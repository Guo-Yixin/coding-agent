from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from deepagents.backends.utils import create_file_data
from langgraph.store.base import BaseStore

from agent.tools.gitee_api import GiteeRepo

REPO_MEMORY_NAMESPACE_PREFIX: Final[tuple[str, str]] = ("coding", "repo-memory")


def repo_memory_virtual_path(owner: str, repo: str) -> str:
    """Agent 可见的记忆文件路径，按 owner/repo 命名，多仓库各自独立。"""
    return f"/memories/{owner}/{repo}.md"


def repo_memory_store_key(owner: str, repo: str) -> str:
    """LangGraph Store 中使用的内部 key。

    Agent 访问的是 `/memories/{owner}/{repo}.md`。但是当前 CompositeBackend
    会把 `/memories/` 路由前缀剥离后再交给 StoreBackend，所以 LangGraph Store
    里实际保存的 key 是 `/{owner}/{repo}.md`。
    """
    return f"/{owner}/{repo}.md"


def repo_project_dir(repo: GiteeRepo) -> str:
    """根据 Gitee 仓库信息生成固定的本地项目目录。

    本地部署版第一版本不再维护“仓库 URL -> 本地目录”的 SQLite 映射表。
    只要前端传入 Gitee 仓库地址，后端就可以从 URL 解析出 repo 名称，
    并稳定落到 `/projects/<repo>`。这样本地目录、命令目录和仓库记忆路径
    都由同一个 owner/repo 规则推导，避免多套映射关系互相覆盖。
    """

    return f"projects/{repo.repo}"


def build_repo_memory_namespace(owner: str, repo: str) -> tuple[str, ...]:
    """生成仓库级长期记忆的 StoreBackend namespace。

    每个 Gitee 仓库使用独立 namespace，不同仓库的记忆文件路径不同、
    namespace 也不同，双重隔离。
    """
    return (*REPO_MEMORY_NAMESPACE_PREFIX, owner.lower(), repo.lower())


def _extract_owner_repo_from_namespace(namespace: tuple[str, ...]) -> tuple[str, str] | None:
    """从 namespace 中提取 owner 和 repo。

    namespace 格式: ("coding", "repo-memory", owner, repo)
    """
    if len(namespace) >= 4 and namespace[:2] == REPO_MEMORY_NAMESPACE_PREFIX:
        return namespace[2], namespace[3]
    return None



def build_initial_repo_memory(*, repo: GiteeRepo, project_dir: str) -> str:
    """生成首次识别仓库时的记忆文件模板。

    这里不猜测技术栈和启动命令，只写入已经确定的仓库地址、本地目录和安全约定。
    后续由 Agent 在真实分析项目后，通过 `edit_file` 更新稳定结论。
    """
    now = datetime.now(UTC).isoformat()
    virtual_project_dir = "/" + project_dir.replace("\\", "/").strip("/")
    command_repo_dir = project_dir.replace("\\", "/").removeprefix("projects/").strip("/")
    command_repo_dir = command_repo_dir or repo.repo
    return f"""# 仓库记忆：{repo.owner}/{repo.repo}

## 基本信息
- 仓库地址：{repo.clone_url}
- 本地目录：{virtual_project_dir}
- 命令目录：{command_repo_dir}
- 初始化时间：{now}

## 技术栈
- 待分析

## 启动命令
- 待分析

## 测试命令
- 待分析

## 关键文件
- 待分析

## 已知约定
- 文件工具使用 `{virtual_project_dir}/...` 这样的虚拟路径。
- `execute` 默认在 `/projects` 对应的本地目录下执行，命令里直接使用 `{command_repo_dir}`，不要写 `projects/{command_repo_dir}`。
- 不得把 token、私钥、`.env`、`.secrets` 或本机敏感路径写入记忆。
- 如果本记忆与真实仓库文件冲突，以真实文件和实际命令输出为准。

## 最近结论
- 暂无
"""


def get_repo_memory_item(store: BaseStore, namespace: tuple[str, ...]):
    """读取当前标准 key 下的仓库记忆。

    当前仓库记忆。Agent 可见路径仍然是 `/memories/{owner}/{repo}.md`，
    数据库内部 key 由 `repo_memory_store_key()` 生成。
    """
    owner_repo = _extract_owner_repo_from_namespace(namespace)
    if owner_repo is None:
        return None

    owner, repo = owner_repo
    return store.get(namespace, repo_memory_store_key(owner, repo))


def ensure_repo_memory_initialized(
    *,
    store: BaseStore,
    repo: GiteeRepo,
    project_dir: str,
) -> bool:
    """确保当前仓库的记忆文件已存在，文件路径为 /memories/{owner}/{repo}.md。

    只检查当前标准 key，不再读取或迁移旧版 `/repo.md`、`/memories/repo.md`。
    返回值表示本次是否新建了记忆文件。已有文件不会被覆盖。
    """
    namespace = build_repo_memory_namespace(repo.owner, repo.repo)
    new_key = repo_memory_store_key(repo.owner, repo.repo)

    # 只检查当前标准 key。旧 key 由维护脚本或人工 SQL 清理，不在运行时兼容。
    if store.get(namespace, new_key) is not None:
        return False

    store.put(
        namespace,
        new_key,
        create_file_data(build_initial_repo_memory(repo=repo, project_dir=project_dir)),
    )
    return True
