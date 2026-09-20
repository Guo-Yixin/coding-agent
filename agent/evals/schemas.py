from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvalCase:
    case_id: str
    prompt: str
    repo_path: str = "."
    base_ref: str | None = None
    gold_files: list[str] = field(default_factory=list)
    gold_symbols: list[str] = field(default_factory=list)
    target_tests: list[list[str] | str] = field(default_factory=list)
    regression_tests: list[list[str] | str] = field(default_factory=list)
    agent_command: list[str] | None = None
    fake_command: list[str] | None = None
    requires_patch: bool = False
    timeout_seconds: int = 600
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalCase":
        return cls(
            case_id=str(data["case_id"]),
            prompt=str(data.get("prompt", "")),
            repo_path=str(data.get("repo_path", ".")),
            base_ref=data.get("base_ref"),
            gold_files=[str(item) for item in data.get("gold_files", [])],
            gold_symbols=[str(item) for item in data.get("gold_symbols", [])],
            target_tests=list(data.get("target_tests", [])),
            regression_tests=list(data.get("regression_tests", [])),
            agent_command=list(data["agent_command"]) if data.get("agent_command") else None,
            fake_command=list(data["fake_command"]) if data.get("fake_command") else None,
            requires_patch=bool(data.get("requires_patch", False)),
            timeout_seconds=int(data.get("timeout_seconds", 600)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalCaseResult:
    case_id: str
    status: str
    agent_exit_code: int | None
    patch_apply: bool
    target_tests_passed: bool | None
    regression_tests_passed: bool | None
    retrieval_hit_at_k: float | None
    tool_recovery_rate: float | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    agent_latency_ms: int
    target_test_latency_ms: int
    regression_test_latency_ms: int
    changed_files: list[str] = field(default_factory=list)
    patch: str = ""
    errors: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReport:
    report_id: str
    mode: str
    repository: str
    cases: list[EvalCaseResult]
    config: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "mode": self.mode,
            "repository": self.repository,
            "config": self.config,
            "created_at": self.created_at,
            "summary": {
                "case_count": len(self.cases),
                "passed_count": sum(case.status == "passed" for case in self.cases),
                "patch_apply_rate": _average([float(case.patch_apply) for case in self.cases]),
                "target_test_pass_rate": _average([case.target_tests_passed for case in self.cases]),
                "regression_test_pass_rate": _average([case.regression_tests_passed for case in self.cases]),
                "retrieval_hit_at_k": _average([case.retrieval_hit_at_k for case in self.cases]),
                "tool_recovery_rate": _average([case.tool_recovery_rate for case in self.cases]),
                "total_tokens": sum(case.total_tokens for case in self.cases),
                "total_latency_ms": sum(case.agent_latency_ms for case in self.cases),
            },
            "cases": [case.to_dict() for case in self.cases],
        }


def _average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None
