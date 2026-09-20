from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONTRACT = "github-main-governance/1.0.0"


class MainGovernanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class BranchSnapshot:
    repository: str
    branch: str
    sha: str
    protected: bool


def parse_branch_snapshot(payload: dict[str, Any], repository: str, branch: str) -> BranchSnapshot:
    if not isinstance(payload, dict):
        raise MainGovernanceError("branch_payload_invalid")
    commit = payload.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    protected = payload.get("protected")
    if not isinstance(sha, str) or len(sha) != 40:
        raise MainGovernanceError("branch_sha_invalid")
    if not isinstance(protected, bool):
        raise MainGovernanceError("branch_protected_invalid")
    if not repository or not branch:
        raise MainGovernanceError("branch_identity_invalid")
    return BranchSnapshot(repository=repository, branch=branch, sha=sha, protected=protected)


def build_evidence(snapshot: BranchSnapshot) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "status": "PASS" if snapshot.protected else "BLOCKED",
        "repository": snapshot.repository,
        "branch": snapshot.branch,
        "sha": snapshot.sha,
        "protected": snapshot.protected,
        "criterion": "branch_protected_flag",
        "issue_completion_proven": False,
        "admin_changes_attempted": False,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "tokens_persisted": False,
        "secrets_captured": False,
    }


def evaluate_branch_payload(payload: dict[str, Any], repository: str, branch: str) -> dict[str, Any]:
    return build_evidence(parse_branch_snapshot(payload, repository, branch))
