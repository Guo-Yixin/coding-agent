# Gitee Reviewer 相关 API 资料

> 本文档整理自 Gitee 官方 Open API 文档，用于后续开发 Gitee Code Reviewer 子 Agent 时查阅。
>
> 资料来源：
>
> - Gitee API 文档页面：https://gitee.com/api/v5/swagger
> - Gitee API JSON 文档：https://gitee.com/api/v5/doc_json
>
> 文档版本：
>
> - `Gitee Open API`
> - `version`: `5.4.92`
> - `swagger`: `2.0`
> - `host`: `gitee.com`
> - `basePath`: `/api`
> - `schemes`: `https`, `http`

## 1. Pull Request 详情

### 1.1 获取单个 Pull Request

| 项目 | 内容 |
|---|---|
| Method | `GET` |
| Path | `/v5/repos/{owner}/{repo}/pulls/{number}` |
| Tags | `Pull Requests` |
| operationId | `getV5ReposOwnerRepoPullsNumber` |
| Summary | 获取单个 Pull Request |
| Description | 获取单个 Pull Request |
| Response `200` | `#/definitions/PullRequest` |

### 1.2 路径参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `owner` | `path` | `string` | 是 | 仓库所属空间地址（企业、组织或个人的地址 path） |
| `repo` | `path` | `string` | 是 | 仓库路径 path |
| `number` | `path` | `integer` / `int32` | 是 | 第几个 PR，即本仓库 PR 的序数 |

### 1.3 `PullRequest` 中和 Review 相关的字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `number` | `integer` / `int32` | PR 编号 |
| `html_url` | `string` | PR 页面地址 |
| `diff_url` | `string` | PR diff 地址 |
| `patch_url` | `string` | PR patch 地址 |
| `comments_url` | `string` | PR 评论地址 |
| `review_comments_url` | `string` | PR review comments 地址 |
| `review_comment_url` | `string` | 单条 PR review comment 地址模板 |
| `commits_url` | `string` | PR commits 地址 |
| `base` | `string` | PR base 信息 |
| `head` | `string` | PR head 信息 |

## 2. Pull Request 变更文件

### 2.1 获取 Pull Request 变更文件列表

| 项目 | 内容 |
|---|---|
| Method | `GET` |
| Path | `/v5/repos/{owner}/{repo}/pulls/{number}/files` |
| Tags | `Pull Requests` |
| operationId | `getV5ReposOwnerRepoPullsNumberFiles` |
| Summary | Pull Request Commit 文件列表，最多显示 300 条 diff |
| Description | Pull Request Commit 文件列表，最多显示 300 条 diff |
| Response `200` | `array` of `#/definitions/PullRequestFiles` |

### 2.2 路径参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `owner` | `path` | `string` | 是 | 仓库所属空间地址（企业、组织或个人的地址 path） |
| `repo` | `path` | `string` | 是 | 仓库路径 path |
| `number` | `path` | `integer` / `int32` | 是 | 第几个 PR，即本仓库 PR 的序数 |

### 2.3 `PullRequestFiles` 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `sha` | `string` | 文件对应 SHA |
| `filename` | `string` | 文件名 |
| `status` | `string` | 文件状态 |
| `additions` | `string` | 新增行数 |
| `deletions` | `string` | 删除行数 |
| `blob_url` | `string` | blob 页面地址 |
| `raw_url` | `string` | raw 文件地址 |
| `patch` | `string` | 文件 patch 内容 |

## 3. Pull Request 评论列表与提交评论

### 3.1 获取某个 Pull Request 的所有评论

| 项目 | 内容 |
|---|---|
| Method | `GET` |
| Path | `/v5/repos/{owner}/{repo}/pulls/{number}/comments` |
| Tags | `Pull Requests` |
| operationId | `getV5ReposOwnerRepoPullsNumberComments` |
| Summary | 获取某个 Pull Request 的所有评论 |
| Description | 获取某个 Pull Request 的所有评论 |
| Response `200` | `array` of `#/definitions/PullRequestComments` |

