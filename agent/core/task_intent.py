from __future__ import annotations

"""用户任务意图识别。

本文件负责把用户输入归类为 Agent 的第一层任务类型。任务类型会直接影响后续
系统提示词、工具权限、是否允许修改代码、是否创建 Pull Request 等关键行为。

当前实现采用“模型结构化分类 + 规则兜底 + 安全降级”的三段式方案：
1. 轻量、确定性的特殊任务仍然先用关键词快速识别，例如只查看工作区、只 git pull。
2. 普通任务调用模型，并使用 LangChain `with_structured_output()` 返回 Pydantic 对象。
3. 如果模型失败、结构化解析失败，或模型把只读任务误判为 coding，则回退或降级。

为什么不完全依赖模型：
- coding 是唯一允许修改文件、提交、push、创建 PR 的模式，不能完全交给模型自由判断。
- 用户明确说“不要修改代码”“只审查”“只给方案”时，必须强制只读。
- 关键词备份版本保留在 task_intent_keyword_backup.py 中，既能回滚，也能作为兜底。
"""

import logging
from functools import lru_cache
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from agent.core.model import make_intent_model

TaskKind = Literal["coding", "analysis", "planning", "qa", "sync", "inspect", "review"]

logger = logging.getLogger("agent.run.task_intent")

_ALLOWED_TASK_KINDS: set[str] = {"coding", "analysis", "planning", "qa", "sync", "inspect", "review"}


class IntentClassification(BaseModel):
    """模型意图分类的结构化输出。

    使用 Pydantic 的意义是把“模型必须返回固定字段、固定枚举”的要求交给框架校验。
    如果模型输出不符合结构，LangChain/Pydantic 会抛出异常，外层再回退到关键词规则。
    """

    task_kind: TaskKind = Field(description="用户任务类型，只能是固定枚举之一。")
    confidence: float = Field(ge=0, le=1, description="分类置信度，范围 0 到 1。")
    reason: str = Field(description="中文短理由，不超过 40 个字。")

    @field_validator("reason")
    @classmethod
    def _trim_reason(cls, value: str) -> str:
        """限制日志中的理由长度，避免模型返回大段文本污染日志。"""

        return value.strip()[:40]


def _normalize_prompt(prompt: str) -> str:
    """把用户输入规整成适合本地规则判断的短文本。

    这里仍然保留本地规则，是因为权限边界必须有确定性兜底。模型分类可以提升泛化能力，
    但不能替代后端对“是否允许写代码”的最终保护。
    """

    return " ".join((prompt or "").lower().split())


def _contains_any(text: str, keywords: list[str]) -> bool:
    """判断文本是否包含任意关键词。"""

    return any(keyword in text for keyword in keywords)


def is_pull_only_task(prompt: str) -> bool:
    """判断用户是否只想同步远程仓库代码。

    这个函数仍然使用关键词，不调用模型。原因是：
    - 它会被后台任务入口直接调用；
    - git pull 属于轻量同步任务，没必要消耗一次模型调用；
    - 如果同时出现“修改、提交、push、PR”等词，就不再当作单纯同步任务。
    """

    normalized = _normalize_prompt(prompt)
    pull_keywords = ["git pull", " pull", "pull一下", "拉取", "同步远程", "更新远程", "拉一下"]
    change_keywords = [
        "修改",
        "新增",
        "修复",
        "创建pr",
        "创建 pr",
        "pull request",
        "提交",
        "push",
        "实现",
        "开发",
    ]
    return _contains_any(normalized, pull_keywords) and not _contains_any(normalized, change_keywords)


def is_workspace_listing_task(prompt: str) -> bool:
    """判断用户是否只是询问本地工作区有哪些项目。

    这个函数也保留关键词判断，避免“当前有哪些项目”这类简单问题触发模型调用。
    """

    normalized = _normalize_prompt(prompt)
    list_keywords = ["有哪些项目", "工作目录", "本地工作", "workspace", "项目列表"]
    change_keywords = ["修改", "修复", "创建", "提交", "push", "pr", "实现", "开发"]
    return _contains_any(normalized, list_keywords) and not _contains_any(normalized, change_keywords)


