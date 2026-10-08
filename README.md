# agent-milestone

> **MCP server 项目**（MCP-native）：给 Agent 的对话/任务轨迹做 git 式版本控制——让每次和 Agent 的协作都能「记住、回看、分支、对比、重放、留档」。

## 项目介绍

agent-milestone 是一个 **MCP-native 的 Agent 轨迹版本控制系统**。

它把 Agent 的对话、工具调用和任务过程抽象成 Git 的同一套模型：

```text
step         = 不可变对象（user / assistant / tool call / tool result）
step hash    = SHA-256 内容寻址
parent_hash  = 把 step 连成一条任务轨迹
milestone    = 命名 ref，指向某个 step
branch       = 另一个 ref，从某个 milestone 分叉
```

在这个模型上提供：

- **版本控制**：checkpoint / checkout / branch / diff / rollback / undo
- **轨迹重放**：replay dry-run，只输出工具调用计划，不执行工具
- **历史管理**：reflog / rename / delete / gc / prune
- **自动记录**：Claude Code SessionEnd hook 自动解析 transcript
- **Agent 接入**：MCP server，让 Agent 主动调版本控制工具
- **本地控制台**：GitHub 风格分支树、folder/branch/tag 图标、Diff 标签页
- **隐私优先**：本地 SQLite + 写入前密钥脱敏

可以这样理解：

> Git 管代码；agent-milestone 管 Agent 的对话、工具调用和决策轨迹。两者可以配合使用：Git 记录代码状态，agent-milestone 记录当时 Agent 做了什么、为什么这么做。

它适合：

- Claude Code / Codex / MCP Agent 的长期任务
- 多方案排查：同一问题分叉成不同 branch
- 复盘和审计：回到某个 milestone，看当时完整工具调用
- 安全回滚：移动 ref 指针，不删除历史 step
- 导出留档：把轨迹渲染成 Markdown 提交到 GitHub

## 为什么做

每次和 agent 对话、跑任务之后，都会忘记「当时到底在做什么」。想要一个长期的里程碑：能记住、能回看、能撤回、能导出留档。

## 定位

- **做什么**：MCP server，给 Agent 的任务轨迹做 git 式版本控制。
  - 核心：`checkpoint` 存里程碑 / `checkout` 回看 / `export` 导出 markdown
  - 版本控制：`branch` 分叉 / `diff` 轨迹对比 / `replay` 安全重放计划
  - 管理：`list_milestones` / `rename` / `delete` / `gc` / `prune` / `reflog`
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
| `server.py` | MCP server，暴露 checkpoint/checkout/export/branch/diff/replay 等工具 |
| `record.py` | SessionEnd hook，会话结束自动把 transcript 存档 |
| `view.py` | 只读查看器：把库里所有轨迹渲染成自包含 HTML（零依赖、浏览器直开） |
| `ui.py` | 本地 Web 控制台：分支树、Diff、Replay、Reflog、回滚/撤回、导出 |
| `redact.py` | 写入前做 API key / token / password / 连接串脱敏 |
| `tests/` | pytest：存储、分支、diff、replay、回滚、迁移、脱敏、transcript 解析 |

## 安装

```bash
cd agent-milestone
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"   # 运行 + pytest/ruff 开发依赖
# 或最小安装：pip install -e .
```

## 使用

### 路径 0：本地 Web 控制台（人用）

```bash
python ui.py
# 或安装后：
agent-milestone-ui
```

打开 `http://127.0.0.1:8765`，可以在浏览器里完成：

- 浏览所有 milestone / branch
- 查看完整轨迹
- 新建 checkpoint
- 从任意 ref 新建 branch
- 把 milestone 移动到某个 branch 文件夹
- 选择两个 ref 做 diff
- replay dry-run
- 回滚到指定 ref / 撤回上一个操作
- rename / delete
- 查看 reflog
- 导出 Markdown
- GC dry-run

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

**`branch(name, from_ref) -> dict`** —— 分叉

- 类比：`git branch feature main`
- 分支只是另一个 ref，不会复制 step。

