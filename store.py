"""Git-style content-addressed store for agent task trajectories.

Model (the same trick git uses — immutable objects + pointers):
- A "step" is an immutable unit of a trajectory: a user/assistant message,
  a tool call, or a tool result. Steps are content-addressed by SHA-256.
- Each step links to its parent via parent_hash, so trajectories form chains.
- A "milestone" (checkpoint) is a named ref pointing at a step hash.
- Branches are refs too; diff walks two chains back to their fork point.

Version 2 adds:
- explicit refs table + branch/list/rename/delete
- reflog
- diff / replay / gc / retention
- write-time secret redaction
- schema migrations for existing v1 databases
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from redact import redact_step, redaction_enabled

SCHEMA_VERSION = 3
DEFAULT_DB_PATH = os.path.expanduser(
    os.getenv("AGENT_MILESTONE_DB", "~/.claude/agent-milestone/milestones.db")
)
VALID_KINDS = {"milestone", "branch"}


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def step_hash(step: dict, parent: str | None = None) -> str:
    # Include parent so identical content in different chains remains distinct.
    payload = json.dumps(
        {"step": step, "parent": parent}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_step(step: dict) -> dict:
    """Coerce a step into the exact shape ``_row_to_step`` reconstructs.

    Hashes must be computed on the normalized shape, otherwise non-string
    content (dicts, numbers) would hash differently from its stored form and
    content addressing would no longer round-trip.
    """
    role = str(step.get("role", ""))
    out: dict[str, Any] = {"role": role}
    content = step.get("content")
    content = "" if content is None else str(content)
    if content or role != "tool":
        out["content"] = content
    if step.get("tool_name"):
        out["tool_name"] = str(step["tool_name"])
    if step.get("tool_args") is not None:
        out["tool_args"] = step["tool_args"]
    if step.get("tool_result") is not None:
        out["tool_result"] = step["tool_result"]
    return out


def _summarize_step(step: dict) -> dict:
    role = step.get("role", "")
    summary: dict[str, Any] = {"role": role}
    if role == "tool":
        summary["tool_name"] = step.get("tool_name")
        args = step.get("tool_args")
        summary["tool_args"] = _clip(args)
    else:
        summary["content"] = _clip(step.get("content", ""))
    return summary


def _clip(value: Any, limit: int = 240) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


class TrailStore:
    def __init__(self, path: str = ":memory:", *, redact: bool | None = None):
        self.path = path
        self._lock = threading.RLock()
        self._redact = redaction_enabled() if redact is None else bool(redact)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ── schema / migration ───────────────────────────────────────────────
    def _migrate(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS steps (
                    hash        TEXT PRIMARY KEY,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL DEFAULT '',
                    tool_name   TEXT,
                    tool_args   TEXT,
                    tool_result TEXT,
                    parent_hash TEXT,
                    created_at  TEXT
                );
                CREATE TABLE IF NOT EXISTS milestones (
                    name      TEXT PRIMARY KEY,
                    step_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refs (
                    name       TEXT PRIMARY KEY,
                    step_hash  TEXT NOT NULL,
                    kind       TEXT NOT NULL DEFAULT 'milestone',
                    parent_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reflog (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_name   TEXT NOT NULL,
                    old_hash   TEXT,
                    new_hash   TEXT,
                    operation  TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column("steps", "created_at", "TEXT")
            self._ensure_column("milestones", "kind", "TEXT DEFAULT 'milestone'")
            self._ensure_column("milestones", "created_at", "TEXT")
            self._ensure_column("milestones", "updated_at", "TEXT")
            self._ensure_column("refs", "parent_ref", "TEXT")
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            # Migrate v1 milestones into the new refs table.
            count = self.conn.execute("SELECT count(*) FROM refs").fetchone()[0]
            if count == 0:
                rows = self.conn.execute("SELECT name, step_hash FROM milestones").fetchall()
                now = _utcnow()
                for row in rows:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO refs"
                        "(name, step_hash, kind, created_at, updated_at) "
                        "VALUES (?, ?, 'milestone', ?, ?)",
                        (row["name"], row["step_hash"], now, now),
                    )
            self.conn.commit()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ── refs / milestones ────────────────────────────────────────────────
    def _resolve_ref(self, name: str) -> str:
        row = self.conn.execute(
            "SELECT step_hash FROM refs WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT step_hash FROM milestones WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            raise KeyError(f"milestone '{name}' not found")
        return row["step_hash"]

    def _log_ref(self, ref_name: str, old_hash: str | None, new_hash: str | None, operation: str) -> None:
        self.conn.execute(
            "INSERT INTO reflog(ref_name, old_hash, new_hash, operation, created_at) VALUES (?, ?, ?, ?, ?)",
            (ref_name, old_hash, new_hash, operation, _utcnow()),
        )

    def checkpoint(self, name: str, steps: list[dict], parent_ref: str | None = None) -> str:
        """Persist a trajectory and point ``name`` at its tip. Returns tip hash."""
        if not name or not name.strip():
            raise ValueError("checkpoint name is required")
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps must be a non-empty list")
        name = name.strip()
        clean_steps = [redact_step(step, enabled=self._redact) for step in steps]
        with self._lock:
            if parent_ref:
                self._resolve_ref(parent_ref)
            old_hash = None
            existing_kind = None
            existing_parent = None
            try:
                old_hash = self._resolve_ref(name)
                row = self.conn.execute(
                    "SELECT kind, parent_ref FROM refs WHERE name = ?", (name,)
                ).fetchone()
                existing_kind = row["kind"] if row else None
                existing_parent = row["parent_ref"] if row else None
            except KeyError:
                pass
            kind = existing_kind or "milestone"
            effective_parent = existing_parent if existing_parent is not None else parent_ref
            parent: str | None = None
            now = _utcnow()
            try:
                for step in clean_steps:
                    normalized = normalize_step(step)
                    h = step_hash(normalized, parent)
                    self.conn.execute(
                        """INSERT OR IGNORE INTO steps
                           (hash, role, content, tool_name, tool_args, tool_result, parent_hash, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            h,
                            normalized["role"],
                            normalized.get("content", ""),
                            normalized.get("tool_name"),
                            json.dumps(normalized.get("tool_args"), ensure_ascii=False, default=str)
                            if normalized.get("tool_args") is not None else None,
                            json.dumps(normalized.get("tool_result"), ensure_ascii=False, default=str)
                            if normalized.get("tool_result") is not None else None,
                            parent,
                            now,
                        ),
                    )
                    parent = h
                self.conn.execute(
                    """INSERT INTO refs(name, step_hash, kind, parent_ref, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(name) DO UPDATE SET step_hash=excluded.step_hash,
                                                      kind=excluded.kind,
                                                      parent_ref=excluded.parent_ref,
                                                      updated_at=excluded.updated_at""",
                    (name, parent, kind, effective_parent, now, now),
                )
                if kind == "milestone":
                    self.conn.execute(
                        """INSERT INTO milestones(name, step_hash, kind, created_at, updated_at)
                           VALUES (?, ?, 'milestone', ?, ?)
                           ON CONFLICT(name) DO UPDATE SET step_hash=excluded.step_hash,
                                                          kind='milestone',
                                                          updated_at=excluded.updated_at""",
                        (name, parent, now, now),
                    )
                self._log_ref(name, old_hash, parent, "checkpoint")
                self.conn.commit()
                return parent  # type: ignore[return-value]
            except Exception:
                self.conn.rollback()
                raise

    def branch(self, name: str, from_ref: str) -> dict:
        """Create a branch ref at ``from_ref``."""
        if not name or not name.strip():
            raise ValueError("branch name is required")
        name = name.strip()
        with self._lock:
            tip = self._resolve_ref(from_ref)
            existing = self.conn.execute("SELECT 1 FROM refs WHERE name = ?", (name,)).fetchone()
            existing = existing or self.conn.execute(
                "SELECT 1 FROM milestones WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                raise ValueError(f"ref '{name}' already exists")
            now = _utcnow()
            self.conn.execute(
                """INSERT INTO refs(name, step_hash, kind, parent_ref, created_at, updated_at)
                   VALUES (?, ?, 'branch', ?, ?, ?)""",
                (name, tip, from_ref, now, now),
            )
            self._log_ref(name, None, tip, "branch")
            self.conn.commit()
            return {"name": name, "kind": "branch", "from": from_ref, "parent_ref": from_ref, "tip": tip}

    def checkout(self, name: str) -> list[dict]:
        """Return the trajectory (root -> tip) recorded at ``name``."""
        with self._lock:
            return self._walk(self._resolve_ref(name))

    def export(self, name: str) -> str:
        """Render milestone ``name`` as markdown, ready to commit to GitHub."""
        steps = self.checkout(name)
        lines = [f"# Milestone: {name}", ""]
        for s in steps:
            if s.get("tool_name"):
                lines.append(f"### [tool] {s['tool_name']}")
                if s.get("tool_args"):
                    lines.append("```")
                    lines.append(json.dumps(s["tool_args"], ensure_ascii=False, indent=2))
                    lines.append("```")
            else:
                lines.append(f"### {s['role']}")
                lines.append(s.get("content", ""))
            lines.append("")
        return "\n".join(lines)

    def list_refs(self, kind: str | None = None) -> list[dict]:
        """List milestones/branches with tip, step count, and timestamps."""
        sql = "SELECT name, step_hash, kind, parent_ref, created_at, updated_at FROM refs"
        params: tuple[Any, ...] = ()
        if kind:
            sql += " WHERE kind = ?"
            params = (kind,)
        sql += " ORDER BY updated_at DESC, name ASC"
        rows = self.conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            count = self._chain_length(row["step_hash"])
            result.append({
                "name": row["name"],
                "kind": row["kind"],
                "parent_ref": row["parent_ref"],
                "tip": row["step_hash"],
                "steps": count,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return result

    def list_milestones(self) -> list[dict]:
        return self.list_refs(kind="milestone")

    def rename(self, old_name: str, new_name: str) -> dict:
        """Rename a ref without touching immutable steps."""
        if not new_name or not new_name.strip():
            raise ValueError("new name is required")
        new_name = new_name.strip()
        with self._lock:
            tip = self._resolve_ref(old_name)
            existing = self.conn.execute(
                "SELECT 1 FROM refs WHERE name = ?", (new_name,)
            ).fetchone()
            existing = existing or self.conn.execute(
                "SELECT 1 FROM milestones WHERE name = ?", (new_name,)
            ).fetchone()
            if existing:
                raise ValueError(f"ref '{new_name}' already exists")
            row = self.conn.execute(
                "SELECT kind, parent_ref, created_at FROM refs WHERE name = ?", (old_name,)
            ).fetchone()
            kind = row["kind"] if row else "milestone"
            parent_ref = row["parent_ref"] if row else None
            created_at = row["created_at"] if row else _utcnow()
            now = _utcnow()
            self.conn.execute(
                """INSERT INTO refs(name, step_hash, kind, parent_ref, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (new_name, tip, kind, parent_ref, created_at, now),
            )
            self._delete_ref_rows(old_name)
            self.conn.execute(
                "UPDATE refs SET parent_ref = ? WHERE parent_ref = ?", (new_name, old_name)
            )
            self._log_ref(old_name, tip, None, "rename_from")
            self._log_ref(new_name, None, tip, "rename_to")
            self.conn.commit()
            return {"old": old_name, "new": new_name, "kind": kind, "tip": tip}

    def delete(self, name: str) -> dict:
        """Delete a ref. Immutable steps remain until ``gc``."""
        with self._lock:
            tip = self._resolve_ref(name)
            self._delete_ref_rows(name)
            self.conn.execute(
                "UPDATE refs SET parent_ref = NULL WHERE parent_ref = ?", (name,)
            )
            self._log_ref(name, tip, None, "delete")
            self.conn.commit()
            return {"name": name, "deleted_tip": tip}

    def set_parent(self, name: str, parent_ref: str | None) -> dict:
        """Move a ref into a branch folder (set its parent_ref)."""
        with self._lock:
            tip = self._resolve_ref(name)
            if parent_ref:
                if parent_ref == name:
                    raise ValueError("ref cannot be its own parent")
                self._resolve_ref(parent_ref)  # validate the folder exists
            now = _utcnow()
            self.conn.execute(
                "UPDATE refs SET parent_ref = ?, updated_at = ? WHERE name = ?",
                (parent_ref, now, name),
            )
            self._log_ref(name, tip, tip, "set_parent")
            self.conn.commit()
            return {"name": name, "parent_ref": parent_ref}

    def rollback(self, name: str, to_ref: str) -> dict:
        """Move a ref pointer back to another ref (history-preserving rollback).

        This is a trajectory-level rollback: it changes where the ref points,
        but never deletes immutable steps. The old tip stays in reflog.
        """
        with self._lock:
            old_tip = self._resolve_ref(name)
            target_tip = self._resolve_ref(to_ref)
            row = self.conn.execute(
                "SELECT kind, parent_ref, created_at FROM refs WHERE name = ?", (name,)
            ).fetchone()
            kind = row["kind"] if row else "milestone"
            parent_ref = row["parent_ref"] if row else None
            now = _utcnow()
            self.conn.execute(
                """INSERT INTO refs(name, step_hash, kind, parent_ref, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET step_hash=excluded.step_hash,
                                                  kind=excluded.kind,
                                                  parent_ref=excluded.parent_ref,
                                                  updated_at=excluded.updated_at""",
                (name, target_tip, kind, parent_ref, row["created_at"] if row else now, now),
            )
            if kind == "milestone":
                self.conn.execute(
                    "UPDATE milestones SET step_hash = ?, updated_at = ? WHERE name = ?",
                    (target_tip, now, name),
                )
            self._log_ref(name, old_tip, target_tip, "rollback")
            self.conn.commit()
            return {"name": name, "kind": kind, "from_tip": old_tip, "to_tip": target_tip, "target": to_ref}

    def undo_last(self, name: str) -> dict:
        """Move a ref back to the previous tip recorded in reflog.

        Only checkpoint/rollback operations are considered. Repeated undo keeps
        walking backwards through history instead of toggling the last change.
        """
        with self._lock:
            row = self.conn.execute(
                """SELECT old_hash, new_hash, operation
                   FROM reflog
                   WHERE ref_name = ? AND old_hash IS NOT NULL
                     AND operation IN ('checkpoint', 'rollback')
                   ORDER BY id DESC LIMIT 1""",
                (name,),
            ).fetchone()
            if row is None or not row["old_hash"]:
                raise ValueError(f"ref '{name}' has no previous operation to undo")
            old_tip = self._resolve_ref(name)
            target_tip = row["old_hash"]
            ref_row = self.conn.execute(
                "SELECT kind, parent_ref, created_at FROM refs WHERE name = ?", (name,)
            ).fetchone()
            kind = ref_row["kind"] if ref_row else "milestone"
            now = _utcnow()
            self.conn.execute(
                "UPDATE refs SET step_hash = ?, updated_at = ? WHERE name = ?",
                (target_tip, now, name),
            )
            if kind == "milestone":
                self.conn.execute(
                    "UPDATE milestones SET step_hash = ?, updated_at = ? WHERE name = ?",
                    (target_tip, now, name),
                )
            self._log_ref(name, old_tip, target_tip, "undo")
            self.conn.commit()
            return {"name": name, "kind": kind, "from_tip": old_tip, "to_tip": target_tip, "undid": row["operation"]}

    def _delete_ref_rows(self, name: str) -> None:
        self.conn.execute("DELETE FROM refs WHERE name = ?", (name,))
        self.conn.execute("DELETE FROM milestones WHERE name = ?", (name,))

    def reflog(self, name: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            if name:
                rows = self.conn.execute(
                    "SELECT * FROM reflog WHERE ref_name = ? ORDER BY id DESC LIMIT ?",
                    (name, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM reflog ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(row) for row in rows]

    def diff(self, left: str, right: str) -> dict:
        """Return a git-like diff between two refs/chains."""
        left_chain = self._chain_hashes(left)
        right_chain = self._chain_hashes(right)
        common = 0
        for a, b in zip(left_chain, right_chain):
            if a != b:
                break
            common += 1
        return {
            "left": left,
            "right": right,
            "fork_hash": left_chain[common - 1] if common else None,
            "common_steps": common,
            "left_only": [self._summarize_hash(h) for h in left_chain[common:]],
            "right_only": [self._summarize_hash(h) for h in right_chain[common:]],
            "left_only_count": len(left_chain) - common,
            "right_only_count": len(right_chain) - common,
        }

    def replay(self, name: str, execute: bool = False) -> dict:
        """Return a deterministic replay plan without executing tools."""
        if execute:
            raise ValueError("execute=True is disabled: replay is dry-run only in the OSS server")
        steps = self.checkout(name)
        actions = []
        for idx, step in enumerate(steps, start=1):
            role = step.get("role")
            if role == "tool":
                actions.append({
                    "index": idx,
                    "type": "tool_call",
                    "tool_name": step.get("tool_name"),
                    "tool_args": step.get("tool_args"),
                    "status": "dry_run",
                })
            else:
                actions.append({
                    "index": idx,
                    "type": "message",
                    "role": role,
                    "content": step.get("content", ""),
                })
        return {"name": name, "steps": len(steps), "execute": False, "actions": actions}

    def gc(self, dry_run: bool = True) -> dict:
        """Delete steps unreachable from any ref. Safe by default."""
        with self._lock:
            reachable: set[str] = set()
            for row in self.conn.execute("SELECT step_hash FROM refs").fetchall():
                reachable.update(self._chain_hashes_by_tip(row["step_hash"]))
            for row in self.conn.execute("SELECT step_hash FROM milestones").fetchall():
                reachable.update(self._chain_hashes_by_tip(row["step_hash"]))
            all_hashes = {row[0] for row in self.conn.execute("SELECT hash FROM steps").fetchall()}
            unreachable = sorted(all_hashes - reachable)
            if not dry_run:
                self.conn.executemany("DELETE FROM steps WHERE hash = ?", [(h,) for h in unreachable])
                self.conn.commit()
            return {
                "dry_run": dry_run,
                "reachable": len(reachable),
                "unreachable": len(unreachable),
                "deleted": 0 if dry_run else len(unreachable),
            }

    def prune(self, *, older_than_days: int | None = None, keep_last: int | None = None, dry_run: bool = True) -> dict:
        """Delete old refs (optionally keeping the most recent N) then gc."""
        refs = self.list_refs()
        refs.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        targets: list[str] = []
        if keep_last is not None:
            targets.extend(r["name"] for r in refs[keep_last:])
        if older_than_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            for r in refs:
                try:
                    updated = datetime.fromisoformat(r["updated_at"])
                except (TypeError, ValueError):
                    continue
                if updated < cutoff and r["name"] not in targets:
                    targets.append(r["name"])
        if not dry_run:
            with self._lock:
                for name in targets:
                    try:
                        self.delete(name)
                    except KeyError:
                        pass
        result = self.gc(dry_run=dry_run)
        result.update({"dry_run": dry_run, "refs_pruned": targets})
        return result

    def stats(self) -> dict:
        with self._lock:
            steps = self.conn.execute("SELECT count(*) FROM steps").fetchone()[0]
            refs = self.conn.execute("SELECT count(*) FROM refs").fetchone()[0]
            size = os.path.getsize(self.path) if self.path != ":memory:" and os.path.exists(self.path) else 0
            return {"schema_version": SCHEMA_VERSION, "steps": steps, "refs": refs, "db_bytes": size}

    def close(self) -> None:
        self.conn.close()

    # ── graph walk / helpers ─────────────────────────────────────────────
    def _chain_hashes(self, name: str) -> list[str]:
        return self._chain_hashes_by_tip(self._resolve_ref(name))

    def _chain_hashes_by_tip(self, tip: str | None) -> list[str]:
        hashes: list[str] = []
        seen: set[str] = set()
        h = tip
        while h is not None:
            if h in seen:
                raise RuntimeError(f"cycle detected in step chain at {h}")
            seen.add(h)
            hashes.append(h)
            row = self.conn.execute("SELECT parent_hash FROM steps WHERE hash = ?", (h,)).fetchone()
            if row is None:
                break
            h = row["parent_hash"]
        hashes.reverse()
        return hashes

    def _chain_length(self, tip: str | None) -> int:
        return len(self._chain_hashes_by_tip(tip))

    def _summarize_hash(self, h: str) -> dict:
        row = self.conn.execute("SELECT * FROM steps WHERE hash = ?", (h,)).fetchone()
        if row is None:
            return {"hash": h, "missing": True}
        step = self._row_to_step(row)
        return {"hash": h, **_summarize_step(step)}

    def _walk(self, tip_hash: str) -> list[dict]:
        result = []
        for h in self._chain_hashes_by_tip(tip_hash):
            row = self.conn.execute("SELECT * FROM steps WHERE hash = ?", (h,)).fetchone()
            if row is None:
                raise KeyError(f"step {h} not found")
            result.append(self._row_to_step(row))
        return result

    def _row_to_step(self, row: sqlite3.Row) -> dict:
        step: dict[str, Any] = {"role": row["role"]}
        if row["content"] or row["role"] != "tool":
            step["content"] = row["content"] or ""
        if row["tool_name"]:
            step["tool_name"] = row["tool_name"]
        if row["tool_args"]:
            step["tool_args"] = _parse_json(row["tool_args"])
        if row["tool_result"]:
            step["tool_result"] = _parse_json(row["tool_result"])
        return step


if __name__ == "__main__":
    store = TrailStore(":memory:", redact=True)
    base = [
        {"role": "user", "content": "查一下上个月的对账差异"},
        {"role": "assistant", "content": "我先查 hive"},
        {"role": "tool", "tool_name": "query_hive", "tool_args": {"sql": "select 1"}},
    ]
    store.checkpoint("main", base)
    alt = base[:2] + [{"role": "tool", "tool_name": "query_hbase", "tool_args": {"table": "t"}}]
    store.checkpoint("alt", alt)
    assert store.checkout("main")[2]["tool_name"] == "query_hive"
    assert store.diff("main", "alt")["right_only"][0]["tool_name"] == "query_hbase"
    store.branch("feature", "main")
    assert any(r["name"] == "feature" and r["kind"] == "branch" for r in store.list_refs())
    assert store.replay("main")["actions"][2]["type"] == "tool_call"
    store.rename("alt", "alt2")
    store.delete("alt2")
    assert store.gc(dry_run=False)["deleted"] >= 0
    store.checkpoint("secret", [{"role": "user", "content": "api_key=sk-abcdefghijklmnopqrstuvwxyz"}])
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(store.checkout("secret"))
    assert "Milestone: main" in store.export("main")
    print("self-check ok")