### 3.2 获取评论列表的参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 可选值 | 说明 |
|---|---|---|---|---|---|---|
| `owner` | `path` | `string` | 是 |  |  | 仓库所属空间地址（企业、组织或个人的地址 path） |
| `repo` | `path` | `string` | 是 |  |  | 仓库路径 path |
| `number` | `path` | `integer` / `int32` | 是 |  |  | 第几个 PR，即本仓库 PR 的序数 |
| `page` | `query` | `integer` / `int32` | 否 | `1` |  | 当前页码 |
| `per_page` | `query` | `integer` / `int32` | 否 | `20` | 最小 `1`，最大 `100` | 每页数量，最大为 100 |
| `direction` | `query` | `string` | 否 |  | `asc`, `desc` | 可选，升序或降序 |
| `comment_type` | `query` | `string` | 否 |  | `diff_comment`, `pr_comment` | 可选，筛选评论类型：代码评论或 PR 普通评论 |

### 3.3 提交 Pull Request 评论

| 项目 | 内容 |
|---|---|
| Method | `POST` |
| Path | `/v5/repos/{owner}/{repo}/pulls/{number}/comments` |
| Tags | `Pull Requests` |
| operationId | `postV5ReposOwnerRepoPullsNumberComments` |
| Summary | 提交 Pull Request 评论 |
| Description | 提交 Pull Request 评论 |
| Consumes | `application/json` |
| Produces | `application/json` |
| Response `201` | `#/definitions/PullRequestComments` |

### 3.4 提交评论的参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `owner` | `path` | `string` | 是 | 仓库所属空间地址（企业、组织或个人的地址 path） |
| `repo` | `path` | `string` | 是 | 仓库路径 path |
| `number` | `path` | `integer` / `int32` | 是 | 第几个 PR，即本仓库 PR 的序数 |
| `body` | `formData` | `string` | 是 | 评论内容 |
| `commit_id` | `formData` | `string` | 否 | PR 代码评论的 commit id |
| `path` | `formData` | `string` | 否 | PR 代码评论的文件名 |
| `position` | `formData` | `integer` / `int32` | 否 | PR 代码评论在 diff 中的位置 |

## 4. 单条 Pull Request 评论

### 4.1 获取 Pull Request 的某条评论

| 项目 | 内容 |
|---|---|
| Method | `GET` |
| Path | `/v5/repos/{owner}/{repo}/pulls/comments/{id}` |
| Tags | `Pull Requests` |
| operationId | `getV5ReposOwnerRepoPullsCommentsId` |
| Summary | 获取 Pull Request 的某条评论 |
| Description | 获取 Pull Request 的某条评论 |
| Response `200` | `#/definitions/PullRequestComments` |

### 4.2 编辑评论

| 项目 | 内容 |
|---|---|
| Method | `PATCH` |
| Path | `/v5/repos/{owner}/{repo}/pulls/comments/{id}` |
| Tags | `Pull Requests` |
| operationId | `patchV5ReposOwnerRepoPullsCommentsId` |
| Summary | 编辑评论 |
| Description | 编辑评论 |
| Response `200` | `#/definitions/PullRequestComments` |

### 4.3 删除评论

| 项目 | 内容 |
|---|---|
| Method | `DELETE` |
| Path | `/v5/repos/{owner}/{repo}/pulls/comments/{id}` |
| Tags | `Pull Requests` |
| operationId | `deleteV5ReposOwnerRepoPullsCommentsId` |
| Summary | 删除评论 |
| Description | 删除评论 |
| Response `204` | 删除评论 |

### 4.4 单条评论接口参数

| 参数 | 位置 | 类型 | 必填 | 适用方法 | 说明 |
|---|---|---|---|---|---|
| `owner` | `path` | `string` | 是 | `GET`, `PATCH`, `DELETE` | 仓库所属空间地址（企业、组织或个人的地址 path） |
| `repo` | `path` | `string` | 是 | `GET`, `PATCH`, `DELETE` | 仓库路径 path |
| `id` | `path` | `integer` / `int32` | 是 | `GET`, `PATCH`, `DELETE` | 评论 ID |
| `body` | `formData` | `string` | 是 | `PATCH` | 评论内容 |

## 5. Pull Request 审查

### 5.1 通过 Pull Request 审查

| 项目 | 内容 |
|---|---|
| Method | `POST` |
| Path | `/v5/repos/{owner}/{repo}/pulls/{number}/review` |
| Tags | `Pull Requests` |
| operationId | `postV5ReposOwnerRepoPullsNumberReview` |
| Summary | 通过 Pull Request 审查 |
| Description | 通过 Pull Request 审查 |
| Consumes | `application/json` |
| Produces | `application/json` |
| Response `201` | 通过 Pull Request 审查 |

