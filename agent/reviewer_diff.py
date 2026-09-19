from __future__ import annotations

"""Reviewer 子 Agent 使用的 diff 解析与位置校验工具。

这个模块不负责调用模型，也不负责访问 Gitee API。它的职责很单一：

1. 调用本地 `git diff`，拿到 PR 分支或工作区的 unified diff 文本。
2. 用确定性的 Python 代码解析 diff，提取“本次变更涉及哪些文件”和“新文件中哪些行发生了变更”。
3. 在 reviewer 子 Agent 记录 finding 前，校验 finding 的文件和行号是否真实属于本次 diff。

为什么要单独做这个模块：

- 代码审查不能完全相信模型自己从 diff 里猜行号，LLM 容易出现文件名或行号漂移。
- finding 如果指向不存在的文件或不在本次 diff 中的行，会降低审查报告可信度。
- 把 diff 解析写成确定性工具，可以让 reviewer 子 Agent 专注于判断风险，而不是处理行号细节。
"""

import re
from dataclasses import dataclass, field

from agent.backends.local_shell import LocalShellBackend


# 允许作为 git ref 的字符白名单。
#
# 这个正则用于保护 `git diff {base}` 和 `git diff {base}...{head}` 命令。
# base/head 理论上应该是分支名、tag、commit hash 或 HEAD 这类 git ref。
# 如果不做校验，模型可能把 `; rm -rf ...`、`&& command` 等 shell 片段拼进命令。
# 这里限制：
# - 第一个字符必须是字母或数字；
# - 后续只允许字母、数字、点、下划线、斜杠、短横线；
# - 长度最多 181 个字符，避免异常超长输入。
_SAFE_GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{0,180}$")


@dataclass(frozen=True)
class DiffFile:
    """单个变更文件的 diff 摘要。

    `changed_lines` 只记录新文件中的新增或修改行号，用于校验 Reviewer finding
    是否真的落在本次 diff 上。删除行没有新文件行号，第一版不作为行级 finding 目标。
    """

    # diff 中的文件路径，统一使用正斜杠，并且已经去掉 a/ 或 b/ 前缀。
    path: str
    # 新文件中的新增或修改行号。使用 tuple 是为了让 dataclass 在 frozen=True 下更稳定。
    changed_lines: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiffSummary:
    """本次 review diff 的结构化摘要。"""

    # diff 的基准 ref，例如 master、HEAD、某个 commit hash。
    base: str
    # diff 的目标 ref。为 None 时表示审查工作区相对于 base 的 diff。
    head: str | None
    # 每个变更文件的结构化摘要。
    files: tuple[DiffFile, ...]
    # 原始 unified diff 文本。保留它是为了必要时让 reviewer 子 Agent 查看完整上下文。
    raw_diff: str

    @property
    def changed_file_paths(self) -> tuple[str, ...]:
        """返回本次 diff 涉及的所有文件路径。"""

        # 从 DiffFile 列表中提取 path，前端或工具层可以快速判断某个文件是否属于本次变更。
        return tuple(file.path for file in self.files)

    def changed_lines_for(self, file_path: str) -> set[int]:
        """返回某个文件在新文件侧发生变更的行号集合。"""

        # 先把外部传入路径规整成 diff 内部使用的格式，避免 a/main.py、b/main.py、main.py 比较失败。
        normalized = _normalize_diff_path(file_path)
        # 在结构化文件列表中查找目标文件。
        for file in self.files:
            # 只要路径完全一致，就把 tuple 行号转换成 set，方便后续 O(1) 判断行号是否存在。
            if file.path == normalized:
                return set(file.changed_lines)
        # 文件不存在时返回空集合，调用方会据此判断 line 不合法。
        return set()


def _validate_git_ref(value: str, *, name: str) -> str:
    """校验 git ref，避免模型把 shell 片段塞进 diff 命令。"""

    # 去掉用户或模型输入两端空白，避免 ` master ` 这种正常输入被误判。
    ref = value.strip()
    # 空字符串和不符合白名单的 ref 都拒绝。
    # 这里主动抛 ValueError，让上层工具返回清晰错误，而不是执行危险命令。
    if not ref or not _SAFE_GIT_REF_RE.fullmatch(ref):
        raise ValueError(f"{name} 不是安全的 git ref: {value!r}")
    # 返回规整后的安全 ref，后续可以拼接到 git diff 命令。
    return ref


