# GitHub Token 与 Provider 接入说明

本文记录将 CODING 项目发布到 GitHub，以及未来接入 GitHub 仓库能力时的认证边界。

## 1. 创建 GitHub Personal Access Token

创建入口：

[GitHub Fine-grained Personal Access Token](https://github.com/settings/personal-access-tokens/new)

推荐配置：

- Resource owner：选择 GitHub 账号 `Guo-Yixin`；
- Repository access：选择 `Only select repositories`；
- 只选择目标仓库 `coding-agent`；
- `Contents`：`Read and write`；
- `Metadata`：`Read-only`；
- 根据实际需要设置过期时间，建议使用 30 或 90 天。

Fine-grained Token 应遵循最小权限原则。Token 只在创建时完整显示一次，不得提交到 Git、README、`.env.example` 或聊天记录中。

官方文档：[Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)

## 2. 将本地项目推送到 GitHub

当前项目远程仓库地址：

```text
https://github.com/Guo-Yixin/coding-agent.git
```

在项目根目录执行：

```powershell
git remote add origin https://github.com/Guo-Yixin/coding-agent.git
git push -u origin main
```

如果 HTTPS 推送时要求输入凭据：

```text
Username: Guo-Yixin
Password: 粘贴 GitHub Personal Access Token
```

Password 位置填写 Token，不要填写 GitHub 登录密码。不要把 Token 写入远程 URL，例如不要使用：

```text
https://TOKEN@github.com/Guo-Yixin/coding-agent.git
```

## 3. 当前 CODING 的 Provider 边界

当前版本的仓库能力仍然是 Gitee provider：

- 读取 `GITEE_TOKEN`；
- 解析 `gitee.com` 仓库地址；
- 使用 Gitee API 读取 Pull Request、文件和评论；
- 使用 Gitee 分支、提交、推送和 Pull Request 流程。

因此，仅配置 GitHub PAT 不会自动让 CODING 支持 GitHub 仓库。GitHub PAT 当前可以用于本地 Git HTTPS 认证和首次 push，但不能直接作为 CODING 的 GitHub provider 配置使用。

## 4. 未来接入 GitHub provider 的建议

建议与 Gitee Token 分开配置：

```text
GITEE_TOKEN=本地 Gitee Token
GITHUB_TOKEN=本地 GitHub Token
```

后续需要新增：

1. GitHub 仓库 URL 解析与校验；
2. GitHub clone、pull、push 认证；
3. GitHub Branch API；
4. GitHub Pull Request 创建、读取和评论 API；
5. 前端仓库平台选择；
6. GitHub provider 的权限控制、错误处理和验证脚本。

不要用同一个 Token 同时代替 Gitee 和 GitHub Token，也不要在日志、任务消息、异常文本或提交记录中输出 Token。

相关官方文档：[About remote repositories](https://docs.github.com/en/get-started/git-basics/about-remote-repositories)
