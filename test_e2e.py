"""End-to-end check: drive the MCP tools the way an agent would."""
import asyncio
import json

import server


def unwrap(r):
    v = r.structured_content
    if isinstance(v, dict) and set(v) == {"result"}:
        v = v["result"]
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
    print("checkout 第3步 ->", back[2]["tool_name"], back[2]["tool_args"])

    ex = await server.mcp.call_tool("export", {"name": "对账排查"})
    print("--- export markdown ---")
    print(unwrap(ex))


asyncio.run(main())
