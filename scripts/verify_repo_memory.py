"""验证仓库记忆按仓库命名的隔离机制。"""

import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.store.sqlite import SqliteStore

from agent.core.repo_memory import (
    build_repo_memory_namespace,
    create_repo_backend,
    ensure_repo_memory_initialized,
    repo_memory_store_key,
    repo_memory_virtual_path,
    _LEGACY_REPO_MEMORY_PATH,
    _LEGACY_STORE_KEY,
)
from agent.core.repo_memory_update import RepoMemoryUpdate, update_repo_memory_from_text
from agent.core.middleware import ContextInjectionMiddleware, MemoryUpdateMiddleware
from agent.tools.gitee_api import parse_gitee_repo_url
from langchain_core.messages import AIMessage, HumanMessage


def _make_store(path: Path) -> tuple[SqliteStore, sqlite3.Connection]:
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store, conn


def main() -> None:
    """Verify repo memory namespace isolation and per-repo naming."""

    with tempfile.TemporaryDirectory() as tmp:
        store, conn = _make_store(Path(tmp) / "langgraph-store.sqlite")
        try:
            ai_repo = parse_gitee_repo_url("https://gitee.com/msb-goldbin/ai_repo.git")
            ai_coding = parse_gitee_repo_url("https://gitee.com/clumsypsc/test_coding_repo.git")

            # ---- 1. 首次初始化应创建记忆文件 ----
            created = ensure_repo_memory_initialized(
                store=store,
                repo=ai_repo,
                project_dir="projects/ai_repo",
            )
            if not created:
                raise AssertionError("first initialization should create repo memory")

            # ---- 2. 重复初始化不应覆盖 ----
            second_created = ensure_repo_memory_initialized(
                store=store,
                repo=ai_repo,
                project_dir="projects/ai_repo",
            )
            if second_created:
                raise AssertionError("existing repo memory should not be overwritten")

            # ---- 3. 验证使用按仓库命名的 key ----
            repo_namespace = build_repo_memory_namespace(ai_repo.owner, ai_repo.repo)
            new_key = repo_memory_store_key(ai_repo.owner, ai_repo.repo)
            if new_key != "/msb-goldbin/ai_repo.md":
                raise AssertionError(f"unexpected store key: {new_key}")

            repo_item = store.get(repo_namespace, new_key)
            if repo_item is None:
                raise AssertionError("repo memory was not written with new per-repo key")
            repo_content = repo_item.value.get("content", "")
            if "msb-goldbin/ai_repo" not in repo_content or "/projects/ai_repo" not in repo_content:
                raise AssertionError(f"unexpected repo memory content: {repo_content}")

            # ---- 4. 旧版 key 应不存在（新代码不写入旧 key） ----
            if store.get(repo_namespace, _LEGACY_STORE_KEY) is not None:
                raise AssertionError("new repo memory should not write legacy /repo.md key")
            if store.get(repo_namespace, _LEGACY_REPO_MEMORY_PATH) is not None:
                raise AssertionError("new repo memory should not write legacy /memories/repo.md key")

            # ---- 5. 不同仓库的 namespace 应该隔离 ----
            ensure_repo_memory_initialized(
                store=store,
                repo=ai_coding,
                project_dir="projects/ai_coding",
            )
            coding_namespace = build_repo_memory_namespace(ai_coding.owner, ai_coding.repo)
            coding_key = repo_memory_store_key(ai_coding.owner, ai_coding.repo)
            if coding_key != "/clumsypsc/test_coding_repo.md":
                raise AssertionError(f"unexpected coding store key: {coding_key}")

            coding_item = store.get(coding_namespace, coding_key)
            if coding_item is None:
                raise AssertionError("second repo memory was not written")

            # 验证两个仓库不共享同一 key
            if coding_key == new_key:
                raise AssertionError("different repos should have different store keys")
            if coding_item.value.get("content") == repo_item.value.get("content"):
                raise AssertionError("different repos should have isolated repo memories")

            # ---- 6. CompositeBackend 应能通过按仓库命名的虚拟路径读取 ----
            virtual_path = repo_memory_virtual_path(ai_repo.owner, ai_repo.repo)
            if virtual_path != "/memories/msb-goldbin/ai_repo.md":
                raise AssertionError(f"unexpected virtual path: {virtual_path}")

            backend = create_repo_backend(
                local_backend=__import__("agent.backends.local_shell", fromlist=["LocalShellBackend"]).LocalShellBackend(),
                store=store,
                owner=ai_repo.owner,
                repo=ai_repo.repo,
            )
            read_result = backend.read(virtual_path)
            if read_result.error or "msb-goldbin/ai_repo" not in read_result.file_data["content"]:
                raise AssertionError("CompositeBackend should read repo memory through per-repo virtual path")

            # ---- 7. 旧版 /memories/repo.md 迁移到新版 /{owner}/{repo}.md ----
            legacy_repo = parse_gitee_repo_url("https://gitee.com/msb-goldbin/legacy_repo.git")
            legacy_namespace = build_repo_memory_namespace(legacy_repo.owner, legacy_repo.repo)
            store.put(legacy_namespace, _LEGACY_REPO_MEMORY_PATH, {"content": "legacy v1 memory", "encoding": "utf-8"})
            migrated_created = ensure_repo_memory_initialized(
                store=store,
                repo=legacy_repo,
                project_dir="projects/legacy_repo",
            )
            if migrated_created:
                raise AssertionError("legacy v1 repo memory should be migrated, not recreated")
            legacy_key = repo_memory_store_key(legacy_repo.owner, legacy_repo.repo)
            migrated_item = store.get(legacy_namespace, legacy_key)
            if migrated_item is None or migrated_item.value.get("content") != "legacy v1 memory":
                raise AssertionError("legacy v1 repo memory should be copied to new per-repo key")

            # ---- 8. 旧版 /repo.md 也应迁移到新版 /{owner}/{repo}.md ----
            legacy_v2_repo = parse_gitee_repo_url("https://gitee.com/msb-goldbin/legacy-v2-repo.git")
            legacy_v2_namespace = build_repo_memory_namespace(legacy_v2_repo.owner, legacy_v2_repo.repo)
            store.put(legacy_v2_namespace, _LEGACY_STORE_KEY, {"content": "legacy v2 memory", "encoding": "utf-8"})
            migrated_v2_created = ensure_repo_memory_initialized(
                store=store,
                repo=legacy_v2_repo,
                project_dir="projects/legacy-v2-repo",
            )
            if migrated_v2_created:
                raise AssertionError("legacy v2 repo memory should be migrated, not recreated")
            legacy_v2_key = repo_memory_store_key(legacy_v2_repo.owner, legacy_v2_repo.repo)
            migrated_v2_item = store.get(legacy_v2_namespace, legacy_v2_key)
            if migrated_v2_item is None or migrated_v2_item.value.get("content") != "legacy v2 memory":
                raise AssertionError("legacy v2 repo memory should be copied to new per-repo key")

            # ---- 9. ContextInjectionMiddleware 应注入新版路径 ----
            original_ci_get_config = __import__(
                "agent.core.middleware.context_injection", fromlist=["get_config"],
            ).get_config
            original_mu_get_config = __import__(
                "agent.core.middleware.memory_update", fromlist=["get_config"],
            ).get_config
            original_ci_get_store = __import__(
                "agent.core.middleware.context_injection", fromlist=["get_langgraph_store"],
            ).get_langgraph_store
            original_mu_get_store = __import__(
                "agent.core.middleware.memory_update", fromlist=["get_langgraph_store"],
            ).get_langgraph_store
            try:
                mock_config = {"configurable": {"repo_url": ai_repo.clone_url, "task_kind": "analysis"}}
                __import__(
                    "agent.core.middleware.context_injection", fromlist=["get_config"],
                ).get_config = lambda: mock_config
                __import__(
                    "agent.core.middleware.memory_update", fromlist=["get_config"],
                ).get_config = lambda: mock_config
                __import__(
                    "agent.core.middleware.context_injection", fromlist=["get_langgraph_store"],
                ).get_langgraph_store = lambda: store
                __import__(
                    "agent.core.middleware.memory_update", fromlist=["get_langgraph_store"],
                ).get_langgraph_store = lambda: store

                injected = ContextInjectionMiddleware().before_agent(
                    {"messages": [HumanMessage(content="检查项目")]},
                    None,
                )
                if not injected:
                    raise AssertionError("repo memory should be injected before agent")
                injected_text = injected["messages"][0].content
                if "/memories/msb-goldbin/ai_repo.md" not in injected_text:
                    raise AssertionError(
                        f"injected message should reference per-repo path, got: {injected_text[:200]}"
                    )

                MemoryUpdateMiddleware().after_agent(
                    {
                        "messages": [
                            HumanMessage(content="检查项目"),
                            AIMessage(content="确认项目使用 FastAPI，测试命令为 `python -m pytest ai_repo`。"),
                        ]
                    },
                    None,
                )
                updated_item = store.get(repo_namespace, new_key)
                updated_content = updated_item.value.get("content", "") if updated_item else ""
                if "FastAPI" not in updated_content or "python -m pytest ai_repo" not in updated_content:
                    raise AssertionError("repo memory should be updated after agent")

                updated = update_repo_memory_from_text(
                    store=store,
                    repo=ai_repo,
                    update=RepoMemoryUpdate(
                        task_kind="coding",
                        final_text=(
                            "## 任务完成总结\n"
                            "- 新增 `/health`、`/register`、`/login` 三个 FastAPI 接口。\n"
                            "- 使用 SQLite 保存用户数据，登录返回 JWT token。\n"
                            "- 修改 `main.py`、`test_main.py`、`requirements.txt`。\n"
                            "- 运行 `python -m pytest ai_repo`，6 passed。\n"
                        ),
                        branch_name="feat/user-login",
                        pr_url="https://gitee.com/msb-goldbin/ai_repo/pulls/2",
                    ),
                )
                if not updated:
                    raise AssertionError("structured repo memory update should report changed")
                structured_item = store.get(repo_namespace, new_key)
                structured_content = structured_item.value.get("content", "") if structured_item else ""
                for term in [
                    "## 技术栈",
                    "FastAPI",
                    "SQLite",
                    "pytest",
                    "## 关键文件",
                    "main.py",
                    "test_main.py",
                    "## 已完成能力",
                    "/register",
                    "## 分支与 PR",
                    "feat/user-login",
                    "https://gitee.com/msb-goldbin/ai_repo/pulls/2",
                ]:
                    if term not in structured_content:
                        raise AssertionError(f"structured repo memory missing term: {term}")
            finally:
                __import__(
                    "agent.core.middleware.context_injection", fromlist=["get_config"],
                ).get_config = original_ci_get_config
                __import__(
                    "agent.core.middleware.memory_update", fromlist=["get_config"],
                ).get_config = original_mu_get_config
                __import__(
                    "agent.core.middleware.context_injection", fromlist=["get_langgraph_store"],
                ).get_langgraph_store = original_ci_get_store
                __import__(
                    "agent.core.middleware.memory_update", fromlist=["get_langgraph_store"],
                ).get_langgraph_store = original_mu_get_store
        finally:
            conn.close()

    print("repo memory verification passed")


if __name__ == "__main__":
    main()
