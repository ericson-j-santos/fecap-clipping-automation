from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.excel_homologation import build_workbook_bytes
from src.operational_workbook import MAIN_NS, OperationalWorkbookError, append_month_rows


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


def august_xml(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        office_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        targets = {
            rel.get("Id"): rel.get("Target")
            for rel in rels.findall(f"{{{rel_ns}}}Relationship")
        }
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            if sheet.get("name") == "Agosto":
                target = targets[sheet.get(f"{{{office_rel}}}id")]
                return archive.read("xl/" + target).decode("utf-8")
    raise AssertionError("aba Agosto não encontrada")


def corrupt_august_header(payload: bytes) -> bytes:
    src = io.BytesIO(payload)
    dst = io.BytesIO()
    with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet8.xml":
                raw = raw.replace(b"ORIGEM", b"ORIGEMX", 1)
            zout.writestr(info, raw)
    return dst.getvalue()


def main() -> int:
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
    base, _ = build_workbook_bytes(
        base_collector, people, {}, enrichment_rules=rules
    )
    before_xml = august_xml(base)
    assert "Rosely Schwartz" in before_xml
    assert "Mercado Comum" not in before_xml

    new_row = [
        "31/08/2026",
        "Mercado Comum",
        2,
        "Online",
        "Proativo",
        "Déficit nominal das contas públicas brasileiras consolidadas alcançou R$ 1,2 trilhão",
        "Ahmed El Khatib",
        "Graduação",
        "https://mercadocomum.com/deficit-nominal-das-contas-publicas-brasileiras",
    ]
    first = append_month_rows(base, {"Agosto": [new_row]})
    assert first.evidence["status"] == "PASS"
    assert first.evidence["appended_count"] == 1
    assert first.evidence["duplicate_count"] == 0
    assert first.evidence["no_op"] is False
    after_xml = august_xml(first.workbook)
    assert "Rosely Schwartz" in after_xml
    assert "Mercado Comum" in after_xml
    assert "Proativo" in after_xml
    assert "Ahmed El Khatib" in after_xml

    replay = append_month_rows(first.workbook, {"Agosto": [new_row]})
    assert replay.evidence["appended_count"] == 0
    assert replay.evidence["duplicate_count"] == 1
    assert replay.evidence["no_op"] is True
    assert replay.workbook == first.workbook
    assert replay.evidence["input_sha256"] == replay.evidence["output_sha256"]

    duplicate_existing = [
        "31/08/2026", "DIRECIONAL CONDOMÍNIOS", 2, "Online", "Menção",
        "Nota fiscal: condomínio terá de emitir? - Direcional Condomínios",
        "Rosely Schwartz", "Extensão", "https://example.invalid/direcional",
    ]
    dup = append_month_rows(first.workbook, {"Agosto": [duplicate_existing]})
    assert dup.evidence["appended_count"] == 0
    assert dup.evidence["duplicate_count"] == 1

    try:
        append_month_rows(corrupt_august_header(base), {"Agosto": [new_row]})
    except OperationalWorkbookError:
        pass
    else:
        raise AssertionError("cabeçalho divergente deveria bloquear")

    print("test_operational_workbook: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
