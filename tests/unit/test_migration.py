from __future__ import annotations

from agent.store.migration import MigrationReport


def test_migration_report_is_json_serializable() -> None:
    report = MigrationReport(
        source="data",
        target_database="coding_agent_db",
        tables={"threads": 2},
        checkpoints=3,
        checkpoint_writes=1,
        store_items=4,
        skipped=["missing optional file"],
    )

    assert report.to_dict() == {
        "source": "data",
        "target_database": "coding_agent_db",
        "tables": {"threads": 2},
        "checkpoints": 3,
        "checkpoint_writes": 1,
        "store_items": 4,
        "skipped": ["missing optional file"],
    }
