# Reins

[English](README.md)

> 约束足够明确，同时保留足够自由。

Reins 是一个面向 AI 辅助编码仓库的 Python 工具集，用来把任务、规范、worktree 和流水线管理结构化地落到仓库里。就当前代码实现而言，`reins` CLI 是主要入口，而 `.reins/` 目录是整个工作控制面的核心。

它的目标不是让 agent 每次运行时都重新猜测项目状态，而是把这些状态显式写成仓库工件：

- `.reins/tasks/` 下的任务元数据与 PRD
- `.reins/spec/` 下的分层规范
- 面向 `implement`、`check`、`debug` 的 JSONL 上下文文件
- 用于并行开发的受跟踪 git worktree
- 按开发者划分的工作区日志与报表
- 带事件审计能力的 pipeline 状态与执行记录

## 当前项目实际提供的能力

根据仓库当前实现，Reins 已经具备这些功能：

- 基于 Typer 的 CLI，用于初始化和操作 Reins 仓库
- 针对 Codex、Claude Code、Cursor 的一等平台配置器
- 任务生命周期命令，并将任务工件导出到文件系统
- 规范初始化、拉取、更新、检查表与校验流程
- 基于 PRD 和 spec layer 的 package-aware 上下文初始化
- 面向并行 agent 执行的受跟踪 git worktree 管理
- 开发者 / workspace 跟踪、统计与清理命令
- 存放在 `.reins/pipelines/` 下、由 YAML 定义的多阶段流水线
- 可选的 `aiohttp` HTTP API，用于更底层的 run 编排

## 安装

Reins 需要 Python 3.11 及以上版本。

以可编辑模式安装：

```bash
pip install -e ".[dev]"
```

安装后会暴露 `reins` 命令：

```bash
reins --help
```

## 快速开始

下面是一条从初始化仓库、登记开发者、创建任务、注入上下文到运行流水线的最短路径：

```bash
reins init --platform codex --project-type backend
reins developer init peppa
reins spec init --package cli

reins task create "Implement JWT auth" \
  --type backend \
  --priority P0 \
  --acceptance "JWT tokens are issued after login" \
  --acceptance "Protected routes reject invalid tokens"

reins task list
reins task init-context <task-id> backend
reins task start <task-id>

reins spec checklist --task <task-id> --validate
reins worktree create feature-jwt --task <task-id>
reins pipeline list
reins pipeline run standard --task .reins/tasks/<task-id>
reins status --verbose
```

如果你想启用 shell 自动补全：

```bash
reins completion zsh > ~/.reins-completion.zsh
source ~/.reins-completion.zsh
```

## `reins init` 会生成什么

初始化之后，Reins 会先搭出 `.reins/` 目录结构：

```text
.reins/
  journal.jsonl
  .current-task
  tasks/
  spec/
  workspace/
```

随着 CLI 的使用，还会逐步生成更多派生工件：

```text
.reins/tasks/<task-id>/
  task.json
  prd.md
  implement.jsonl
  check.jsonl
  debug.jsonl
  pipeline-state.json

.reins/pipelines/
  debug.yaml
  research-heavy.yaml
  standard.yaml
  test-driven.yaml
```

这些文件不是仅供内部使用的缓存。它们本身就是面向人和工具的工作界面，agent、hook 和开发者都可以直接读取。

## 命令概览

### `reins init`

初始化 `.reins/`，自动检测或接收目标平台，应用平台模板，并迁移标准 spec 布局。

常用选项：

- `--platform`：显式指定平台，例如 `codex`、`claude`、`cursor`
- `--project-type`：指定 `frontend`、`backend` 或 `fullstack`
- `--developer`：初始化模板渲染时使用的开发者身份
- `--package`：为 monorepo 生成 package 级别的 spec scaffolding

### `reins status`

显示当前任务、任务状态、活跃 agent 数、开发者身份、workspace journal 数量、git 改动数以及最近的 journal 活动。加上 `--verbose` 可以查看更完整的信息。

### `reins developer ...`

管理保存在 `.reins/.developer` 中的当前开发者身份。

常用命令：

- `reins developer init`
- `reins developer show`
- `reins developer workspace-info`

### `reins workspace ...`

查看和维护按开发者隔离的 workspace 数据。

常用命令：

- `reins workspace init`
- `reins workspace list`
- `reins workspace stats`
- `reins workspace cleanup`
- `reins workspace report`

### `reins task ...`

创建、导出并推进任务工件。

常用命令：

- `reins task create`
- `reins task list`
- `reins task show`
- `reins task start`
- `reins task finish`
- `reins task archive`
- `reins task init-context`
- `reins task add-context`

当你执行 `reins task init-context <task-id> <backend|frontend|fullstack>` 时，Reins 会自动生成：

- `implement.jsonl`
- `check.jsonl`
- `debug.jsonl`