### 5.2 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `number` | `path` | `integer` / `int32` | 是 | 第几个 PR，即本仓库 PR 的序数 |
| `force` | `formData` | `boolean` | 否 | 是否强制审查通过，默认否，只对管理员有效 |
| `owner` | `path` | `integer` / `int32` | 是 | 官方 JSON 中该字段类型为 `integer` / `int32` |
| `repo` | `path` | `integer` / `int32` | 是 | 官方 JSON 中该字段类型为 `integer` / `int32` |

## 6. 仓库默认审查人员配置

### 6.1 修改仓库默认审查人员

| 项目 | 内容 |
|---|---|
| Method | `PUT` |
| Path | `/v5/repos/{owner}/{repo}/reviewer` |
| Tags | `Repositories` |
| operationId | `putV5ReposOwnerRepoReviewer` |
| Summary | 修改代码审查设置 |
| Description | 修改代码审查设置 |
| Consumes | `application/json` |
| Produces | `application/json` |
| Response `200` | `#/definitions/Project` |

### 6.2 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| `access_token` | `formData` | `string` | 否 | 用户授权码 |
| `owner` | `path` | `string` | 是 | 仓库所属空间地址（企业、组织或个人的地址 path） |
| `repo` | `path` | `string` | 是 | 仓库路径 path |
| `assignees` | `formData` | `string` | 是 | 审查人员 username，可设置多个，多个用户名用英文逗号分隔，例如 `username1,username2` |
| `testers` | `formData` | `string` | 是 | 测试人员 username，可设置多个，多个用户名用英文逗号分隔，例如 `username1,username2` |
| `assignees_number` | `formData` | `integer` / `int32` | 是 | 审查人员数量 |
| `testers_number` | `formData` | `integer` / `int32` | 是 | 测试人员数量 |

## 7. `PullRequestComments` 返回字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `url` | `string` | 评论 API 地址 |
| `id` | `integer` / `int32` | 评论 ID |
| `path` | `string` | 文件路径 |
| `position` | `string` | diff 位置 |
| `original_position` | `string` | 原始 diff 位置 |
| `new_line` | `string` | 新行号 |
| `commit_id` | `string` | commit id |
| `original_commit_id` | `string` | 原始 commit id |
| `user` | `#/definitions/UserBasic` | 评论用户 |
| `created_at` | `string` / `date-time` | 创建时间 |
| `updated_at` | `string` / `date-time` | 更新时间 |
| `body` | `string` | 评论正文 |
| `html_url` | `string` | 评论页面地址 |
| `pull_request_url` | `string` | Pull Request 地址 |
| `_links` | `string` | 链接信息 |
| `comment_type` | `string` | 评论类型 |
| `in_reply_to_id` | `integer` / `int32` | 回复的评论 ID |

## 8. 与 Pull Request 评论相关的 API 路径清单

| Path | Method | 用途 |
|---|---|---|
| `/v5/repos/{owner}/{repo}/pulls/{number}` | `GET` | 获取单个 Pull Request |
| `/v5/repos/{owner}/{repo}/pulls/{number}/files` | `GET` | 获取 Pull Request 变更文件列表 |
| `/v5/repos/{owner}/{repo}/pulls/{number}/comments` | `GET` | 获取 Pull Request 评论列表 |
| `/v5/repos/{owner}/{repo}/pulls/{number}/comments` | `POST` | 提交 Pull Request 评论 |
| `/v5/repos/{owner}/{repo}/pulls/comments/{id}` | `GET` | 获取单条 Pull Request 评论 |
| `/v5/repos/{owner}/{repo}/pulls/comments/{id}` | `PATCH` | 编辑单条 Pull Request 评论 |
| `/v5/repos/{owner}/{repo}/pulls/comments/{id}` | `DELETE` | 删除单条 Pull Request 评论 |
| `/v5/repos/{owner}/{repo}/pulls/{number}/review` | `POST` | 通过 Pull Request 审查 |
| `/v5/repos/{owner}/{repo}/reviewer` | `PUT` | 修改仓库默认审查人员设置 |
