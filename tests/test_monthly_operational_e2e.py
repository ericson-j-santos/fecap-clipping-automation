from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import build_workbook_bytes

SCRIPT = ROOT / "scripts" / "run_monthly_operational_e2e.py"


def collector_for(title: str, url: str, source: str, person: str) -> dict:
    return {
        "format": 1,
        "mode": "one_shot",
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "items": [{
            "external_id": url,
            "title": title,
            "url": url,
            "source": source,
            "published_at": "2026-08-31T00:00:00",
            "text": f"O professor {person}, da FECAP, comenta o tema.",
        }],
    }


def test_check_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "positive_case_required=true" in completed.stdout
    assert "replay_required=true" in completed.stdout
    assert "production_enabled=false" in completed.stdout


def test_requires_one_shot() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--start-date",
            "2026-08-01",
            "--end-date",
            "2026-08-31",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 50
    assert '"phase": "authorization"' in completed.stdout


def test_monthly_operational_replay_with_precollected_fixture() -> None:
    people = {
        "Rosely Schwartz": "Extensão",
        "Ahmed El Khatib": "Graduação",
    }
    rules = json.loads(
        (ROOT / "config" / "video_enrichment.json").read_text(encoding="utf-8")
    )
    base_collector = collector_for(
        "Nota fiscal: condomínio terá de emitir? - Direcional Condomínios",
        "https://example.invalid/direcional",
        "DIRECIONAL CONDOMÍNIOS",
        "Rosely Schwartz",
    )
    base_workbook, _ = build_workbook_bytes(
        base_collector, people, {}, enrichment_rules=rules
    )
    next_collector = collector_for(
        "Déficit nominal das contas públicas brasileiras consolidadas alcançou R$ 1,2 trilhão",
        "https://mercadocomum.com/deficit-nominal-das-contas-publicas-brasileiras",
        "Mercado Comum",
        "Ahmed El Khatib",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        source = temp / "Clipping_2026.xlsx"
        collected = temp / "collector.json"
        output = temp / "Clipping_2026.validado.xlsx"
        replay = temp / "Clipping_2026.replay.xlsx"
        append_evidence = temp / "append.json"
        replay_evidence = temp / "replay.json"
        e2e_evidence = temp / "e2e.json"

        source.write_bytes(base_workbook)
        collected.write_text(
            json.dumps(next_collector, ensure_ascii=False),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--once",
                "--skip-collect",
                "--start-date",
                "2026-08-01",
                "--end-date",
                "2026-08-31",
                "--workbook",
                str(source),
                "--collector",
                str(collected),
                "--output",
                str(output),
                "--replay-output",
                str(replay),
                "--append-evidence",
                str(append_evidence),
                "--replay-evidence",
                str(replay_evidence),
                "--evidence",
                str(e2e_evidence),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        evidence = json.loads(e2e_evidence.read_text(encoding="utf-8"))
        assert evidence["status"] == "PASS"
        assert evidence["collector_skipped"] is True
        assert evidence["live_knewin_validated"] is False
        assert evidence["appended_count"] == 1
        assert evidence["replay_no_op"] is True
        assert evidence["replay_duplicate_count"] >= 1
        assert output.read_bytes() == replay.read_bytes()


def test_invalid_window_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        evidence = temp / "e2e.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--once",
                "--start-date",
                "2026-09-01",
                "--end-date",
                "2026-08-31",
                "--evidence",
                str(evidence),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 50
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        assert payload["phase"] == "date_window"
