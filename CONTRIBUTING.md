# 参与 Beacon

[简体中文](#参与-beacon) | [English](#contributing-to-beacon)

Beacon 当前支持 Python 3.11 及以上版本和 Node.js 22 及以上版本。CI 会在
Windows 与 Ubuntu 上测试 Python，并在受支持的 Node.js 版本上测试 Gateway。

## 环境准备

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip build
.\.venv\Scripts\python.exe -m pip install -e .\python-core
npm.cmd --prefix gateway ci
~~~

Linux 或 macOS 请使用 <code>python3.11</code>、
<code>./.venv/bin/python</code> 和 <code>npm</code>。

## 验证

~~~powershell
py -3.11 -m unittest discover -s python-core\tests
npm.cmd --prefix gateway run check
npm.cmd --prefix gateway test
py -3.11 scripts\check_versions.py
py -3.11 scripts\release_check.py --strict
~~~

正式发布前，应在干净检出的仓库中运行
<code>scripts/release_check.py --strict</code>。

## 改动边界

- 修改 CLI、JSON schema、持久化格式或 Gateway 路由时，请说明兼容性影响，
  并尽可能保持稳定的错误和状态语义。
- 服务商激活测试必须保持本地化和确定性，不得调用真实的 Claude、Codex、
  Hermes 或其它模型服务商账号。
- 不得提交运行配置、服务商注册表、SQLite 文件、日志、服务商输出、唤醒
  票据、<code>.env</code> 文件、凭据或真实对话。
- 测试和文档应使用中性的示例路径以及明确为虚构内容的标识符。
- 不得在无关改动中扩大 Gateway 的网络暴露范围或增加凭据持久化。

## 贡献条款

Beacon 采用 [Apache License 2.0](LICENSE)。当你有意向 Beacon 提交贡献时，
即表示你同意该贡献按 Apache License 2.0 授权，并确认自己有权提交相关
内容。Beacon 不要求贡献者转让版权。

---

# Contributing To Beacon

Beacon currently targets Python 3.11 or newer and Node.js 22 or newer. CI tests
Python on Windows and Ubuntu and tests Gateway on supported Node releases.

## Setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip build
.\.venv\Scripts\python.exe -m pip install -e .\python-core
npm.cmd --prefix gateway ci
```

On Linux or macOS, use `python3.11`, `./.venv/bin/python`, and `npm`.

## Verification

```powershell
py -3.11 -m unittest discover -s python-core\tests
npm.cmd --prefix gateway run check
npm.cmd --prefix gateway test
py -3.11 scripts\check_versions.py
py -3.11 scripts\release_check.py --strict
```

Before a real release, run `scripts/release_check.py --strict` from a clean
checkout.

## Change Boundaries

- Describe compatibility effects for CLI, JSON schema, persistence, or Gateway
  route changes. Preserve stable error and status semantics where possible.
- Keep provider activation tests local and deterministic. Tests must not call
  real Claude, Codex, Hermes, or model-provider accounts.
- Never commit runtime profiles, provider registries, SQLite files, logs,
  provider output, wake tickets, `.env` files, credentials, or real
  transcripts.
- Use neutral fixture paths and clearly fake identifiers in tests and docs.
- Do not broaden Gateway beyond localhost or add credential persistence as an
  incidental change.

## Contribution Terms

Beacon is licensed under the [Apache License 2.0](LICENSE). By intentionally
submitting a contribution for inclusion in Beacon, you agree that the
contribution is licensed under the Apache License 2.0 and represent that you
have the right to submit it. No copyright assignment is required.
