from __future__ import annotations

"""工作区路径解析模块。

`Workspace` 是 `LocalShellBackend` 的轻量依赖，专门负责一件事：
把 Agent 或工具传入的路径解析成真实文件系统路径，并保证结果仍然位于工作区根目录内。

为什么要单独抽这个类：
- 后端、runtime、repo mapping 等模块都会使用工作区路径。
- 路径安全不能散落在各个业务函数里，否则很容易漏掉某个入口。
- 统一通过 `Workspace.resolve()` 可以把“工作区外路径禁止访问”这条规则固定下来。

注意：
这里不负责 DeepAgents permissions，也不负责命令安全。它只处理文件系统路径边界。
"""

from pathlib import Path

from .permissions import assert_path_inside


class Workspace:
    """本地工作区封装。

    参数：
        root: 工作区根目录，例如 `B:\\ai_workspace`。

    设计原则：
    - 初始化时确保 root 目录存在。
    - 所有相对路径都以 root 为基准解析。
    - 所有解析结果都必须通过 `assert_path_inside` 校验。

    这样可以避免模型传入 `..`、绝对路径或奇怪路径时跳出工作区。
    """

    def __init__(self, root: Path):
        """创建工作区对象，并确保根目录存在。"""

        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str | Path = ".") -> Path:
        """解析路径并确保结果仍在工作区内。

        参数：
            path: 可以是相对路径，也可以是绝对路径。

        返回：
            解析后的绝对路径。

        安全边界：
            如果最终路径不在 `self.root` 内，会抛出 `WorkspacePermissionError`。
            这保证了调用方不能通过 `../` 或外部绝对路径访问工作区外文件。
        """

        candidate = Path(path)
        if not candidate.is_absolute():
            # 相对路径一律按工作区根目录解析。
            candidate = self.root / candidate
        return assert_path_inside(candidate, self.root)
