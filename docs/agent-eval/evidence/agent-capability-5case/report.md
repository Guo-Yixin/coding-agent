# Agent Eval 评测报告 `f4116f81f5ff6f00`

- **结果：** 1/5 道通过
- **模式：** `real`
- **生成时间：** `2026-09-26T12:58:46.667592+00:00`
- **Agent 提交：** `710862e51e382762de1b3cccf63fdf965d369f4e`
- **目标仓库：** `test-coding-eval`
- **模型：** `DeepSeek deepseek-flash`
- **Agent 适配器：** `none`
- **总耗时：** 4.7m
- **总 Token：** 3,511,041

## 案例结果

| 案例 | 结果 | 目标测试 | 回归测试 | 隐藏验收 | 检索命中@5 | Token | Agent 耗时 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `taskboard-group-by-status` | **未通过** | 未通过 | 通过 | 未通过 | 1.0 | 109,741 | 22.9s |
| `taskboard-priority-aliases` | **未通过** | 未通过 | 通过 | 未通过 | 1.0 | 986,997 | 76.0s |
| `taskboard-select-tasks` | **未通过** | 未通过 | 通过 | 未通过 | 1.0 | 408,737 | 35.3s |
| `taskboard-status-filter` | **通过** | 通过 | 通过 | 通过 | 1.0 | 784,972 | 67.6s |
| `taskboard-title-search` | **未通过** | 未通过 | 通过 | 未通过 | 1.0 | 1,220,594 | 78.2s |

## 未通过原因

### `taskboard-group-by-status`

- Agent did not modify required files: taskboard/__init__.py, taskboard/tasks.py, tests/test_group_tasks_by_status.py
- test failed (1): [LOCAL_PATH] -m pytest tests/test_group_tasks_by_status.py -q
F                                                                        [100%]
================================== FAILURES ===================================
_____________ test_groups_normalized_statuses_and_preserves_order _____________

    def test_groups_normalized_statuses_and_preserves_order():
        tasks = [
            {"id": 1, "status": "Open"},
            {"id": 2, "status": "done"},
            {"id": 3, "status": "OPEN"},
            {"id": 4},
            {"id": 5, "status": None},
        ]
    
>       groups = group_tasks_by_status(tasks)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_group_tasks_by_status.py:13: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

tasks = [{'id': 1, 'status': 'Open'}, {'id': 2, 'status': 'done'}, {'id': 3, 'status': 'OPEN'}, {'id': 4}, {'id': 5, 'status': None}]

    def group_tasks_by_status(tasks: Iterable[Task]) -> dict[str, list[Task]]:
        """Group tasks by normalized status, preserving first-seen group and row order."""
    
>       raise NotImplementedError("benchmark task: group tasks by status")
E       NotImplementedError: benchmark task: group tasks by status

taskboard\tasks.py:38: NotImplementedError
=========================== short test summary info ===========================
FAILED tests/test_group_tasks_by_status.py::test_groups_normalized_statuses_and_preserves_order
1 failed in 0.12s

- test failed (1): [LOCAL_PATH] [LOCAL_PATH] [LOCAL_PATH]
Traceback (most recent call last):
  File "[LOCAL_PATH]", line 29, in <module>
    main()
    ~~~~^^
  File "[LOCAL_PATH]", line 21, in main
    groups = group_tasks_by_status(tasks)
  File "[LOCAL_PATH]", line 38, in group_tasks_by_status
    raise NotImplementedError("benchmark task: group tasks by status")
NotImplementedError: benchmark task: group tasks by status

- Plan approval evidence is incomplete: the plan must be pending, the workspace clean before approval, and coding resumed after approval
- Plan quality rubric missed required sections: 需求理解 / 需求拆解 / 目标, 涉及文件 / 相关文件 / 改动文件 / taskboard/tasks.py / taskboard/__init__.py / tests/, 验证方案 / 测试方案 / pytest / 测试命令

### `taskboard-priority-aliases`

