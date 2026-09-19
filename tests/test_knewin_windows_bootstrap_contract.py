from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "knewin-session-capture.ps1"


def main() -> int:
    text = SCRIPT.read_text(encoding="utf-8")
    required = (
        "# Version: 5.0.0",
        "[switch]$Offline",
        "[switch]$SkipInstall",
        "knewin-session-bootstrap.jsonl",
        '"venv"',
        '"ensurepip"',
        '"--no-index"',
        '"--find-links"',
        "Python.Python.3.12",
        "probe_knewin_session.py",
        "KNEWIN_AUTH_EVIDENCE",
        "secrets_captured",
    )
    for token in required:
        assert token in text, f"contrato ausente: {token}"

    assert "pip install playwright" not in text
    assert "Password=" not in text
    assert "TOKEN=" not in text
    print("test_knewin_windows_bootstrap_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
