"""Git-style content-addressed store for agent task trajectories.

Model (the same trick git uses — immutable objects + pointers):
- A "step" is an immutable unit of a trajectory: a user/assistant message,
  a tool call, or a tool result. Steps are content-addressed by SHA-256.
- Each step links to its parent via parent_hash, so trajectories form chains.
- A "milestone" (checkpoint) is a named ref pointing at a step hash.

Branching is free (a branch is just another ref). Diff is cheap (walk two
chains back to their fork point).
"""
import hashlib
import json
import os
import sqlite3
import threading


DEFAULT_DB_PATH = os.path.expanduser("~/.claude/agent-milestone/milestones.db")


def step_hash(step: dict, parent=None) -> str:
    # include parent so shared content in different chains doesn't corrupt the walk
    payload = json.dumps({"step": step, "parent": parent}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TrailStore:
    def __init__(self, path: str = ":memory:"):
        # MCP runs tools in worker threads; allow cross-thread use and
        # serialize with a lock (single-user local tool, write rate is
        # agent-paced anyway).
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS steps (
                hash        TEXT PRIMARY KEY,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL DEFAULT '',
                tool_name   TEXT,
                tool_args   TEXT,
                tool_result TEXT,
                parent_hash TEXT
            );
            CREATE TABLE IF NOT EXISTS milestones (
                name      TEXT PRIMARY KEY,
                step_hash TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def checkpoint(self, name: str, steps: list[dict]) -> str:
        """Persist a trajectory and point `name` at its tip. Returns tip hash."""
        with self._lock:
            parent = None
            for step in steps:
                h = step_hash(step, parent)
                self.conn.execute(
                    """INSERT OR IGNORE INTO steps
                       (hash, role, content, tool_name, tool_args, tool_result, parent_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        h,
                        step.get("role", ""),
                        step.get("content", ""),
                        step.get("tool_name"),
                        json.dumps(step.get("tool_args"), ensure_ascii=False),
                        json.dumps(step.get("tool_result"), ensure_ascii=False),
                        parent,
                    ),
                )
                parent = h
            self.conn.execute(
                "INSERT OR REPLACE INTO milestones (name, step_hash) VALUES (?, ?)",
                (name, parent),
            )
            self.conn.commit()
            return parent

    def checkout(self, name: str) -> list[dict]:
        """Return the trajectory (root -> tip) recorded at milestone `name`."""
        with self._lock:
            row = self.conn.execute(
                "SELECT step_hash FROM milestones WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                raise KeyError(f"milestone '{name}' not found")
            return self._walk(row["step_hash"])

    def export(self, name: str) -> str:
        """Render milestone `name` as markdown, ready to commit to GitHub."""
        steps = self.checkout(name)
        lines = [f"# Milestone: {name}", ""]
        for s in steps:
            if s.get("tool_name"):
                lines.append(f"### [tool] {s['tool_name']}")
                if s.get("tool_args"):
                    lines.append("```")
                    lines.append(s["tool_args"])
                    lines.append("```")
            else:
                lines.append(f"### {s['role']}")
                lines.append(s.get("content", ""))
            lines.append("")
        return "\n".join(lines)

    def _walk(self, tip_hash: str) -> list[dict]:
        steps = []
        h = tip_hash
        while h is not None:
            row = self.conn.execute(
                "SELECT * FROM steps WHERE hash = ?", (h,)
            ).fetchone()
            if row is None:
                raise KeyError(f"step {h} not found")
            steps.append(self._row_to_step(row))
            h = row["parent_hash"]
        steps.reverse()
        return steps

    def _row_to_step(self, row) -> dict:
        step = {"role": row["role"], "content": row["content"]}
        if row["tool_name"]:
            step["tool_name"] = row["tool_name"]
        if row["tool_args"]:
            step["tool_args"] = row["tool_args"]
        if row["tool_result"]:
            step["tool_result"] = row["tool_result"]
        return step


if __name__ == "__main__":
    # Self-check: two branches sharing a prefix, forking at step 3.
    store = TrailStore(":memory:")
    base = [
        {"role": "user", "content": "查一下上个月的对账差异"},
        {"role": "assistant", "content": "我先查 hive"},
        {"role": "tool", "tool_name": "query_hive", "tool_args": {"sql": "select 1"}},
    ]
    store.checkpoint("main", base)

    alt = base[:2] + [
        {"role": "tool", "tool_name": "query_hbase", "tool_args": {"table": "t"}},
    ]
    store.checkpoint("alt", alt)

    assert [s["content"] for s in store.checkout("main")][:2] == [
        "查一下上个月的对账差异",
        "我先查 hive",
    ]
    assert store.checkout("alt")[2]["tool_name"] == "query_hbase"
    assert "Milestone: main" in store.export("main")
    assert "query_hive" in store.export("main")
    print("self-check ok")