- Agent did not modify required files: taskboard/tasks.py, tests/test_sort_by_priority.py
- test failed (1): [LOCAL_PATH] -m pytest tests/test_sort_by_priority.py -q
F                                                                        [100%]
================================== FAILURES ===================================
________ test_priority_sort_keeps_equal_and_unknown_priorities_stable _________

    def test_priority_sort_keeps_equal_and_unknown_priorities_stable():
        tasks = [
            {"id": 1, "priority": "low"},
            {"id": 2, "priority": "urgent"},
            {"id": 3, "priority": "backlog"},
            {"id": 4, "priority": "high"},
            {"id": 5, "priority": "high"},
        ]
>       assert [task["id"] for task in sort_by_priority(tasks)] == [2, 4, 5, 1, 3]
E       assert [4, 5, 1, 2, 3] == [2, 4, 5, 1, 3]
E         
E         At index 0 diff: 4 != 2
E         Use -v to get more diff

tests\test_sort_by_priority.py:12: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_sort_by_priority.py::test_priority_sort_keeps_equal_and_unknown_priorities_stable
1 failed in 0.11s

- test failed (1): [LOCAL_PATH] [LOCAL_PATH] [LOCAL_PATH]
Traceback (most recent call last):
  File "[LOCAL_PATH]", line 25, in <module>
    main()
    ~~~~^^
  File "[LOCAL_PATH]", line 21, in main
    assert [item["id"] for item in sort_by_priority(tasks)] == [2, 4, 1, 3, 5, 6, 7]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError


### `taskboard-select-tasks`

- Agent did not modify required files: taskboard/__init__.py, taskboard/tasks.py, tests/test_select_tasks.py
- test failed (1): [LOCAL_PATH] -m pytest tests/test_select_tasks.py -q
F                                                                        [100%]
================================== FAILURES ===================================
__ test_select_tasks_combines_case_insensitive_filters_and_keeps_input_order __

    def test_select_tasks_combines_case_insensitive_filters_and_keeps_input_order():
        tasks = [
            {"id": 1, "title": "Fix API timeout", "status": "Open"},
            {"id": 2, "title": "Write API docs", "status": "done"},
            {"id": 3, "title": "API migration", "status": "OPEN"},
            {"id": 4, "status": "open"},
        ]
        original = [dict(task) for task in tasks]
    
>       assert [task["id"] for task in select_tasks(tasks, status="open", query="api")] == [1, 3]
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests\test_select_tasks.py:13: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

tasks = [{'id': 1, 'title': 'Fix API timeout', 'status': 'Open'}, {'id': 2, 'title': 'Write API docs', 'status': 'done'}, {'id': 3, 'title': 'API migration', 'status': 'OPEN'}, {'id': 4, 'status': 'open'}]
status = 'open', query = 'api'

    def select_tasks(
        tasks: Iterable[Task], *, status: str | None = None, query: str = ""
    ) -> list[Task]:
        """Select tasks by optional case-insensitive status and title query."""
    
>       raise NotImplementedError("benchmark task: combine task filters")
E       NotImplementedError: benchmark task: combine task filters

taskboard\tasks.py:46: NotImplementedError
=========================== short test summary info ===========================
FAILED tests/test_select_tasks.py::test_select_tasks_combines_case_insensitive_filters_and_keeps_input_order
1 failed in 0.12s

- test failed (1): [LOCAL_PATH] [LOCAL_PATH] [LOCAL_PATH]
Traceback (most recent call last):
  File "[LOCAL_PATH]", line 28, in <module>
    main()
    ~~~~^^
  File "[LOCAL_PATH]", line 20, in main
    assert [item["id"] for item in select_tasks(tasks, status="open", query="api")] == [1, 3]
                                   ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "[LOCAL_PATH]", line 46, in select_tasks
    raise NotImplementedError("benchmark task: combine task filters")
NotImplementedError: benchmark task: combine task filters

- Plan approval evidence is incomplete: the plan must be pending, the workspace clean before approval, and coding resumed after approval
- Plan quality rubric missed required sections: 需求理解 / 需求拆解 / 目标, 涉及文件 / 相关文件 / 改动文件 / taskboard/tasks.py / taskboard/__init__.py / tests/, 验证方案 / 测试方案 / pytest / 测试命令
- Injected tool failure was not followed by a verified successful recovery