@lru_cache(maxsize=1)
def _make_structured_intent_model():
    """创建带结构化输出约束的意图分类模型。

    DeepSeek 使用 OpenAI-compatible 接口。为了兼容性，这里选择 `json_mode`：
    - prompt 中明确要求只返回 JSON；
    - LangChain 负责把 JSON 解析为 `IntentClassification`；
    - Pydantic 负责字段和枚举校验。

    如果未来模型支持更严格的原生 JSON Schema，可以把 method 调整为 `json_schema`。
    """

    return make_intent_model().with_structured_output(IntentClassification, method="json_mode")


def _classify_by_keyword_backup(prompt: str) -> TaskKind:
    """调用备份文件中的关键词分类逻辑。

    备份文件是模型分类改造前的完整实现。模型不可用、结构化解析失败或测试环境没有
    真实 key 时，仍然可以保持项目可用。
    """

    from agent.core.task_intent_keyword_backup import classify_task_kind as keyword_classify_task_kind

    return keyword_classify_task_kind(prompt)


def _classify_by_model(prompt: str) -> TaskKind:
    """调用模型完成第一层用户意图分类。"""

    system_prompt = """你是 AI Coding 系统的第一层用户意图分类器。
你只负责分类，不要回答用户问题，不要生成方案，不要写代码。

你必须从以下固定类别中选择一个：
- coding：用户明确要求修改、实现、生成代码、执行已确认方案、提交、push、创建或复用 PR。
- planning：用户要求技术方案、实施方案、设计步骤、修改建议，或要求先给方案等待确认。
- analysis：用户要求分析项目、梳理结构、解释代码、检查现状、总结模块。
- qa：用户问概念、原因、区别、是否可以、某个文件/函数是做什么的。
- sync：用户只要求 git pull、拉取、同步远程代码，不要求修改。
- inspect：用户只问本地工作区、当前工作目录、有哪些项目。
- review：用户要求代码审查、PR review、读取 PR diff、输出审查报告，尤其是明确不要修改代码。

你必须只返回 JSON，不要返回 Markdown，不要返回额外解释。
JSON 字段必须包含：
- task_kind：固定类别之一。
- confidence：0 到 1 之间的小数。
- reason：中文短理由，不超过 40 个字。
"""
    result = _make_structured_intent_model().invoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=f"用户输入：{prompt}")]
    )
    if isinstance(result, dict):
        # 某些 provider/版本在结构化输出时可能返回 dict，这里做一次兼容解析。
        parsed = IntentClassification.model_validate(result)
    elif isinstance(result, IntentClassification):
        parsed = result
    else:
        parsed = IntentClassification.model_validate(result)

    logger.info(
        "模型意图分类完成：task_kind=%s confidence=%s reason=%s",
        parsed.task_kind,
        parsed.confidence,
        parsed.reason,
    )
    return parsed.task_kind


def _has_negative_change_marker(normalized: str) -> bool:
    """识别用户明确要求不要改代码、不要提交、只读处理的表达。"""

    return _contains_any(
        normalized,
        [
            "先不要修改",
            "不要修改",
            "不修改",
            "先不要改",
            "不要改",
            "不改代码",
            "不要改代码",
            "只分析",
            "只给方案",
            "只做方案",
            "只 review",
            "只review",
            "只做代码审查",
            "只做审查",
            "不要提交",
            "不要push",
            "不要 push",
            "不要创建pr",
            "不要创建 pr",
        ],
    )


def _has_explicit_coding_marker(normalized: str) -> bool:
    """识别用户明确允许进入写代码阶段的表达。"""

    return _contains_any(
        normalized,
        [
            "确认实施",
            "确定实施",
            "开始实施",
            "确认，实施",
            "确认该方案",
            "按照方案实施",
            "按方案实施",
            "执行方案",
            "生成代码",
            "修改代码",
            "开始修改",
            "实现这个功能",
            "开发这个功能",
            "提交",
            "push",
            "创建pr",
            "创建 pr",
            "创建 pull request",
        ],
    )


def _has_review_marker(normalized: str) -> bool:
    """识别代码审查相关表达。"""

    return _contains_any(
        normalized,
        [
            "review",
            "reviewer",
            "代码审查",
            "代码评审",
            "审查pr",
            "审查 pr",
            "评审pr",
            "评审 pr",
            "pr review",
            "pr审查",
            "pr 审查",
            "pr评审",
            "pr 评审",
            "pull request review",
            "输出中文审查报告",
            "读取 pr diff",
            "读取pr diff",
            "pr diff",
            "审查报告",
        ],
    )


