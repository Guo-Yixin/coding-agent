# Issue Writer Examples

## OpenSandbox 部署问题

标题：`[Infra][Sandbox] classify image-pull failures before sandbox creation`

```markdown
## Problem / Context

OpenSandbox `/health` 返回 200，但创建 sandbox 时可能因镜像仓库 DNS、镜像不存在或 Docker 拉取超时失败。当前调用方只能看到长异常堆栈，无法快速区分 API 可达性和镜像准备问题。

## Observed Behavior

- Health check succeeds.
- Sandbox creation fails with image-pull or request-timeout errors.
- The failure is not represented as a stable, user-actionable error category.

## Expected Behavior

创建前能够区分 server health、image availability、DNS/pull timeout，并返回不包含凭据的修复建议。

## Proposed Scope

- 增加 image preflight 和错误分类。
- 在 Eval 启动前阻止无效镜像配置。
- 保留原始 request id，但脱敏 endpoint 和认证信息。

## Non-goals

- 不自动修改 node2 Docker 或 DNS 配置。
- 不在 Issue 中上传 `.env` 或完整私有日志。

## Acceptance Criteria

- [ ] health 成功但 image 不可用时返回明确分类。
- [ ] image 可用时可完成 create → execute → destroy。
- [ ] 有 fake、integration 和 failure-path 测试。
```

## 检索回归问题

标题：`[Bug][Retrieval] preserve grep fallback when CodeGraph returns invalid JSON`

验收重点：CodeGraph 超时/返回非法 JSON 时仍返回 grep 命中；trace 记录 fallback reason；gold file hit@k 不下降。

## PostgreSQL 运维问题

标题：`[Chore][PostgreSQL] add documented stale-run recovery procedure`

验收重点：提供恢复命令、幂等行为、审计事件和 integration test；明确不会触碰旧的 `langgraph_db`。