这些上下文文件由任务 PRD 和 `.reins/spec/` 下的相关 spec layer 共同组成。

### `reins spec ...`

管理分层规范。

常用命令：

- `reins spec init`
- `reins spec update`
- `reins spec fetch`
- `reins spec list`
- `reins spec validate`
- `reins spec add-layer`
- `reins spec checklist`

默认的全局 layer 包括：

- `backend`
- `frontend`
- `unit-test`
- `integration-test`
- `guides`

对于 package-based 仓库，Reins 还可以在 `.reins/spec/<package>/...` 下创建 package 局部 layer。

### `reins worktree ...`

创建并跟踪与任务或 agent lane 绑定的 git worktree。

常用命令：

- `reins worktree create`
- `reins worktree list`
- `reins worktree verify`
- `reins worktree cleanup`
- `reins worktree cleanup-orphans`
- `reins worktree prune`

### `reins journal ...`

查看 CLI 工作流背后的事件日志。

常用命令：

- `reins journal show`
- `reins journal replay`
- `reins journal export`
- `reins journal stats`

### `reins pipeline ...`

针对任务目录执行命名流水线。

常用命令：

- `reins pipeline list`
- `reins pipeline run`
- `reins pipeline status`
- `reins pipeline cancel`

## 内置流水线

当前仓库在 `.reins/pipelines/` 下内置了四条流水线：

| 流水线 | 用途 |
| --- | --- |
| `standard` | 标准的 research -> implement -> check -> verify 流程 |
| `research-heavy` | 先并行研究，再实现与验证 |
| `test-driven` | 先定义验证目标，再进入实现 |
| `debug` | 先定位故障，再修复并验证 |

流水线本质上是声明式 YAML。每个 stage 会定义：

- stage 类型，例如 `research`、`implement`、`check`、`verify`、`debug`
- `agent_type`
- prompt 模板
- 依赖顺序
- 重试策略
- 可选的上下文文件注入

## spec 与上下文的分层规则

当前实现中，上下文解析同时考虑 package 和 layer：

- package-local spec layer 优先于全局 layer
- 任务类型会决定需要选取哪些 layer
- `guides` 会在任务类型相关 layer 之后追加
- 在编译上下文前，会去重重复 spec source

这意味着你既可以在全局 layer 中维护团队通用规范，也可以针对某个 package 做局部覆盖。

## 平台支持

虽然 Reins 内部有更宽的 platform registry，但当前仓库真正内置模板与配置器支持的平台是：

- Codex
- Claude Code
- Cursor

对应模板位于 `src/reins/platform/templates/`，并在 `reins init` 时应用。

## 可选 HTTP API

如果你需要更底层的集成方式，Reins 也提供了一个 `aiohttp` 服务器：

```bash
python -m reins.api.server --port 8000 --state-dir .reins_state
```

核心路由包括：

- `POST /runs`
- `GET /runs/{id}`
- `GET /runs/{id}/timeline`
- `POST /runs/{id}/commands`
- `POST /runs/{id}/approve`
- `POST /runs/{id}/reject`
- `POST /runs/{id}/abort`
- `POST /runs/{id}/resume`

当你希望直接驱动底层 run / orchestrator 流程，而不是走 CLI 时，这个 API 会更合适。

## 仓库内文档

想继续深入，可以从这些文档开始：

- `docs/cli-reference.md`
- `docs/spec-schema.md`
- `docs/PARALLEL-EXECUTION-STRATEGY.md`
- `docs/ROADMAP-DETAILED.md`

## 在 Reins 上开发

标准检查命令：

```bash
ruff check src tests
mypy src
pytest
```

如果你只是想快速确认 CLI 面没有跑偏，可以执行：

```bash
PYTHONPATH=src python -m reins.cli.main --help
PYTHONPATH=src python -m reins.cli.main pipeline list
```

## 源码结构

当前源码大致可以按下面理解：

- `src/reins/cli/`：面向用户的 CLI 入口与命令组
- `src/reins/platform/`：平台检测、模板与配置器
- `src/reins/task/`：任务元数据、投影与 JSONL 上下文存储
- `src/reins/context/`：spec 解析与上下文编译
- `src/reins/workspace/`：开发者 workspace 状态、统计与报表
- `src/reins/isolation/`：受跟踪 git worktree 管理
- `src/reins/orchestration/`：pipeline 执行与 stage 协调
- `src/reins/kernel/`、`src/reins/policy/`、`src/reins/execution/`：更底层的事件、策略与执行原语
- `src/reins/api/`：可选 HTTP API

## 贡献说明

在修改项目时，建议遵循下面的约定：

1. 代码和测试一起更新。
2. 运行 lint、类型检查和相关测试。
3. 保证命令示例始终和 `reins --help` 对齐。
4. 优先记录当前 CLI 和仓库工件的真实行为，而不是写偏架构愿景式描述。
