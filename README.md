<!-- beacon-version: 0.1.0 -->
# Beacon

**简体中文** | [English](README.en.md)

Beacon 是一个面向 CLI 型 AI Agent 的本地优先协作层。它不绑定具体模型或
服务商，而是为彼此独立运行的 Agent 提供一套明确、可追踪的协作界面，用于
完成工作空间接入、请求投递、状态追踪和受限的服务商会话激活。Beacon 不会
假定不同 Agent 的私有会话天然共享，也不会把各自的完整对话历史拼接成一份
不可控的公共记忆。

Python CLI 是 Beacon 当前的主要操作入口。范围更窄的 TypeScript Gateway
坚持本机优先原则，只开放部分工作空间、上下文、Agent、对话、调用、连接和
绑定接口。

需要接入 Beacon 的外部 Agent 应先阅读 [BEACON.md](BEACON.md)。本文面向
项目使用者和开发者，用于说明整体能力与模块边界，并不是最短操作手册。

Beacon 的首个公开版本为 <code>0.1.0</code>，对应 Git tag
<code>v0.1.0</code>。内部开发阶段和自动化步骤编号不作为公开语义化版本。

> 开发说明：Beacon 起源于以 vibe coding 为主的探索式开发，部分结构或实现
> 仍可能存在值得重新审视的地方。当前版本已经过自动化校验和多服务商实机
> 冒烟测试，但仍属于 Alpha 阶段。欢迎通过 Issue、设计建议或 Pull Request
> 指出问题并参与改进。

## Beacon 适合做什么

- 让彼此独立运行的 Codex、Claude 和 Hermes 会话在同一本地项目中，通过
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
<code>v0.1.0</code> 的双语发布说明见
[docs/release/v0.1.0.md](docs/release/v0.1.0.md)。

## 当前能力概览

| 能力范围 | Python CLI | Gateway HTTP |
| --- | --- | --- |
| 工作空间和配置初始化 | 完整的本地配置与工作空间流程 | 创建、列出、打开和归档工作空间；不提供配置初始化路由 |
| Agent 接入和端点 | 幂等服务商接入、句柄、别名和清单 | 仅创建、列出 Agent；不提供端点接入路由 |
| 请求和投递 | 请求板、排队/单次投递、守护进程与租约恢复 | 尚未开放 |
| 服务商会话 | 元数据发现、登记、可复用配置的加入/退出 | 尚未开放 |
| 状态查询 | 接入、端点、投递、交换、激活和守护进程状态 | 仅部分工作空间和运行权限记录 |
| 服务商激活 | 受限激活已登记的 Claude、Codex、Hermes 会话 | 尚未开放 |
| 上下文和对话 | 完整本地 CLI 操作 | 通过可选 Python bridge 开放部分 <code>/api/v1</code> 路由 |
| 调用和记录 | 本地调用、时间线和记录查询 | 部分调用、文件记录和时间线路由 |
| 尚未实现 | UI、服务商自有实时连接器、远程凭据、公网/LAN 暴露 | 完整 CLI 对等能力、远程或多用户服务 |

## 首次使用流程

1. 阅读 [BEACON.md](BEACON.md)。
2. 常规 Agent 协作继续阅读
   [docs/agent/agent_entry.md](docs/agent/agent_entry.md)。
3. 初始化或接收一个本地运行配置。<code>--profile</code> 接收本地 JSON
   配置文件路径，而不是内联 JSON 字符串。
4. 常规工作空间内服务商接入优先使用
   <code>agent-provider-onboard</code>。
5. 投递前使用 <code>agent-onboarding-status</code> 检查接入状态。
6. 通过工作空间内的端点别名完成定向投递。

涉及服务商专用预检或已登记会话激活时，应从
[docs/providers/provider_guides.md](docs/providers/provider_guides.md)
开始阅读。

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
