<!-- beacon-version: 0.1.1 -->
# Beacon

**简体中文** | [English](README.en.md)

Beacon 是一个面向 CLI 型 AI Agent 的本地优先协作层。它不绑定具体模型或
服务商，而是为彼此独立运行的 Agent 提供一套明确、可追踪的协作界面，用于
完成工作空间接入、请求投递、状态追踪和受限的服务商会话激活。Beacon 不会
假定不同 Agent 的私有会话天然共享，也不会把各自的完整对话历史拼接成一份
不可控的公共记忆。

Python CLI 是 Beacon 当前的主要操作入口。范围更窄的 TypeScript Gateway
坚持本机优先原则，只开放部分工作空间、上下文、Agent、对话、调用、连接和
绑定接口。本次 DSH 源码增量不包含 Desktop、浏览器 UI 或未完成的 P3-B 资产。

需要接入 Beacon 的外部 Agent 应先阅读 [BEACON.md](BEACON.md)。本文面向
项目使用者和开发者，用于说明整体能力与模块边界，并不是最短操作手册。

Beacon 当前源码版本为 <code>0.1.1</code>；当前最新公开 Git tag/release 仍为
<code>v0.1.0</code>。<code>0.1.1</code> 尚未在本工作区发布。内部开发阶段和
自动化步骤编号不作为公开语义化版本。

待审阅的 DSH 第四端内容按源码增量准备，而不是独立安装包。下载或解压源码后
仍须安装运行时及依赖；所需 CLI、可选 Gateway、DSH carrier、路径与认证边界见
[源码安装与可选运行时说明](docs/release/source-installation.md)，发布说明草稿见
[DSH 源码增量草稿](docs/release/dsh-source-increment-draft.md)。真实认证和模型
通信尚未验证。

> 开发说明：Beacon 起源于以 vibe coding 为主的探索式开发，部分结构或实现
> 仍可能存在值得重新审视的地方。当前版本已经过自动化校验和多服务商实机
> 冒烟测试，但仍属于 Alpha 阶段。欢迎通过 Issue、设计建议或 Pull Request
> 指出问题并参与改进。

## Beacon 适合做什么

- 让彼此独立运行的 Codex、Claude、Hermes 和 Beacon 管理的 DeepSeek Harness
  会话在同一本地项目中，通过
  明确的请求和可观察状态开展协作。
- 复用已经登记的服务商会话，并分别管理其工作空间成员关系与端点身份，而
  不把服务商登录等同于 Beacon 身份。
- 在本地协作停滞时，查询接入、投递、守护进程、租约、激活和消息交换状态。
- 当前以 CLI 作为可靠的主要入口，并通过可选 Gateway 暴露部分本地接口。

Beacon 不是远程 Agent 托管平台、服务商账号连接器，也不是面向生产环境的
多用户聊天服务。

## 快速开始

Beacon 支持 Python 3.11 及以上版本。推荐使用独立虚拟环境进行可编辑安装；
安装过程会一并安装 PyYAML，并创建 <code>beacon</code> 命令，无需预装额外
Python 依赖或手动配置 <code>PYTHONPATH</code>。

Windows PowerShell：

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\python-core
.\.venv\Scripts\beacon.exe --help
~~~

Linux/macOS：

~~~bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e ./python-core
./.venv/bin/beacon --help
~~~

激活虚拟环境后即可直接使用 <code>beacon</code>。Beacon 是项目和 CLI 的
公开名称；内部 <code>agent_os</code> 模块、<code>agent-os-core</code>
Python 包名和 <code>@agent-os/gateway</code> 包名暂时保留，以维持兼容性。

在仓库根目录运行本地冒烟测试：

~~~powershell
beacon --database runtime\state\local-platform.sqlite3 --workspace-root workspace\sandboxes\local-platform --plugins-directory plugins smoke
~~~

<code>python -m agent_os.local_runtime</code> 仍是完全兼容的源码/模块入口。
只有在无法进行可编辑安装时，才需要通过
<code>PYTHONPATH=python-core\src</code> 使用该入口。

<code>smoke</code> 命令只会输出 JSON。默认情况下，它不会启动守护进程、
开放公网端口、连接真实模型服务商、创建凭据或启动图形界面。

## 发布准备

版本变化见 [CHANGELOG.md](CHANGELOG.md)，安全报告方式见
[SECURITY.md](SECURITY.md)，参与方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，
发布门槛见 [docs/release/README.md](docs/release/README.md)。项目采用
Apache-2.0 许可证。公开发布前必须通过：