def _has_planning_marker(normalized: str) -> bool:
    """识别方案类表达。"""

    return _contains_any(
        normalized,
        [
            "方案",
            "计划",
            "设计",
            "步骤",
            "怎么做",
            "如何做",
            "先列出",
            "先帮我设计",
            "由我确认",
            "修改建议",
            "实施建议",
        ],
    )


def _has_review_fix_plan_marker(normalized: str) -> bool:
    """识别“基于审查结果生成修复方案”的只读方案任务。

    这类输入里经常同时出现 `review`、`findings`、`审查报告` 和 `方案`。
    它不是重新做 PR 审查，而是读取已有审查结论，整理后续修复计划。
    """

    has_review_source = _contains_any(
        normalized,
        [
            "审查报告",
            "review findings",
            "结构化 findings",
            "findings",
            "/reviews/",
        ],
    )
    has_fix_plan = _contains_any(normalized, ["修复方案", "修改方案", "整改方案", "生成方案", "给我一个方案"])
    return has_review_source and has_fix_plan


def _has_coding_marker(normalized: str) -> bool:
    """识别普通开发实现类表达。"""

    return _contains_any(
        normalized,
        [
            "修改",
            "修复",
            "新增",
            "增加",
            "实现",
            "开发",
            "改为",
            "改成",
            "改造",
            "迁移",
            "接入",
            "升级",
            "重构",
            "提交",
            "push",
            "运行测试",
        ],
    )


def _apply_security_guard(prompt: str, predicted: TaskKind) -> TaskKind:
    """对模型分类结果做权限安全修正。

    这里是整个分类链路的安全阀：模型可以建议任务类型，但不能突破用户明确给出的只读边界。
    """

    normalized = _normalize_prompt(prompt)
    has_negative = _has_negative_change_marker(normalized)
    has_explicit_coding = _has_explicit_coding_marker(normalized)
    has_review = _has_review_marker(normalized)
    has_planning = _has_planning_marker(normalized)
    has_review_fix_plan = _has_review_fix_plan_marker(normalized)
    has_coding = _has_coding_marker(normalized)

    if has_review_fix_plan and has_negative:
        return "planning"
    if has_review and has_negative:
        return "review"
    if predicted == "coding" and has_negative:
        if has_review:
            return "review"
        if has_planning:
            return "planning"
        return "analysis"

    # “确认/开始/实施”这类短回复通常依赖上一轮方案。只要用户明确表达开始实施，
    # 就允许进入 coding，避免被模型误判成 qa 或 planning。
    if has_explicit_coding and not has_negative:
        return "coding"

    # 明确 PR 审查且没有开发动作时，强制 review。
    if has_review and not has_coding:
        return "review"

    # 明确方案类且没有开发动作时，强制 planning。
    if has_planning and not has_coding:
        return "planning"

    return predicted


def classify_task_kind(prompt: str) -> TaskKind:
    """按用户意图选择 Agent 工作模式。

    coding 是唯一允许写文件、执行提交、push 和创建 PR 的模式。其余模式都按只读任务处理，
    最多准备或读取本地仓库，然后输出分析、方案、审查报告或答案。
    """

    normalized = _normalize_prompt(prompt)
    if not normalized:
        return "qa"

    # 两类低成本、低歧义任务先本地快速判断，避免无意义模型调用。
    if is_pull_only_task(prompt):
        logger.info("关键词快速分类：task_kind=sync")
        return "sync"
    if is_workspace_listing_task(prompt):
        logger.info("关键词快速分类：task_kind=inspect")
        return "inspect"

    try:
        predicted = _classify_by_model(prompt)
    except Exception as exc:
        fallback = _classify_by_keyword_backup(prompt)
        logger.warning(
            "模型意图分类失败，回退关键词分类：fallback=%s error=%s",
            fallback,
            exc,
        )
        return _apply_security_guard(prompt, fallback)

    final_kind = _apply_security_guard(prompt, predicted)
    if final_kind != predicted:
        logger.info("意图分类被安全规则修正：model=%s final=%s", predicted, final_kind)
    return final_kind


def is_read_only_task(task_kind: TaskKind) -> bool:
    """只读任务不允许写文件、提交、push 和创建 PR。"""

    return task_kind in {"analysis", "planning", "qa", "inspect", "review"}
