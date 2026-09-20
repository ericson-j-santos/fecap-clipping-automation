from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.github_governance import CONTRACT, MainGovernanceError, evaluate_branch_payload

DEFAULT_REPOSITORY = "ericson-j-santos/fecap-clipping-automation"
DEFAULT_BRANCH = "main"
DEFAULT_EVIDENCE = ROOT / "evidence" / "private" / "main-governance-audit.json"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_branch(repository: str, branch: str, timeout: int) -> dict:
    if "/" not in repository:
        raise MainGovernanceError("repository_invalid")
    owner, name = repository.split("/", 1)
    url = (
        "https://api.github.com/repos/"
        f"{quote(owner, safe='')}/{quote(name, safe='')}/branches/{quote(branch, safe='')}"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "fecap-clipping-governance-audit",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def blocked_evidence(repository: str, branch: str, phase: str, error_type: str) -> dict:
    return {
        "contract": CONTRACT,
        "status": "BLOCKED",
        "repository": repository,
        "branch": branch,
        "phase": phase,
        "error_type": error_type,
        "admin_changes_attempted": False,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "tokens_persisted": False,
        "secrets_captured": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita a proteção da branch main sem alterar configuração")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--check", action="store_true")
    ns = parser.parse_args()

    if ns.check:
        print(json.dumps({
            "contract": CONTRACT,
            "mode": "one_shot",
            "network_enabled": False,
            "admin_changes_attempted": False,
            "scheduled": False,
            "production_enabled": False,
        }, sort_keys=True))
        return 0

    try:
        payload = fetch_branch(ns.repository, ns.branch, ns.timeout)
        evidence = evaluate_branch_payload(payload, ns.repository, ns.branch)
    except (MainGovernanceError, HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        evidence = blocked_evidence(ns.repository, ns.branch, "api_fetch", type(exc).__name__)
        write_json(ns.evidence, evidence)
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 50

    write_json(ns.evidence, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 50


if __name__ == "__main__":
    raise SystemExit(main())