~~~powershell
py -3.11 scripts\release_check.py --strict
~~~

该命令会检查根许可证、私密安全联系方式、版本一致性、仓库卫生和发布文档。
本次 DSH 源码增量的可审阅说明见
[docs/release/dsh-source-increment-draft.md](docs/release/dsh-source-increment-draft.md)。

## 当前能力概览

| 能力范围 | Python CLI | Gateway HTTP |
| --- | --- | --- |
| 工作空间和配置初始化 | 完整的本地配置与工作空间流程 | 创建、列出、打开和归档工作空间；不提供配置初始化路由 |
| Agent 接入和端点 | 幂等服务商接入、句柄、别名和清单 | 仅创建、列出 Agent；不提供端点接入路由 |
| 请求和投递 | 请求板、排队/单次投递、守护进程与租约恢复 | 尚未开放 |
| 服务商会话 | 元数据发现、登记、可复用配置的加入/退出 | 尚未开放 |
| 状态查询 | 接入、端点、投递、交换、激活和守护进程状态；Codex 支持自有运行时快照与可选 app-server 单点读取 | 仅部分工作空间和运行权限记录 |
| 服务商激活 | 受限激活已登记的 Claude、Codex、Hermes 会话；另提供可选的 DeepSeek Harness 精确既有 session 接入、新建和跨 runtime 恢复。Claude 支持默认 CLI 与可选 Agent SDK，Codex 支持默认 CLI、经 0.149 schema 验证且恢复权限不扩张的可选稳定 stdio app-server 及显式 active-turn 补充，Hermes 支持默认 CLI 与精确版本门控的可选 stdio TUI Gateway | 尚未开放 |
| 上下文和对话 | 完整本地 CLI 操作 | 通过可选 Python bridge 开放部分 <code>/api/v1</code> 路由 |
| 调用和记录 | 本地调用、时间线和记录查询 | 部分调用、文件记录和时间线路由 |
| 尚未实现 | 正式发布 Desktop、Desktop 写控制、Hermes WebSocket/ACP/HTTP 或常驻运行时、持久 Claude SDK 运行时、DSH cancel/supplement/并发/自动发现/外部存活 Web/TUI 接管、远程凭据、公网/LAN 暴露 | 完整 CLI 对等能力、远程或多用户服务 |

## 首次使用流程

1. 阅读 [BEACON.md](BEACON.md)。
2. 常规 Agent 协作继续阅读
   [docs/agent/agent_entry.md](docs/agent/agent_entry.md)。
3. 使用 <code>agent-workspace-init</code> 初始化项目。Beacon 写入本地
   <code>.beacon/workspace.json</code>，之后会从当前目录向上解析最近项目作用域，
   不扫描本机数据库猜测工作空间。
4. 使用 <code>agent-join --agent &lt;可见ID&gt; --provider ... --session ...</code>
   一次性登记 Agent、精确原生会话和同名投递端点。
   DeepSeek Harness 同样接受精确 <code>--session</code>，从配置的官方持久化
   root 恢复；仅在确实需要新会话时使用 <code>--new-session</code>。
5. 投递前使用 <code>agent-onboarding-status</code> 检查接入状态。
6. 使用可见 Agent ID 完成定向投递；目标可按需用 <code>agent-reply</code>
   回复。<code>--profile</code> 仍可用于项目目录外的显式调用。

显式提供的原生会话 ID 会走精确查找，不受“最近会话”展示数量限制。同一工作空间
内，一个活跃原生会话不会被普通 <code>agent-join</code> 静默登记给两个可见 Agent；
工作空间无效时也会在读取服务商会话目录前直接失败。

旧工作空间若没有项目 marker，不要直接执行普通初始化以免创建并行空数据库；应向
<code>agent-workspace-init</code> 显式提供
<code>--existing-database</code>（必要时同时提供旧 workspace root 与 plugins
目录）。Beacon 会先按 ID 验证旧库，再写入当前 marker/profile，不扫描、复制或改写旧库。

队列查询保留 append-only 原始状态用于审计，但当关联请求已在 Provider 投递前回复、
关闭或终止时，对外有效状态为 <code>terminal_unprocessed</code>，worker 不会再次拾取。