### `taskboard-title-search`

- Agent did not modify required files: taskboard/tasks.py, tests/test_search_tasks.py
- test failed (1): [LOCAL_PATH] -m pytest tests/test_search_tasks.py -q
FF                                                                       [100%]
================================== FAILURES ===================================
_____________ test_search_is_case_insensitive_and_preserves_order _____________

    def test_search_is_case_insensitive_and_preserves_order():
        tasks = [
            {"id": 1, "title": "Fix API timeout"},
            {"id": 2, "title": "Write API docs"},
            {"id": 3, "title": "Clean UI"},
        ]
>       assert [task["id"] for task in search_tasks(tasks, "api")] == [1, 2]
E       assert [] == [1, 2]
E         
E         Right contains 2 more items, first extra item: 1
E         Use -v to get more diff

tests\test_search_tasks.py:10: AssertionError
__________________ test_search_ignores_tasks_without_a_title __________________

    def test_search_ignores_tasks_without_a_title():
>       assert search_tasks([{"id": 1}, {"id": 2, "title": "API"}], "api") == [{"id": 2, "title": "API"}]
E       AssertionError: assert [] == [{'id': 2, 'title': 'API'}]
E         
E         Right contains one more item: {'id': 2, 'title': 'API'}
E         Use -v to get more diff

tests\test_search_tasks.py:14: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_search_tasks.py::test_search_is_case_insensitive_and_preserves_order
FAILED tests/test_search_tasks.py::test_search_ignores_tasks_without_a_title
2 failed in 0.12s

- test failed (1): [LOCAL_PATH] [LOCAL_PATH] [LOCAL_PATH]
Traceback (most recent call last):
  File "[LOCAL_PATH]", line 20, in <module>
    main()
    ~~~~^^
  File "[LOCAL_PATH]", line 13, in main
    assert [item["id"] for item in search_tasks(tasks, "api")] == [1, 2]
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError


## 运行产物

- `taskboard-group-by-status` agent_output: `cases/taskboard-group-by-status/artifacts/agent-output.txt`
- `taskboard-group-by-status` patch: `cases/taskboard-group-by-status/artifacts/patch.diff`
- `taskboard-group-by-status` tests: `cases/taskboard-group-by-status/artifacts/tests.log`
- `taskboard-group-by-status` trace: `cases/taskboard-group-by-status/traces/agent-events.jsonl`
- `taskboard-priority-aliases` agent_output: `cases/taskboard-priority-aliases/artifacts/agent-output.txt`
- `taskboard-priority-aliases` patch: `cases/taskboard-priority-aliases/artifacts/patch.diff`
- `taskboard-priority-aliases` tests: `cases/taskboard-priority-aliases/artifacts/tests.log`
- `taskboard-priority-aliases` trace: `cases/taskboard-priority-aliases/traces/agent-events.jsonl`
- `taskboard-select-tasks` agent_output: `cases/taskboard-select-tasks/artifacts/agent-output.txt`
- `taskboard-select-tasks` patch: `cases/taskboard-select-tasks/artifacts/patch.diff`
- `taskboard-select-tasks` tests: `cases/taskboard-select-tasks/artifacts/tests.log`
- `taskboard-select-tasks` trace: `cases/taskboard-select-tasks/traces/agent-events.jsonl`
- `taskboard-status-filter` agent_output: `cases/taskboard-status-filter/artifacts/agent-output.txt`
- `taskboard-status-filter` patch: `cases/taskboard-status-filter/artifacts/patch.diff`
- `taskboard-status-filter` tests: `cases/taskboard-status-filter/artifacts/tests.log`
- `taskboard-status-filter` trace: `cases/taskboard-status-filter/traces/agent-events.jsonl`
- `taskboard-title-search` agent_output: `cases/taskboard-title-search/artifacts/agent-output.txt`
- `taskboard-title-search` patch: `cases/taskboard-title-search/artifacts/patch.diff`
- `taskboard-title-search` tests: `cases/taskboard-title-search/artifacts/tests.log`
- `taskboard-title-search` trace: `cases/taskboard-title-search/traces/agent-events.jsonl`
