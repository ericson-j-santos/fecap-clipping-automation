from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_homologation_pipeline.py"

spec = importlib.util.spec_from_file_location("homologation_pipeline", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_check_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "pipeline=knewin>excel>onedrive" in completed.stdout
    assert "sharepoint_in_critical_path=false" in completed.stdout
    assert "scheduled=false" in completed.stdout
    assert "production_enabled=false" in completed.stdout


def test_requires_one_shot_authorization() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--destination-root", str(ROOT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 50
    assert "one_shot_authorization_missing" in completed.stdout


def test_idempotency_requires_same_sha_and_already_present() -> None:
    first = {"status": "PASS", "action": "uploaded", "workbook_sha256": "abc"}
    second = {"status": "PASS", "action": "already_present", "workbook_sha256": "abc"}
    module.validate_idempotency(first, second)

    try:
        module.validate_idempotency(first, {**second, "workbook_sha256": "def"})
    except ValueError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("deveria bloquear SHA divergente")

    try:
        module.validate_idempotency(first, {**second, "action": "uploaded"})
    except ValueError as exc:
        assert "already_present" in str(exc)
    else:
        raise AssertionError("deveria exigir already_present na segunda execução")