`agent-dispatch-send` 是公开的 `send` 操作，未指定投递模式时默认执行一次
有界 inline 投递（`--wait once` 与内部 `worker_execute` 只是兼容写法），适合
确认和简短问答。目标繁忙时会把选择权返回调用方，
不会自动排队、重试或转为 steer。复杂信息建议先写入项目文件，再发送摘要和
引用；长时间任务只有在已确认 worker/daemon/supervisor 可消费时才显式使用
`--queued`。`localRuntime.dispatchControl` 可配置默认模式和即时繁忙策略。
投递不强制回复，服务商执行完成也不等于已经回复。

涉及服务商专用预检或已登记会话激活时，应从
[docs/providers/provider_guides.md](docs/providers/provider_guides.md)
开始阅读。
[服务商程序化接口状态](docs/providers/provider_programmatic_interfaces.md)
另行区分官方已经提供的接口与 Beacon 实际实现的后端；上游存在接口不代表该
后端已经可选。

Claude 控制配置位于 <code>localRuntime.claudeControl</code>。默认和回滚
后端仍为 <code>cli</code>；<code>agent_sdk</code> 需要显式选择并安装
<code>python-core[claude-agent-sdk]</code> 可选依赖。CLI 为兼容保留默认最终
输出写回，Agent SDK 默认 <code>explicit_only</code>。缺包或版本不兼容会在
ticket 投递前失败且不会静默回退。该 SDK 后端每次激活只拥有一个短生命周期
client；最新实现尚未完成带认证真实会话的实机 smoke。

Codex 控制配置统一位于 <code>localRuntime.codexControl</code>。默认仍为
<code>exec_resume</code> 激活、Beacon 快照状态、显式
<code>turn_steer</code> 补充能力和 <code>explicit_only</code> 回复写回；Codex
专用繁忙配置保持兼容。只有显式选择 <code>provider_final_capture</code> 时，
Codex 最终输出才会自动写成 Beacon 回复。使用
<code>codex-session-status</code> 查询指定登记会话；只有调用方明确判断补充
信息属于当前 active turn 时，才使用 <code>codex-session-supplement</code>。
该命令不会新建 turn，只有持有同一 app-server stdio 连接的 Beacon 运行器
可以实际投递。完整配置、状态、幂等与歧义处理见
[Codex 激活说明](docs/providers/codex_registered_session_activation.md)。
默认 <code>explicit_only</code> 激活消息会直接告诉接收方如何使用
<code>agent-reply</code>，不会再错误声称最终回答会被自动捕获。登入时发现的
<code>CODEX_HOME</code> 会继续用于状态查询和两种 Codex 激活后端。当前实现已
通过 Codex CLI 0.149.0 正式非实验 schema 与伪传输兼容测试；app-server 会在
<code>turn/start</code> 前验证恢复后的 cwd、sandbox、审批策略和可写根目录没有
扩张。该 0.149 路径尚未完成带认证真实会话的实机 smoke。

Beacon 对外区分 `send`、`queue`、`supplement`、`status`，内部当前只实现
`inline`、`queue`、`dry_run`；`async_submit` 仅为后续保留。服务商后端通过
统一契约选择并报告 requested/effective backend，不进行静默回退。当前 Codex
app-server 是每次操作独立启动和关闭的短生命周期 stdio 后端，不是常驻的
多 thread 管理器。详见
[投递与服务商后端契约](docs/agent/provider_backend_contract.md)。

Hermes 默认继续使用 `hermes_cli`。只有显式选择
`--hermes-activation-backend tui_gateway` 才会启动一次操作自有的
`python -u -m tui_gateway.entry` stdio 子进程；当前仅接受经过审计的
`hermes-agent==0.19.0`，不兼容时会在提交提示词前失败且不会静默回退。
持久 session id 与 gateway 返回的运行时 session id 是两个不同身份域，后者
不会写回登记句柄。Gateway 默认 `explicit_only`，且当前尚未进行已认证的真实
Hermes 会话 smoke。详见
[Hermes 激活说明](docs/providers/hermes_registered_session_activation.md)。

