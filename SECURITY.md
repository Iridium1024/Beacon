# 安全策略

[简体中文](#安全策略) | [English](#security-policy)

## 受支持版本

Beacon 当前是 Alpha 阶段的本地工具。安全修复将应用于默认分支的最新提交；
更早的提交和未公开的本地构建不作为受支持的独立发布线。

## 私密报告安全问题

请通过 GitHub 仓库 Security 页面中的
[Report a vulnerability](https://github.com/Iridium1024/Beacon/security/advisories/new)
私密报告安全问题。不要在公开 Issue 中提交凭据、令牌、Cookie、完整对话、
服务商会话注册表、SQLite 数据库、本地配置、唤醒票据或日志。除非这些信息
对复现问题确有必要，并且维护者已通过私密渠道明确提出要求，否则请移除
账号标识、会话标识、本地路径和私有模型内容。

维护者会在精力允许时查看报告。Beacon 不承诺固定的确认回复或修复时限；
已经确认的问题将根据影响程度和维护者当时可投入的精力安排优先级。

## 安全边界

- Gateway 只适用于可信任的本机环境，并拒绝 LAN 或公网监听地址。仅限
  localhost 的传输方式不等同于多用户身份认证。
- 会话发现默认只读取元数据。读取受限消息片段或更完整历史必须显式启用。
- Beacon 不会绕过服务商登录、服务商权限、交互式确认或操作系统沙箱。
- 服务商凭据只会从明确指定的环境变量读取，Beacon 不保存凭据值。
- 共享服务商会话注册表是本地 JSON 文件，不保证多进程锁定；并发写入需要
  操作者自行控制。
- 不要将 Gateway 暴露至 LAN、公网接口、反向代理或共享多用户主机；这些
  部署方式不受支持。

Beacon 不是生产级多用户服务，也不是远程 Agent 托管平台。

---

# Security Policy

## Supported Versions

Beacon is currently an alpha-quality local tool. Security fixes are applied to
the latest commit on the default branch; older commits and unpublished local
builds are not supported release lines.

## Reporting A Vulnerability

Report security vulnerabilities privately using
[Report a vulnerability](https://github.com/Iridium1024/Beacon/security/advisories/new)
on the repository's Security page. Do not open a public issue containing
credentials, tokens, cookies, complete transcripts, provider registries,
SQLite databases, local profiles, wake tickets, or logs. Remove account
identifiers, session identifiers, local paths, and private model content from
any reproduction unless they are essential and explicitly requested through
the private channel.

Reports are reviewed as availability permits. Beacon does not promise a fixed
acknowledgement or remediation timeline. Confirmed issues will be prioritized
according to their impact and the maintainers' available capacity.

## Security Boundaries

- Gateway is intended only for a trusted local machine and rejects LAN/public
  bind addresses. Localhost-only transport is not multi-user authentication.
- Session discovery is metadata-only by default. Reading bounded message
  snippets or full history requires explicit opt-in.
- Beacon does not bypass provider login, provider permissions, interactive
  approvals, or operating-system sandbox controls.
- Provider credentials are read from explicitly named environment variables;
  Beacon does not persist credential values.
- The shared provider-session registry is a local JSON file without a
  multi-process locking guarantee. Concurrent writers require operator control.
- Do not expose Gateway to a LAN, public interface, reverse proxy, or shared
  multi-user host. Those deployment modes are unsupported.

Beacon is not a production multi-user service or a remote agent hosting
platform.
