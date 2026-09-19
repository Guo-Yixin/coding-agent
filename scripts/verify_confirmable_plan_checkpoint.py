from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.core.graph import get_store
from agent.core.runtime import (
    _is_approval_prompt,
    _latest_confirmable_plan_message,
    _latest_non_approval_user_prompt,
    _message_metadata,
)


def main() -> None:
    """验证 checkpoint 历史中的方案可以被“确认实施”流程读取。

    这个脚本依赖当前开发库里已有的演示 checkpoint。如果没有包含“修复技术方案”
    的历史会话，则跳过具体断言，只验证确认关键词逻辑。
    """

    assert _is_approval_prompt("确认")
    assert _is_approval_prompt("开始实施")
    assert _is_approval_prompt("确认方案，开始")

    store = get_store()
    for thread in store.list_threads(20):
        thread_id = thread["thread_id"]
        plan_message = _latest_confirmable_plan_message(thread_id)
        if plan_message is None:
            continue
        metadata = _message_metadata(plan_message)
        content = str(plan_message.get("content") or "")
        assert metadata.get("task_kind") == "planning"
        assert metadata.get("awaiting_confirmation") is True
        assert any(marker in content for marker in ["技术方案", "修复技术方案", "是否确认实施该方案"])
        source_prompt = _latest_non_approval_user_prompt(thread_id, "")
        assert source_prompt
        assert not _is_approval_prompt(source_prompt)
        print("confirmable plan checkpoint verification passed")
        return

    print("confirmable plan checkpoint verification skipped: no confirmable checkpoint plan found")


if __name__ == "__main__":
    main()
