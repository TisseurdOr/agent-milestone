"""Auto-record a Claude Code session into the trail store at session end.

Wired as a SessionEnd hook: Claude Code passes the transcript path via stdin
JSON, so nothing is lost even when nobody remembers to checkpoint manually.
"""
import json
import os
import sys

from store import DEFAULT_DB_PATH, TrailStore

DB_PATH = DEFAULT_DB_PATH


def _text_of(block: dict) -> str:
    t = block.get("type")
    if t == "text":
        return block.get("text", "")
    if t == "tool_result":
        c = block.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "\n".join(
                b.get("text", "")
                for b in c
                if isinstance(b, dict) and b.get("type") == "text"
            )
        return json.dumps(c, ensure_ascii=False)
    return ""


def parse_transcript(path: str) -> list[dict]:
    steps = []
    tool_steps = {}  # tool_use_id -> step, to attach results
    for line in open(path, encoding="utf-8"):
        try:
            m = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if m.get("type") not in ("user", "assistant"):
            continue
        msg = m.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            if isinstance(content, str):
                steps.append({"role": "user", "content": content})
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tid = b.get("tool_use_id")
                        if tid in tool_steps:
                            tool_steps[tid]["tool_result"] = _text_of(b)
        elif role == "assistant" and isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    steps.append({"role": "assistant", "content": b.get("text", "")})
                elif b.get("type") == "tool_use":
                    step = {"role": "tool", "tool_name": b.get("name"),
                            "tool_args": b.get("input")}
                    steps.append(step)
                    tool_steps[b.get("id")] = step
        # thinking blocks are private and noisy -> intentionally dropped
    return steps


def auto_name(steps: list[dict]) -> str:
    for s in steps:
        if s.get("role") == "user" and s.get("content"):
            text = s["content"].strip()
            if text.startswith("<command-") or text.startswith("/"):
                continue
            return text[:20] or "session"
    return "session"


def main() -> None:
    raw = sys.stdin.read()
    hook = json.loads(raw) if raw.strip() else {}
    path = hook.get("transcript_path")
    if not path and hook.get("session_id"):
        cand = os.path.expanduser(
            "~/.claude/projects/-Users-cailin/" + hook["session_id"] + ".jsonl"
        )
        if os.path.exists(cand):
            path = cand
    if not path or not os.path.exists(path):
        print("record: no transcript path found", file=sys.stderr)
        return

    steps = parse_transcript(path)
    if not steps:
        print("record: no steps parsed", file=sys.stderr)
        return

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    store = TrailStore(DB_PATH)
    name = auto_name(steps)
    tip = store.checkpoint(name, steps)
    print(f"record: checkpoint '{name}' -> {tip[:12]} ({len(steps)} steps)")

    # 归档自动同步 iCloud：会话结束把查看页刷到 iCloud Drive，手机/别的设备随时能看
    try:
        from view import render
        icloud_dir = os.path.expanduser(
            "~/Library/Mobile Documents/com~apple~CloudDocs/agent-milestone"
        )
        os.makedirs(icloud_dir, exist_ok=True)
        out = render(db_path=DB_PATH, out_path=os.path.join(icloud_dir, "trails.html"))
        print(f"record: 已同步 iCloud 查看页 -> {out}")
    except Exception as ex:
        print(f"record: iCloud 同步跳过 ({ex})", file=sys.stderr)


if __name__ == "__main__":
    main()