def _normalize_diff_path(path: str) -> str:
    """统一 diff 文件路径，去掉 a/、b/ 前缀并转换为正斜杠。"""

    # Git diff 在 Windows 上也通常使用正斜杠；这里额外把反斜杠转换掉，兼容工具入参。
    normalized = path.strip().replace("\\", "/")
    # unified diff 的文件路径经常形如 a/main.py 或 b/main.py。
    # reviewer finding 通常只写 main.py，所以内部统一去掉前缀。
    if normalized.startswith("a/") or normalized.startswith("b/"):
        normalized = normalized[2:]
    # 返回标准化路径，供文件集合和 finding 校验共用。
    return normalized


def parse_unified_diff(diff_text: str, *, base: str = "HEAD", head: str | None = None) -> DiffSummary:
    """解析 unified diff，提取变更文件和新文件中的变更行号。

    这里不让模型自己从 diff 文本中猜行号，原因是 LLM 容易出现 position drift。
    确定性的 Python 解析可以保证 finding 行号校验更稳定。
    """

    # key 是标准化文件路径，value 是该文件在“新文件侧”的新增/修改行号集合。
    files: dict[str, set[int]] = {}
    # 当前正在解析的文件路径。遇到 `diff --git` 或 `+++` 时更新。
    current_file: str | None = None
    # 当前 hunk 中新文件侧的行号。遇到 `@@ -old +new @@` 时初始化。
    new_line: int | None = None

    # unified diff 按行解析即可，不需要构建完整 AST。
    for raw_line in diff_text.splitlines():
        # `diff --git a/foo.py b/foo.py` 表示一个新文件 diff 块开始。
        if raw_line.startswith("diff --git "):
            # 新文件块开始时，先清空当前文件和行号状态，避免上一个文件的行号污染下一个文件。
            current_file = None
            new_line = None
            # 典型 split 结果：["diff", "--git", "a/foo.py", "b/foo.py"]。
            parts = raw_line.split()
            # 第 4 段通常是新文件路径，也就是 b/foo.py。
            if len(parts) >= 4:
                # 标准化路径，去掉 b/ 前缀。
                current_file = _normalize_diff_path(parts[3])
                # 即使后续没有新增行，也先登记文件，表示它属于本次 diff。
                files.setdefault(current_file, set())
            # 当前行处理完毕，继续解析下一行。
            continue

        # `+++ b/foo.py` 表示新文件侧路径。
        # 对新增文件、重命名、某些 diff 输出，+++ 行比 diff --git 行更可靠。
        if raw_line.startswith("+++ "):
            # 取出 `+++ ` 后面的路径。
            path = raw_line[4:].strip()
            # `/dev/null` 表示删除文件的新文件侧不存在，不能作为可定位的新文件路径。
            if path != "/dev/null":
                # 更新当前文件路径，并登记到文件集合。
                current_file = _normalize_diff_path(path)
                files.setdefault(current_file, set())
            # 当前行处理完毕。
            continue

        # hunk 头形如：@@ -10,7 +10,8 @@。
        # 其中 +10,8 表示新文件从第 10 行开始，这个数字是后续新增/上下文行的计数起点。
        if raw_line.startswith("@@"):
            # 只关心新文件侧的起始行号，也就是 `+数字`。
            match = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            # 如果匹配失败，说明 hunk 头格式异常；后续行号校验无法继续，所以置为 None。
            new_line = int(match.group(1)) if match else None
            # 当前行处理完毕。
            continue

        # 如果还没有进入某个文件，或还没有遇到 hunk 头，就不能解析行号。
        if current_file is None or new_line is None:
            continue

        # 以 `+` 开头且不是 `+++` 的行，表示新文件新增的一行。
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            # 新增行属于本次 diff 的有效 finding 位置。
            files.setdefault(current_file, set()).add(new_line)
            # 新增行占用了新文件中的一个行号，所以行号递增。
            new_line += 1
        # 以 `-` 开头且不是 `---` 的行，表示旧文件删除的一行。
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            # 删除行只存在于旧文件，不增加新文件行号。
            # 第一版 reviewer finding 只定位到新文件侧行号，所以这里不记录删除行。
            continue
        else:
            # context 行或空行都对应新文件行号，需要递增。
            # 例如普通上下文行虽然不是变更行，但它会推动后续新增行的行号。
            new_line += 1

    # 把内部 dict/set 转成稳定、可序列化、不可变的 dataclass 结构。
    # sorted(files.items()) 保证相同 diff 每次解析输出顺序一致，方便测试和日志对比。
    parsed_files = tuple(
        # 每个文件的行号也排序，避免 set 的无序性影响结果。
        DiffFile(path=path, changed_lines=tuple(sorted(lines)))
        for path, lines in sorted(files.items())
    )
    # 返回结构化摘要，同时保留原始 diff 供后续需要完整上下文时使用。
    return DiffSummary(base=base, head=head, files=parsed_files, raw_diff=diff_text)


