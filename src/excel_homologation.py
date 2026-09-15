from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html import escape
import io
import re
from pathlib import Path
import zipfile

from src.clipping import Candidate, Decision, classify, idempotency_key

CONTRACT_VERSION = "1.0.0"
MONTHS = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
MONTH_HEADERS = (
    "DATA", "VEÍCULO", "TIER", "MÍDIA", "ORIGEM",
    "ASSUNTO", "FONTE", "UN.NEG", "LINK",
)
REVIEW_HEADERS = ("DATA", "VEÍCULO", "TÍTULO", "MOTIVO", "LINK", "IDEMPOTENCY_KEY")
CONTROL_HEADERS = ("Indicador", "Valor")
_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
_TAG_RE = re.compile(r"<[^>]+>")


class ExcelHomologationError(ValueError):
    pass


@dataclass(frozen=True)
class ClassifiedItem:
    candidate: Candidate
    decision: Decision
    key: str


def _clean_text(value: object) -> str:
    return _TAG_RE.sub("", str(value or "").strip())


def _required_text(item: dict, key: str) -> str:
    value = _clean_text(item.get(key))
    if not value:
        raise ExcelHomologationError(f"item sem campo obrigatório: {key}")
    return value


def _parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExcelHomologationError("published_at inválido") from exc


def validate_collector_output(payload: object) -> list[Candidate]:
    if not isinstance(payload, dict) or payload.get("format") != 1:
        raise ExcelHomologationError("saída do coletor inválida")
    if payload.get("credentials_persisted") is not False:
        raise ExcelHomologationError("saída não garante credentials_persisted=false")
    if payload.get("raw_response_persisted") is not False:
        raise ExcelHomologationError("saída não garante raw_response_persisted=false")
    if payload.get("production_enabled") is not False:
        raise ExcelHomologationError("saída não preserva production_enabled=false")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ExcelHomologationError("saída sem items[]")

    candidates: list[Candidate] = []
    for item in items:
        if not isinstance(item, dict):
            raise ExcelHomologationError("item do coletor não é objeto")
        candidates.append(
            Candidate(
                title=_required_text(item, "title"),
                url=_required_text(item, "url"),
                source=_required_text(item, "source"),
                published_at=_required_text(item, "published_at"),
                text=str(item.get("text") or "").strip(),
            )
        )
    return candidates


def classify_items(
    candidates: list[Candidate],
    people: dict[str, str],
    tiers: dict[str, int] | None = None,
) -> list[ClassifiedItem]:
    tiers = tiers or {}
    return [
        ClassifiedItem(candidate, classify(candidate, people, tiers), idempotency_key(candidate))
        for candidate in candidates
    ]


def build_model(items: list[ClassifiedItem]) -> dict:
    month_rows = {name: [] for name in MONTHS}
    review_rows: list[list[object]] = []
    excluded = 0

    for item in items:
        candidate, decision = item.candidate, item.decision
        dt = _parse_date(candidate.published_at)
        if decision.status == "include":
            month_rows[MONTHS[dt.month - 1]].append([
                dt.strftime("%d/%m/%Y"), candidate.source, decision.tier,
                None, None, None, decision.person, decision.business_unit, candidate.url,
            ])
        elif decision.status == "review":
            review_rows.append([
                dt.strftime("%d/%m/%Y"), candidate.source, candidate.title,
                decision.reason, candidate.url, item.key,
            ])
        elif decision.status == "exclude":
            excluded += 1
        else:
            raise ExcelHomologationError(f"status de classificação inválido: {decision.status}")

    for rows in month_rows.values():
        rows.sort(key=lambda row: (row[0], str(row[1]), str(row[8])))
    review_rows.sort(key=lambda row: (row[0], str(row[1]), str(row[4])))
    included = sum(len(rows) for rows in month_rows.values())
    return {
        "contract_version": CONTRACT_VERSION,
        "month_rows": month_rows,
        "review_rows": review_rows,
        "counts": {
            "items": len(items), "include": included,
            "review": len(review_rows), "exclude": excluded,
        },
    }


def _col_name(index: int) -> str:
    result = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _cell_xml(row_index: int, col_index: int, value: object, style: int = 0) -> str:
    ref = f"{_col_name(col_index)}{row_index}"
    style_attr = f' s="{style}"' if style else ""
    if value is None:
        return f'<c r="{ref}"{style_attr}/>'
    text = escape(str(value), quote=False)
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(headers: tuple[str, ...], rows: list[list[object]], widths: tuple[float, ...]) -> str:
    max_row = max(1, len(rows) + 1)
    max_col = len(headers)
    cols = "".join(
        f'<col min="{i+1}" max="{i+1}" width="{width}" customWidth="1"/>'
        for i, width in enumerate(widths)
    )
    row_xml = []
    row_xml.append('<row r="1" ht="20" customHeight="1">' + "".join(
        _cell_xml(1, i, value, 1) for i, value in enumerate(headers)
    ) + '</row>')
    for r_idx, row in enumerate(rows, start=2):
        row_xml.append(f'<row r="{r_idx}">' + "".join(
            _cell_xml(r_idx, c_idx, value) for c_idx, value in enumerate(row)
        ) + '</row>')
    dimension = f"A1:{_col_name(max_col - 1)}{max_row}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>'
        f'<cols>{cols}</cols><sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="{dimension}"/></worksheet>'
    )