DeepSeek Harness 是独立的第四个 Agent 平台，不是 <code>deepseek</code> 模型
preset。它仅提供显式可选的 <code>deepseek_harness_sdk_stdio</code> managed
runtime：它可精确恢复官方 JSONL 持久化中的既有 session，也可新建 session；
独立 CLI/worker 通过带身份认证的本机 IPC 复用同一 generation。正常 stop 后，
显式 resume 保持原生 session、Agent 和 alias，同时创建新 handle/runtime/
generation；recreate 仍表示新原生会话。Windows 使用项目内锁定到
<code>0.1.1-rc.2</code> 的 Node 22.19+ 路线；不会全局安装或接管外部仍存活的
DSH Web/TUI 进程。当前已有 fake 跨进程回归及官方 runtime/持久化配合本地假模型
的离线历史恢复测试，但尚未运行认证真实模型 smoke。详见
[DeepSeek Harness managed runtime](docs/providers/deepseek_harness_managed_runtime.md)。

## Gateway

Gateway 是可选组件，并不完整映射 Python CLI。当前未开放
<code>agent-dispatch</code>、端点接入、已登记会话激活以及完整的交换请求/
状态接口。

在 <code>gateway</code> 目录安装依赖并执行检查：

~~~powershell
Set-Location gateway
npm.cmd ci
npm.cmd run check
npm.cmd run test:platform-route
npm.cmd run test:platform-bridge
~~~

Linux/macOS 使用 <code>npm</code> 代替 <code>npm.cmd</code>。已有锁文件时
默认使用 <code>npm ci</code>；只有在有意修改依赖或
<code>package-lock.json</code> 时才使用 <code>npm install</code>。

通过 Python bridge 启动 Gateway：

~~~powershell
$env:LOCAL_PLATFORM_BRIDGE_MODE='python_cli'
$env:LOCAL_PLATFORM_PYTHON_CORE_CWD='../python-core'
$env:LOCAL_PLATFORM_PYTHONPATH='src'
$env:LOCAL_PLATFORM_DATABASE='../runtime/state/local-platform.sqlite3'
$env:LOCAL_PLATFORM_WORKSPACE_ROOT='../workspace/sandboxes/local-platform'
$env:LOCAL_PLATFORM_PLUGINS_DIRECTORY='../plugins'
npm run build
npm start
~~~

Gateway 默认使用 <code>contract_only</code> 模式。

Gateway 会依次尝试 <code>LOCAL_PLATFORM_PYTHON_COMMAND</code>、当前
<code>VIRTUAL_ENV</code>、Windows 上的 <code>py -3.11</code>，以及
Linux/macOS 上的 <code>python3.11</code> 或 <code>python3</code>。启动
bridge 前会拒绝低于 Python 3.11 的解释器。只有默认候选均不适用时，才需要
显式指定 Python 命令。

## 仓库结构

~~~text
.
|-- AGENTS.md
|-- BEACON.md
|-- LICENSE
|-- NOTICE
|-- README.md
|-- README.en.md
|-- config/
|-- contracts/
|-- docs/
|   |-- agent/
|   |-- gateway/
|   |-- providers/
|   \-- runtime/
|-- gateway/
|-- python-core/
|   |-- src/
|   \-- tests/       # 规范 Python 回归测试集
|-- runtime/      # 默认忽略的本地运行状态
|-- workspace/    # 默认忽略的本地工作空间状态
\-- plugins/      # 默认忽略的插件和运行状态
~~~

## 本地状态与发布边界

运行数据库、本地配置、服务商会话注册表、唤醒票据、守护进程日志、服务商
输出、插件状态和冒烟测试产物都属于本机状态。发布仓库默认忽略这些内容，
不应将其提交到 Git。

私有开发工作区可以在 Beacon 发布目录之外保存迁移记录、开发过程记录和真实
冒烟测试历史。这些内部材料不属于外部 Agent 的常规接入文档。

## 后续计划

Beacon 计划按以下顺序继续演进：

1. 完善本地身份、工作空间成员关系和连接状态的持久化、恢复与诊断。
2. 稳定控制接口，明确区分已登记身份、工作空间成员关系和实时连接状态。
3. 为支持 MCP 的桌面客户端提供兼容接口。
4. 建立桌面管理中心，统一管理已登记会话、工作空间、成员关系和实时连接。
5. 提供受控的多 Agent 房间，将选定的已登记 Agent 加入同一协作会话。
6. 建立工作空间范围内的共享上下文，并加入明确的权限、来源、容量限制和
   循环防护。
7. 完善安装、升级、数据迁移和桌面端生命周期管理。

以上顺序不代表固定发布日期，后续可能根据实现验证和社区反馈进行调整。

## 许可证

Beacon 采用 [Apache License 2.0](LICENSE)。Copyright 2026 Beacon
contributors。