def get_local_diff(backend: LocalShellBackend, repo_dir: str, base: str = "HEAD") -> str:
    """返回 reviewer 要审查的本地 git diff 文本。

    该函数保留给旧调用点使用。新 reviewer 工具优先调用
    `get_local_diff_summary`，因为后者会同时返回变更文件和变更行号。
    """

    # 校验 base，避免模型或用户把 shell 片段拼进 git 命令。
    base = _validate_git_ref(base, name="base")
    # 读取工作区相对于 base 的 diff。--unified=80 给 reviewer 更多上下文，便于判断风险。
    result = backend.run(f"git diff --unified=80 {base}", cwd=repo_dir)
    # git diff 失败时，把 git 的错误信息向上抛出，由工具层脱敏并展示。
    if result.exit_code != 0:
        raise RuntimeError(result.stderr or result.stdout or "git diff failed")
    # 返回原始 diff 文本。这个旧函数不做结构化解析。
    return result.stdout


def get_local_diff_summary(
    backend: LocalShellBackend,
    repo_dir: str,
    *,
    base: str = "HEAD",
    head: str | None = None,
) -> DiffSummary:
    """生成本地分支或工作区 diff 的结构化摘要。

    Args:
        backend: 当前工作区的 LocalShellBackend。
        repo_dir: 仓库虚拟路径，例如 `projects/ai_coding`。
        base: 对比基准分支、commit 或 `HEAD`。
        head: 可选目标分支。传入时使用 `base...head`，不传时审查工作区相对 base 的 diff。
    """

    # 校验基准 ref，确保它可以安全拼入 git diff 命令。
    base_ref = _validate_git_ref(base, name="base")
    # 如果调用方传入 head，也做同样的安全校验；不传则表示审查当前工作区。
    head_ref = _validate_git_ref(head, name="head") if head else None
    # 有 head 时使用 `base...head`，通常表示审查两个分支之间的变更。
    # 没有 head 时只传 base，表示审查工作区相对于 base 的未提交或已提交变更。
    range_expr = f"{base_ref}...{head_ref}" if head_ref else base_ref
    # 调用 LocalShellBackend 执行 git diff。
    # cwd 使用 backend 的虚拟路径，例如 projects/ai_coding，由 backend 做 Windows 路径映射和权限校验。
    result = backend.run(f"git diff --unified=80 {range_expr}", cwd=repo_dir)
    # 如果 git 命令失败，直接抛异常，避免 reviewer 基于空 diff 继续胡乱审查。
    if result.exit_code != 0:
        raise RuntimeError(result.stderr or result.stdout or "git diff failed")
    # 用确定性解析器把原始 diff 转成结构化摘要。
    return parse_unified_diff(result.stdout, base=base_ref, head=head_ref)


def validate_finding_location(summary: DiffSummary, *, file: str, line: int | None) -> tuple[bool, str]:
    """校验 finding 是否指向本次 diff 中真实存在的文件和变更行。"""

    # 统一用户、模型或工具传入的文件路径格式，避免 a/、b/、反斜杠导致误判。
    normalized = _normalize_diff_path(file)
    # 把本次 diff 中的文件路径转成 set，方便判断 finding 文件是否属于本次变更。
    changed_files = set(summary.changed_file_paths)
    # 如果文件不在本次 diff 中，finding 就不可信，直接拒绝。
    if normalized not in changed_files:
        return False, f"文件不在本次 diff 中: {file}"
    # 没有行号时，只做文件级校验。文件属于本次 diff，就允许记录文件级 finding。
    if line is None:
        return True, "文件属于本次 diff，未指定行号。"
    # 读取该文件所有新增/修改行号。
    changed_lines = summary.changed_lines_for(normalized)
    # 指定了行号时，必须落在新增/修改行集合内。
    # 这样可以避免 reviewer 把 finding 指向旧代码、上下文行或不存在的行。
    if line not in changed_lines:
        return False, f"行号 {line} 不是文件 {normalized} 的新增或修改行。"
    # 文件和行号都通过校验，finding 可以保存。
    return True, "finding 位置有效。"
