"""End-to-end check: drive the MCP tools the way an agent would."""
import asyncio
import json
import os
import tempfile
from pathlib import Path

# Isolate the e2e run from the user's real ~/.claude database.
_tmp = Path(tempfile.mkdtemp(prefix="agent-milestone-e2e-"))
os.environ["AGENT_MILESTONE_DB"] = str(_tmp / "milestones.db")

import server


def unwrap(r):
    v = r.structured_content
    if isinstance(v, dict) and set(v) == {"result"}:
        v = v["result"]
    if v is None and getattr(r, "content", None):
        first = r.content[0]
        v = getattr(first, "text", first)
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            pass
    return v


async def main():
    steps = [
        {"role": "user", "content": "帮我查一下昨天的对账差异"},
        {"role": "assistant", "content": "我先查 Hive 对账表"},
        {"role": "tool", "tool_name": "query_hive",
         "tool_args": {"sql": "SELECT * FROM reconcile WHERE dt='2026-09-02'"}},
        {"role": "assistant", "content": "有 3 条差异，去 HBase 看原始数据"},
        {"role": "tool", "tool_name": "query_hbase",
         "tool_args": {"table": "reconcile_raw"}},
    ]

    cp = await server.mcp.call_tool("checkpoint", {"name": "对账排查", "steps": steps})
    print("checkpoint ->", unwrap(cp))

    co = await server.mcp.call_tool("checkout", {"name": "对账排查"})
    back = unwrap(co)
    print("checkout 步数 ->", len(back))
    print("checkout 第3步 ->", back[2]["tool_name"])

    br = await server.mcp.call_tool(
        "branch", {"name": "对账排查-分支", "from_ref": "对账排查"}
    )
    print("branch ->", unwrap(br))

    branch_steps = steps[:2] + [{"role": "tool", "tool_name": "query_hbase",
                                 "tool_args": {"table": "reconcile_raw"}}]
    await server.mcp.call_tool(
        "checkpoint", {"name": "对账排查-HBase", "steps": branch_steps}
    )
    d = await server.mcp.call_tool(
        "diff", {"left": "对账排查", "right": "对账排查-HBase"}
    )
    print("diff ->", unwrap(d)["left_only_count"], unwrap(d)["right_only_count"])

    plan = await server.mcp.call_tool("replay", {"name": "对账排查"})
    actions = unwrap(plan)["actions"]
    print("replay 工具调用 ->", [a.get("tool_name") for a in actions if a["type"] == "tool_call"])

    ex = await server.mcp.call_tool("export", {"name": "对账排查"})
    print("--- export markdown ---")
    print(unwrap(ex))


asyncio.run(main())
