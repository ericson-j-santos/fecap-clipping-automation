from __future__ import annotations

from hashlib import sha256
import io
import zipfile
from xml.etree import ElementTree as ET

from src.excel_homologation import (
    CONTRACT_VERSION,
    MONTH_HEADERS,
    MONTHS,
    REVIEW_HEADERS,
    build_workbook_bytes,
)


def sample_payload() -> dict:
    return {
        "format": 1,
        "mode": "one_shot",
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "production_enabled": False,
        "items": [
            {
                "external_id": "1",
                "title": "Professor FECAP comenta economia",
                "url": "https://example.com/a?utm_source=x",
                "source": "Viva",
                "published_at": "2026-09-14T08:54:00",
                "text": "Ahmed El Khatib é professor da FECAP.",
            },
            {
                "external_id": "2",
                "title": "<B>FECAP</B> promove evento",
                "url": "https://example.com/b",
                "source": "Fecap",
                "published_at": "2026-09-13T00:00:00",
                "text": "A FECAP promove evento institucional.",
            },
            {
                "external_id": "3",
                "title": "Executivo é destaque",
                "url": "https://example.com/c",
                "source": "Site",
                "published_at": "2026-09-12T00:00:00",
                "text": "Executivo graduado em Administração pela FECAP.",
            },
        ],
    }


def main() -> int:
    people = {"Ahmed El Khatib": "Graduação"}
    first, evidence = build_workbook_bytes(sample_payload(), people, {})
    second, evidence2 = build_workbook_bytes(sample_payload(), people, {})

    assert first == second
    assert evidence == evidence2
    assert evidence["contract"] == f"excel-homologation/{CONTRACT_VERSION}"
    assert evidence["counts"] == {"items": 3, "include": 1, "review": 1, "exclude": 1}
    assert evidence["workbook_sha256"] == sha256(first).hexdigest()
    assert evidence["external_destination_enabled"] is False
    assert evidence["tiers_configured"] is False

    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = set(archive.namelist())
        assert "xl/workbook.xml" in names
        assert len([name for name in names if name.startswith("xl/worksheets/sheet")]) == 14
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        for month in MONTHS:
            assert f'name="{month}"' in workbook_xml
        assert 'name="Revisao"' in workbook_xml
        assert 'name="Controle"' in workbook_xml

        september = archive.read("xl/worksheets/sheet9.xml").decode("utf-8")
        for header in MONTH_HEADERS:
            assert header in september
        assert "Ahmed El Khatib" in september
        assert "Graduação" in september
        assert "utm_source" not in september

        review = archive.read("xl/worksheets/sheet13.xml").decode("utf-8")
        for header in REVIEW_HEADERS:
            assert header in review
        assert "FECAP promove evento" in review
        assert "A FECAP promove evento institucional" not in review

        for name in names:
            if name.endswith(".xml") or name.endswith(".rels"):
                ET.fromstring(archive.read(name))

    print("test_excel_homologation: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
