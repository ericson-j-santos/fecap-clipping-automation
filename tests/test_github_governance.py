from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.github_governance import MainGovernanceError, evaluate_branch_payload


def payload(protected: object) -> dict:
    return {
        "name": "main",
        "commit": {"sha": "a" * 40},
        "protected": protected,
    }


def main() -> int:
    blocked = evaluate_branch_payload(payload(False), "owner/repo", "main")
    assert blocked["status"] == "BLOCKED"
    assert blocked["protected"] is False
    assert blocked["issue_completion_proven"] is False
    assert blocked["admin_changes_attempted"] is False
    assert blocked["scheduled"] is False
    assert blocked["production_enabled"] is False

    passed = evaluate_branch_payload(payload(True), "owner/repo", "main")
    assert passed["status"] == "PASS"
    assert passed["protected"] is True
    assert passed["issue_completion_proven"] is False

    for invalid in (
        {"commit": {"sha": "short"}, "protected": True},
        {"commit": {"sha": "a" * 40}, "protected": "false"},
        [],
    ):
        try:
            evaluate_branch_payload(invalid, "owner/repo", "main")
        except MainGovernanceError:
            pass
        else:
            raise AssertionError("MainGovernanceError esperado")

    print("GITHUB_GOVERNANCE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
