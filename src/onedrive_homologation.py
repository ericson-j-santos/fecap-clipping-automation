from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from src.sharepoint_homologation import deterministic_filename

TARGET_FOLDER = "FECAP Clipping - Homologacao 2026"


class OneDriveHomologationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def publish_workbook(workbook: Path, destination_root: Path) -> dict:
    if not workbook.is_file():
        raise OneDriveHomologationError("workbook_missing")
    if not destination_root.is_dir():
        raise OneDriveHomologationError("destination_root_missing")

    digest = sha256_file(workbook)
    file_name = deterministic_filename(digest)
    folder = destination_root / TARGET_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / file_name

    action = "uploaded"
    if target.exists():
        if sha256_file(target) != digest:
            raise OneDriveHomologationError("hash_conflict")
        action = "already_present"
    else:
        shutil.copy2(workbook, target)

    if sha256_file(target) != digest:
        raise OneDriveHomologationError("verification_failed")

    return {
        "status": "PASS",
        "mode": "one_shot",
        "destination_type": "onedrive_sync",
        "folder": TARGET_FOLDER,
        "file_name": file_name,
        "workbook_sha256": digest,
        "action": action,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "secrets_captured": False,
    }