**`diff(left, right) -> dict`** —— 轨迹对比

- 沿两条链回溯到共同前缀，返回 fork hash、左独有、右独有 step 摘要。

**`replay(name) -> dict`** —— 安全重放

- 默认 dry-run，只返回工具调用计划，不执行任何工具。
- 需要真实执行时由调用方自己接 executor。

**`reflog(name?) -> list[dict]`** —— ref 历史

- checkpoint / branch / rename / delete / prune 全记录。

**`gc(dry_run=True)` / `prune(...)`** —— 存储回收

- `gc` 删除没有任何 ref 可达的 step。
- `prune` 按时间或保留数量清理旧 ref，再触发 gc。

**`rollback(name, to_ref)` / `undo_last(name)`** —— 回滚

- `rollback` 把 ref 指针移回指定 milestone/branch，不删除历史 step。
- `undo_last` 沿 reflog 撤回最近一次 checkpoint/rollback。

**`set_parent(name, parent_ref)`** —— 分支文件夹

- 把已有 milestone/branch 移动到某个 branch 文件夹下，控制台会按树形展示。

## 隐私与存储

- 默认写入前脱敏 API key、Bearer token、password、Redis/Postgres 连接串。
- DB 路径可通过 `AGENT_MILESTONE_DB` 覆盖。
- 不想同步 iCloud 查看页时设置 `AGENT_MILESTONE_AUTO_ICLOUD=0`。

## 存储

统一存到 `~/.claude/agent-milestone/milestones.db`（`store.py` 里的 `DEFAULT_DB_PATH`），`record.py` 和 `server.py` 都引用它。

## 验证

```bash
python store.py      # 自检，应打印 self-check ok
python test_e2e.py   # 端到端：checkpoint → checkout → export
python view.py       # 生成 trails.html 轨迹查看页（浏览器直开，看所有里程碑+step）
```

## 操作手册

出问题先查 [RUNBOOK.md](./RUNBOOK.md)，每条 = 症状 → 原因 → 处理。

## 状态（2026-10-08 阶段 2 + 本地控制台已跑通）

阶段 1 + 阶段 2 + 本地控制台已完整验证：store 自检、pytest、工具级端到端、以及新会话里 Agent 通过 MCP 实际调用核心工具。

### 已完成并验证 ✅

| 模块 | 说明 | 验证 |
|---|---|---|
| `store.py` | SQLite + git 式模型（内容寻址 step + 命名指针 milestone） | `python store.py` → self-check ok |
| `server.py` | MCP 工具 checkpoint/checkout/export/branch/diff/replay/rollback/undo/reflog/gc/prune | `test_e2e.py` 全通 |
| `record.py` | SessionEnd hook 自动存档真实对话 | 真实库累计 4800+ steps、十余个 milestone |
| `ui.py` | 本地 Web 控制台：分支树 / Diff tab / Replay / Reflog / 回滚 / 导出 | 浏览器实际点击验证通过 |
| `tests/` + `test_e2e.py` | pytest + 工具级端到端 | 16 pytest + e2e 通过 |

### 断点（阶段 1 收尾必做，全部关闭）

1. ~~DB 路径不合一~~ ✅ 统一到 `store.py` 的 `DEFAULT_DB_PATH`。
2. ~~`record.py` 真实 `.jsonl` 解析~~ ✅ 真实 transcript 解析 413 步、tool 关联 100%。
3. ~~`server.py` 注册后 agent 实际调用~~ ✅ 2026-09-08 新会话实际调用验证通过。

### 下一步（roadmap）

- [x] 阶段 2：branch / diff / replay / reflog / gc / prune
- [x] 本地 Web 控制台：分支树 / folder 图标 / Diff tab / 回滚 / 导出
- [ ] 阶段 3：真实 demo 视频、`pipx`/`uvx` 安装体验、发布到 PyPI
- [ ] 数据库加密 / retention 策略

## 铁律

阶段 1 没跑通之前，任何新功能都不许加。
