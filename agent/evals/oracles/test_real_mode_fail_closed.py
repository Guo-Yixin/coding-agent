from __future__ import annotations

import sys
import tempfile
from pathlib import Path


def main() -> None:
    target_repo = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(target_repo))
    from agent.evals.runner import EvalRunner
    from agent.evals.schemas import EvalCase

    with tempfile.TemporaryDirectory(prefix="eval-oracle-") as temp:
        repository = Path(temp) / "source"
        repository.mkdir()
        (repository / "seed.txt").write_text("seed", encoding="utf-8")
        runner = EvalRunner(output_dir=Path(temp) / "out", mode="real")
        case = EvalCase(case_id="missing-agent", prompt="should fail closed")
        try:
            result = runner._run_case(case, repository=repository)
        except (RuntimeError, ValueError):
            return
        assert result.status != "passed", "real mode incorrectly passed without starting a real Agent"
        assert result.agent_exit_code is None, "missing Agent must not be represented by exit code zero"


if __name__ == "__main__":
    main()
