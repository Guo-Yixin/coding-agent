from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from agent.core.settings import CHECKPOINT_DB_PATH, LANGGRAPH_STORE_DB_PATH, POSTGRES_DSN, STORE_DB_PATH
from agent.store.migration import migrate_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate CODING SQLite data to PostgreSQL")
    parser.add_argument("--business-db", type=Path, default=STORE_DB_PATH)
    parser.add_argument("--checkpoint-db", type=Path, default=CHECKPOINT_DB_PATH)
    parser.add_argument("--store-db", type=Path, default=LANGGRAPH_STORE_DB_PATH)
    parser.add_argument("--dsn", default=POSTGRES_DSN)
    parser.add_argument("--report", type=Path, default=Path("data/migration-report.json"))
    args = parser.parse_args()
    if not args.dsn:
        parser.error("POSTGRES_DSN is required")
    report = migrate_all(
        business_db=args.business_db,
        checkpoint_db=args.checkpoint_db,
        store_db=args.store_db,
        dsn=args.dsn,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    load_dotenv()
    raise SystemExit(main())
