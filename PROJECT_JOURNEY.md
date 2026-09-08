# agent-milestone · 项目路程

> 一个 MCP-native 的 agent 任务轨迹版本控制系统：让 agent 的每次对话/任务都能「记住、撤回、复盘、留档」。

## 起点：为什么做这个（痛点）

每次和 agent 对话/跑任务之后，都会忘记「当时我们到底在做什么」。想要一个长期的「里程碑」——能记住、能回看、能撤回、能导出留档。

## 定位：做什么，不做什么

- **做什么**：MCP server，给 agent 的任务轨迹做 git 式版本控制。
  - 一期：`checkpoint` 存里程碑 / `checkout` 回看+撤回 / `export` 导出 markdown 到 GitHub
  - 二期：`branch` 分叉 / `diff` 轨迹 diff / `replay` 重放
- **差异化**：Atlas 管代码（ACP-first），本服务管**对话轨迹**（MCP-native）。
- **不做什么**：多租户、云端同步（刻意不做，本地优先 = 隐私 + 工程判断）。

## 技术决策

- 存储：SQLite，git 式模型（内容寻址的不可变 step + 指针 ref）。
- 捕获：显式（agent 自己调 checkpoint/branch，像开发者一样用版本控制）。
- 语言：Python（最快交付）。
- 撤回粒度 = 里程碑级（回到上一个 checkpoint，不是逐步 Ctrl+Z）。

## 计划

- **阶段 0 · 环境（半天）**：venv + MCP SDK，Hello World server 挂进 Claude Code。
- **阶段 1 · 核心闭环（3~5 天）**：SQLite + checkpoint/checkout/export。
- **阶段 2 · 版本控制外壳（3~5 天）**：branch/diff/replay。
- **阶段 3 · 演示 + 文档（2~3 天）**：demo 视频 + README + 推 GitHub。

## 铁律

阶段 1 没跑通之前，任何新功能都不许加。

## 状态

- [x] 设计定稿（2026-09-03）
- [x] 阶段 1 核心闭环（checkpoint/checkout/export + SessionEnd 自动记录，2026-09-08 已跑通）
- [ ] 阶段 2 外壳（branch/diff/replay）
- [ ] 阶段 3 演示 + 推 GitHub
