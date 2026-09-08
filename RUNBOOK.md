# agent-milestone · 操作手册（Runbook）

> 项目出问题，先来这查。每条 = 症状 → 原因 → 处理。修好后把标题状态改成「已修复」。

## 排查速查

```bash
python store.py      # 存储层自检，应打印 self-check ok
python test_e2e.py   # 工具级端到端：checkpoint → checkout → export
```

## 已知问题

### 1. MCP `checkout` 读不到自动记录的数据（已修复 2026-09-03）

- **症状**：agent 调 `checkout` 报 `milestone 'xxx' not found`，但 `record.py` 明明存过。
- **原因**：DB 路径不合一。`record.py` 写 `~/.claude/agent-milestone/milestones.db`，`server.py` 读 `./milestones.db`（项目目录）——两个库。
- **处理**：路径收敛到 `store.py` 的 `DEFAULT_DB_PATH = ~/.claude/agent-milestone/milestones.db`，`record.py` / `server.py` 都引用它。
