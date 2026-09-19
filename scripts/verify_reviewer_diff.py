from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.reviewer_diff import parse_unified_diff, validate_finding_location


SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
index 1111111..2222222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,4 +1,6 @@
 from fastapi import FastAPI

 app = FastAPI()
+SECRET = "demo"
+
 @app.get("/health")
 def health():
"""


def main() -> None:
    summary = parse_unified_diff(SAMPLE_DIFF, base="master", head="feature/demo")
    assert summary.changed_file_paths == ("app/main.py",)
    assert summary.changed_lines_for("app/main.py") == {4, 5}

    ok, message = validate_finding_location(summary, file="app/main.py", line=4)
    assert ok, message

    ok, message = validate_finding_location(summary, file="app/main.py", line=20)
    assert not ok, message

    ok, message = validate_finding_location(summary, file="app/other.py", line=3)
    assert not ok, message

    print("reviewer diff verification passed")


if __name__ == "__main__":
    main()
