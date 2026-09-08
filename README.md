# agent-milestone

> **MCP server 项目**（MCP-native）：给 agent 的对话/任务轨迹做 git 式版本控制——让每次和 agent 的协作都能「记住、回看、撤回、留档」。

## 为什么做

每次和 agent 对话、跑任务之后，都会忘记「当时到底在做什么」。想要一个长期的里程碑：能记住、能回看、能撤回、能导出留档。

## 定位

- **做什么**：MCP server，给 agent 的任务轨迹做 git 式版本控制。
  - 一期：`checkpoint` 存里程碑 / `checkout` 回看+撤回 / `export` 导出 markdown
  - 二期：`branch` 分叉 / `diff` 轨迹 diff / `replay` 重放
- **差异化**：Atlas 管代码（ACP-first），本服务管**对话轨迹**（MCP-native）。
- **不做什么**：多租户、云端同步——刻意不做，本地优先 = 隐私 + 工程判断。

## 核心模型（git 的同一套技巧）

不可变对象 + 指针：

- **step**：轨迹的最小单元——一条 user/assistant 消息、一次 tool 调用或 tool 结果。内容寻址（SHA-256）。
- 每个 step 通过 `parent_hash` 链接成一条链，链就是一次任务的轨迹。
- **milestone（checkpoint）**：一个命名指针，指向某个 step 的 hash。
- 分叉天然免费（branch 只是另一个指针）；diff 便宜（走两条链回到分叉点）。

## 组件

| 文件 | 作用 |
|---|---|
| `store.py` | 存储层：SQLite + git 式模型，含 self-check |
| `server.py` | MCP server，暴露 3 个工具给 agent 主动调 |
| `record.py` | SessionEnd hook，会话结束自动把 transcript 存档 |
| `test_e2e.py` | 端到端测试：按 agent 的方式驱动三个工具 |

## 安装

```bash
cd agent-milestone
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 就一个依赖：mcp
```

## 使用

### 路径一：自动记录（SessionEnd hook）

在 Claude Code 的 `settings.json` 配 SessionEnd hook 指向 `record.py`，每次会话结束自动把整段对话轨迹解析成 step 存库，无需手动操作：

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          { "type": "command", "command": "python3 /path/to/agent-milestone/record.py" }
        ]
      }
    ]
  }
}
```

### 路径二：主动版本控制（MCP 工具）

把 `server.py` 注册成 MCP server 后，agent 在对话里像开发者用 git 一样主动调。

**`checkpoint(name, steps) -> str`** —— 存档
- 输入：一个名字 + 一段轨迹（step 列表）
- 做什么：把轨迹存进 SQLite，给最后一步打上这个名字
- 返回：tip hash（前 12 位）
- 类比：`git commit -m "对账排查"`

**`checkout(name) -> list[dict]`** —— 回看 / 撤回
- 输入：里程碑名字
- 做什么：按名字找到指针，沿 `parent_hash` 往回走，还原整条轨迹
- 返回：轨迹（第一步 → 最后一步）
- 类比：`git checkout 对账排查`

**`export(name) -> str`** —— 导出留档
- 输入：里程碑名字
- 做什么：把轨迹渲染成 markdown
- 返回：markdown 文本，可直接 commit 到 GitHub
- 类比：`git log` 排版成文档

## 存储

统一存到 `~/.claude/agent-milestone/milestones.db`（`store.py` 里的 `DEFAULT_DB_PATH`），`record.py` 和 `server.py` 都引用它。

## 验证

```bash
python store.py      # 自检，应打印 self-check ok
python test_e2e.py   # 端到端：checkpoint → checkout → export
```

## 操作手册

出问题先查 [RUNBOOK.md](./RUNBOOK.md)，每条 = 症状 → 原因 → 处理。

## 状态（2026-09-08 阶段 1 已跑通）

阶段 1 核心闭环已完整验证：store 自检、工具级端到端、以及**新会话里 agent 通过 MCP 实际调 `checkpoint` → `checkout` → `export`** 三连全通。

### 已完成并验证 ✅

| 模块 | 说明 | 验证 |
|---|---|---|
| `store.py` | SQLite + git 式模型（内容寻址 step + 命名指针 milestone） | `python store.py` → self-check ok |
| `server.py` | MCP 工具 checkpoint/checkout/export | 新会话 agent 实际调用通过 |
| `record.py` | SessionEnd hook 自动存档真实对话 | DB 已累计 6.6MB 真实轨迹 |
| `test_e2e.py` | 工具级端到端 | `python test_e2e.py` 通过 |

### 断点（阶段 1 收尾必做，全部关闭）

1. ~~DB 路径不合一~~ ✅ 统一到 `store.py` 的 `DEFAULT_DB_PATH`。
2. ~~`record.py` 真实 `.jsonl` 解析~~ ✅ 真实 transcript 解析 413 步、tool 关联 100%。
3. ~~`server.py` 注册后 agent 实际调用~~ ✅ 2026-09-08 新会话实际调用验证通过。

### 下一步（roadmap）

- [ ] 阶段 2：branch / diff / replay
- [ ] 阶段 3：demo + 推 GitHub

## 铁律

阶段 1 没跑通之前，任何新功能都不许加。
