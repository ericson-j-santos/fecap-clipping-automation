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

    config_raw = (ROOT / "scripts" / "configure_fecap_main_protection_risk3.py").read_text(encoding="utf-8")
    runner_raw = (ROOT / "scripts" / "run_fecap_main_protection_local.py").read_text(encoding="utf-8")

    assert 'ACTION_ID = "fecap.main-protection.dev"' in config_raw
    assert 'SCOPE = "repo://ericson-j-santos/fecap-clipping-automation/branch/main"' in config_raw
    assert 'EVIDENCE_PATH = "evidence/private/main-protection-risk3.json"' in config_raw
    assert "--token" not in config_raw
    assert "--secret" not in config_raw

    assert 'TARGET_REPOSITORY = "ericson-j-santos/fecap-clipping-automation"' in runner_raw
    assert 'TARGET_BRANCH = "main"' in runner_raw
    assert 'RULESET_NAME = "main-protection"' in runner_raw
    assert 'EXPECTED_TARGET_SHA = "ad154563e9843ce88810e7826f6547f4da889775"' in runner_raw
    assert 'VALIDATED_SOURCE_SHA = "9d3d6afbd0f147057a21a7c93927b34ec2a7aa48"' in runner_raw
    assert 'API_VERSION = "2022-11-28"' in runner_raw
    assert 'REQUIRED_CHECKS = ("tests",)' in runner_raw
    assert 'env.pop("GH_TOKEN", None)' in runner_raw
    assert 'env.pop("GITHUB_TOKEN", None)' in runner_raw
    assert '"~DEFAULT_BRANCH"' in runner_raw
    assert '{"type": "deletion"}' in runner_raw
    assert '{"type": "non_fast_forward"}' in runner_raw
    assert '{"type": "required_linear_history"}' in runner_raw
    assert '"strict_required_status_checks_policy": True' in runner_raw
    assert '"bypass_actors": []' in runner_raw
    assert '"target_sha_changed"' in runner_raw
    assert '"validated_source_not_parent_of_target"' in runner_raw
    assert '"required_checks_not_green"' in runner_raw
    assert '"branch_not_protected_after_write"' in runner_raw
    assert '"ruleset_readback_mismatch"' in runner_raw
    assert "--repository" not in runner_raw
    assert "--branch" not in runner_raw
    assert "--ruleset-name" not in runner_raw
    assert "--required-check" not in runner_raw

    print("GITHUB_GOVERNANCE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