def _control_rows(model: dict) -> list[list[object]]:
    counts = model["counts"]
    return [
        ["Contrato", f"excel-homologation/{CONTRACT_VERSION}"],
        ["Itens classificados", counts["items"]],
        ["Publicados nas abas mensais", counts["include"]],
        ["Fila de revisão", counts["review"]],
        ["Excluídos", counts["exclude"]],
        ["TIER", "Em branco quando não houver configuração evidenciada"],
        ["MÍDIA", "Em branco; não inferir"],
        ["ORIGEM", "Em branco; regra ainda não evidenciada"],
        ["ASSUNTO", "Em branco; curadoria não automatizada"],
        ["Destino SharePoint", "Desabilitado até site/biblioteca/caminho serem evidenciados"],
        ["Produção/agendamento", "Desabilitados"],
    ]


def _package_bytes(model: dict) -> bytes:
    sheet_names = list(MONTHS) + ["Revisao", "Controle"]
    sheets = []
    month_widths = (13, 28, 9, 12, 15, 30, 24, 18, 60)
    for month in MONTHS:
        sheets.append((MONTH_HEADERS, model["month_rows"][month], month_widths))
    sheets.append((REVIEW_HEADERS, model["review_rows"], (13, 28, 48, 46, 60, 68)))
    sheets.append((CONTROL_HEADERS, _control_rows(model), (32, 78)))

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for idx in range(1, len(sheets) + 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append('</Types>')

    workbook_sheets = "".join(
        f'<sheet name="{escape(name, quote=True)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(sheet_names, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{workbook_sheets}</sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>'
    )
    workbook_rels = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ]
    for idx in range(1, len(sheets) + 1):
        workbook_rels.append(
            f'<Relationship Id="rId{idx}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{idx}.xml"/>'
        )
    workbook_rels.append(
        f'<Relationship Id="rId{len(sheets)+1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    workbook_rels.append('</Relationships>')

    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF70AD47"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment vertical="top" wrapText="1"/></xf><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" '
        'applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        '</Relationships>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>FECAP Clipping - Homologação</dc:title>'
        '<dc:creator>fecap-clipping-automation</dc:creator><cp:lastModifiedBy>fecap-clipping-automation</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-01T00:00:00Z</dcterms:modified></cp:coreProperties>'
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>fecap-clipping-automation</Application></Properties>'
    )

    files = {
        "[Content_Types].xml": "".join(content_types), "_rels/.rels": root_rels,
        "docProps/core.xml": core, "docProps/app.xml": app,
        "xl/workbook.xml": workbook, "xl/_rels/workbook.xml.rels": "".join(workbook_rels),
        "xl/styles.xml": styles,
    }
    for idx, (headers, rows, widths) in enumerate(sheets, start=1):
        files[f"xl/worksheets/sheet{idx}.xml"] = _sheet_xml(headers, rows, widths)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name].encode("utf-8"))
    return buffer.getvalue()


def build_workbook_bytes(
    collector_payload: object,
    people: dict[str, str],
    tiers: dict[str, int] | None = None,
) -> tuple[bytes, dict]:
    candidates = validate_collector_output(collector_payload)
    classified = classify_items(candidates, people, tiers)
    model = build_model(classified)
    workbook = _package_bytes(model)
    evidence = {
        "status": "PASS",
        "contract": f"excel-homologation/{CONTRACT_VERSION}",
        "counts": model["counts"],
        "workbook_sha256": sha256(workbook).hexdigest(),
        "idempotency_key_set_sha256": sha256(
            "\n".join(sorted(item.key for item in classified)).encode("utf-8")
        ).hexdigest(),
        "tiers_configured": bool(tiers),
        "external_destination_enabled": False,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "raw_response_persisted": False,
        "secrets_captured": False,
    }
    return workbook, evidence


def write_workbook(
    collector_payload: object,
    people: dict[str, str],
    output: Path,
    tiers: dict[str, int] | None = None,
) -> dict:
    workbook, evidence = build_workbook_bytes(collector_payload, people, tiers)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(workbook)
    evidence["output_path"] = str(output)
    return evidence
