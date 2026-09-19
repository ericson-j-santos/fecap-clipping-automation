from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.sharepoint_homologation import (
    TARGET_FOLDER,
    TARGET_SITE_TITLE,
    SharePointHomologationError,
    build_evidence,
    choose_existing_site,
    deterministic_filename,
    remote_file_decision,
    site_candidate,
    workbook_sha256,
)
from scripts.publish_sharepoint_homologation import validate_organization_domain


def main() -> int:
    digest = workbook_sha256(b"workbook")
    name = deterministic_filename(digest)
    assert name.startswith("fecap-clipping-homologacao-")
    assert name.endswith(".xlsx")

    weak = site_candidate("Marketing", "https://tenant.sharepoint.com/sites/Marketing")
    strong = site_candidate("FECAP Comunicação", "https://tenant.sharepoint.com/sites/FECAPComunicacao")
    exact = site_candidate("FECAP Clipping Homologacao", "https://tenant.sharepoint.com/sites/FECAPClippingHomologacao")
    assert weak and strong and exact
    assert choose_existing_site([weak, strong, exact]) == exact

    tied_a = site_candidate("FECAP A", "https://tenant.sharepoint.com/sites/FECAPA")
    tied_b = site_candidate("FECAP B", "https://tenant.sharepoint.com/sites/FECAPB")
    assert tied_a and tied_b
    assert choose_existing_site([tied_a, tied_b]) is None

    assert remote_file_decision([], name) == "upload"
    assert remote_file_decision([name], name) == "already_present"
    try:
        remote_file_decision([name, name], name)
    except SharePointHomologationError:
        pass
    else:
        raise AssertionError("duplicidade remota deveria bloquear")

    evidence = build_evidence(
        workbook_digest=digest,
        site_title=TARGET_SITE_TITLE,
        site_url="https://tenant.sharepoint.com/sites/FECAPClippingHomologacao",
        library_name="Documents",
        folder_name=TARGET_FOLDER,
        file_name=name,
        action="already_present",
        existing_site_reused=False,
        site_created=True,
    )
    assert evidence["status"] == "PASS"
    assert evidence["mode"] == "one_shot"
    assert evidence["duplicate_prevented"] is True
    assert evidence["external_destination_enabled"] is True
    assert evidence["scheduled"] is False
    assert evidence["production_enabled"] is False
    assert evidence["credentials_persisted"] is False
    assert evidence["tokens_persisted"] is False

    assert validate_organization_domain("TIERI659.ONMICROSOFT.COM") == "tieri659.onmicrosoft.com"
    for invalid in ("", "user@example.com", "https://example.com", "example", "-bad.example.com"):
        try:
            validate_organization_domain(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"domínio inválido deveria bloquear: {invalid}")

    print("test_sharepoint_homologation: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
