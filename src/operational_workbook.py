from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import io
import posixpath
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from src.clipping import canonical_url
from src.excel_homologation import MONTHS, MONTH_HEADERS

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": REL_NS}
ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)

EXPECTED_HEADER_KEYS = (
    "data", "veiculo", "tier", "midia", "origem",
    "assunto", "fonte", "unneg", "link",
)


class OperationalWorkbookError(ValueError):
    pass


@dataclass(frozen=True)
class AppendResult:
    workbook: bytes
    evidence: dict


def _digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _header_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _col_index(cell_ref: str) -> int:
    match = re.match(r"^([A-Z]+)", str(cell_ref or "").upper())
    if not match:
        raise OperationalWorkbookError(f"referência de célula inválida: {cell_ref}")
    value = 0
    for char in match.group(1):
        value = value * 26 + (ord(char) - 64)
    return value


def _col_name(index: int) -> str:
    if index < 1:
        raise OperationalWorkbookError("índice de coluna inválido")
    result = ""
    value = index
    while value:
        value, rem = divmod(value - 1, 26)
        result = chr(65 + rem) + result
    return result


def _shared_strings(files: dict[str, bytes]) -> list[str]:
    raw = files.get("xl/sharedStrings.xml")
    if raw is None:
        return []
    root = ET.fromstring(raw)
    result = []
    for item in root.findall(f"{{{MAIN_NS}}}si"):
        result.append("".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")))
    return result


def _cell_text(cell: ET.Element | None, shared: list[str]) -> str:
    if cell is None:
        return ""
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
    value = cell.find(f"{{{MAIN_NS}}}v")
    raw = "" if value is None or value.text is None else value.text
    if cell_type == "s" and raw:
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            raise OperationalWorkbookError("shared string inválida")
    if cell_type == "str":
        return raw
    formula = cell.find(f"{{{MAIN_NS}}}f")
    if formula is not None and not raw:
        return ""
    return raw


def _row_cells(row: ET.Element) -> dict[int, ET.Element]:
    result: dict[int, ET.Element] = {}
    for cell in row.findall(f"{{{MAIN_NS}}}c"):
        result[_col_index(cell.get("r", ""))] = cell
    return result


def _find_header_row(sheet_root: ET.Element, shared: list[str]) -> tuple[int, ET.Element]:
    sheet_data = sheet_root.find(f"{{{MAIN_NS}}}sheetData")
    if sheet_data is None:
        raise OperationalWorkbookError("planilha sem sheetData")
    for row in list(sheet_data)[:30]:
        cells = _row_cells(row)
        keys = tuple(_header_key(_cell_text(cells.get(index), shared)) for index in range(1, 10))
        if keys == EXPECTED_HEADER_KEYS:
            return int(row.get("r", "0")), row
    raise OperationalWorkbookError(
        "cabeçalho do fluxo em vídeo não encontrado: " + " | ".join(MONTH_HEADERS)
    )


def _workbook_sheets(files: dict[str, bytes]) -> dict[str, str]:
    workbook = ET.fromstring(files["xl/workbook.xml"])
    rels = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
    }
    result: dict[str, str] = {}
    for sheet in workbook.findall(".//m:sheet", NS):
        name = sheet.get("name")
        rid = sheet.get(f"{{{REL_NS}}}id")
        target = targets.get(rid)
        if not name or not target:
            continue
        if target.startswith("/"):
            path = target.lstrip("/")
        else:
            path = posixpath.normpath(posixpath.join("xl", target))
        result[name] = path
    return result


def _rels_path(sheet_path: str) -> str:
    directory, filename = posixpath.split(sheet_path)
    return posixpath.join(directory, "_rels", filename + ".rels")


def _sheet_hyperlinks(files: dict[str, bytes], sheet_path: str, root: ET.Element) -> dict[str, str]:
    rel_path = _rels_path(sheet_path)
    raw_rels = files.get(rel_path)
    if raw_rels is None:
        return {}
    rels = ET.fromstring(raw_rels)
    target_by_id = {
        rel.get("Id"): rel.get("Target")
        for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship")
        if rel.get("TargetMode") == "External"
    }
    result: dict[str, str] = {}
    hyperlinks = root.find(f"{{{MAIN_NS}}}hyperlinks")
    if hyperlinks is None:
        return result
    for link in hyperlinks.findall(f"{{{MAIN_NS}}}hyperlink"):
        ref = link.get("ref")
        rid = link.get(f"{{{REL_NS}}}id")
        target = target_by_id.get(rid)
        if ref and target:
            result[ref] = target
    return result


def _canonical_or_raw(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return canonical_url(text)
    except ValueError:
        return text.casefold()


def _existing_links(
    files: dict[str, bytes],
    sheet_path: str,
    root: ET.Element,
    shared: list[str],
    header_row: int,
) -> set[str]:
    hyperlinks = _sheet_hyperlinks(files, sheet_path, root)
    sheet_data = root.find(f"{{{MAIN_NS}}}sheetData")
    result: set[str] = set()
    if sheet_data is None:
        return result
    for row in sheet_data.findall(f"{{{MAIN_NS}}}row"):
        row_num = int(row.get("r", "0"))
        if row_num <= header_row:
            continue
        cells = _row_cells(row)
        cell = cells.get(9)
        ref = "" if cell is None else cell.get("r", "")
        value = hyperlinks.get(ref) or _cell_text(cell, shared)
        normalized = _canonical_or_raw(value)
        if normalized:
            result.add(normalized)
    return result


def _style_template(sheet_root: ET.Element, header_row: int) -> tuple[dict[int, str], dict[str, str]]:
    sheet_data = sheet_root.find(f"{{{MAIN_NS}}}sheetData")
    if sheet_data is None:
        return {}, {}
    rows = [
        row for row in sheet_data.findall(f"{{{MAIN_NS}}}row")
        if int(row.get("r", "0")) > header_row
    ]
    if not rows:
        return {}, {}
    template = max(rows, key=lambda row: int(row.get("r", "0")))
    cells = _row_cells(template)
    styles = {
        col: cell.get("s")
        for col, cell in cells.items()
        if cell.get("s") is not None and 1 <= col <= 9
    }
    row_attrs = {
        key: value for key, value in template.attrib.items()
        if key not in {"r", "spans"}
    }
    return styles, row_attrs


def _inline_cell(ref: str, value: object, style: str | None) -> ET.Element:
    attrs = {"r": ref, "t": "inlineStr"}
    if style is not None:
        attrs["s"] = style
    cell = ET.Element(f"{{{MAIN_NS}}}c", attrs)
    inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
    text = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
    text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text.text = "" if value is None else str(value)
    return cell


def _next_relationship_id(rels: ET.Element) -> str:
    used: set[int] = set()
    for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship"):
        rid = str(rel.get("Id") or "")
        match = re.fullmatch(r"rId(\d+)", rid)
        if match:
            used.add(int(match.group(1)))
    candidate = 1
    while candidate in used:
        candidate += 1
    return f"rId{candidate}"


def _ensure_hyperlinks_node(root: ET.Element) -> ET.Element:
    existing = root.find(f"{{{MAIN_NS}}}hyperlinks")
    if existing is not None:
        return existing
    node = ET.Element(f"{{{MAIN_NS}}}hyperlinks")
    children = list(root)
    later = {
        "printOptions", "pageMargins", "pageSetup", "headerFooter",
        "rowBreaks", "colBreaks", "customProperties", "cellWatches",
        "ignoredErrors", "smartTags", "drawing", "legacyDrawing",
        "legacyDrawingHF", "picture", "oleObjects", "controls",
        "webPublishItems", "tableParts", "extLst",
    }
    index = len(children)
    for pos, child in enumerate(children):
        local = child.tag.rsplit("}", 1)[-1]
        if local in later:
            index = pos
            break
    root.insert(index, node)
    return node


def _append_hyperlink(
    files: dict[str, bytes],
    sheet_path: str,
    root: ET.Element,
    cell_ref: str,
    url: str,
) -> None:
    rel_path = _rels_path(sheet_path)
    raw = files.get(rel_path)
    if raw is None:
        rels = ET.Element(f"{{{PKG_REL_NS}}}Relationships")
    else:
        rels = ET.fromstring(raw)
    rid = _next_relationship_id(rels)
    rel = ET.SubElement(rels, f"{{{PKG_REL_NS}}}Relationship")
    rel.set("Id", rid)
    rel.set(
        "Type",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    )
    rel.set("Target", url)
    rel.set("TargetMode", "External")
    files[rel_path] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)

    hyperlinks = _ensure_hyperlinks_node(root)
    link = ET.SubElement(hyperlinks, f"{{{MAIN_NS}}}hyperlink")
    link.set("ref", cell_ref)
    link.set(f"{{{REL_NS}}}id", rid)


def _update_refs(files: dict[str, bytes], sheet_path: str, root: ET.Element, header_row: int, last_row: int) -> None:
    dimension = root.find(f"{{{MAIN_NS}}}dimension")
    if dimension is not None:
        current = dimension.get("ref", "A1:I1")
        start = current.split(":", 1)[0]
        dimension.set("ref", f"{start}:I{last_row}")

    auto_filter = root.find(f"{{{MAIN_NS}}}autoFilter")
    if auto_filter is not None:
        auto_filter.set("ref", f"A{header_row}:I{last_row}")

    rel_path = _rels_path(sheet_path)
    raw_rels = files.get(rel_path)
    if raw_rels is None:
        return
    rels = ET.fromstring(raw_rels)
    table_ids = {
        link.get(f"{{{REL_NS}}}id")
        for link in root.findall(f".//{{{MAIN_NS}}}tablePart")
    }
    for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship"):
        if rel.get("Id") not in table_ids:
            continue
        if not str(rel.get("Type") or "").endswith("/table"):
            continue
        target = rel.get("Target")
        if not target:
            continue
        if target.startswith("/"):
            table_path = target.lstrip("/")
        else:
            table_path = posixpath.normpath(
                posixpath.join(posixpath.dirname(sheet_path), target)
            )
        raw_table = files.get(table_path)
        if raw_table is None:
            continue
        table = ET.fromstring(raw_table)
        table.set("ref", f"A{header_row}:I{last_row}")
        table_filter = table.find(f"{{{MAIN_NS}}}autoFilter")
        if table_filter is not None:
            table_filter.set("ref", f"A{header_row}:I{last_row}")
        files[table_path] = ET.tostring(table, encoding="utf-8", xml_declaration=True)


def _serialize_zip(original: bytes, replacements: dict[str, bytes]) -> bytes:
    source = io.BytesIO(original)
    target = io.BytesIO()
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(target, "w") as zout:
        names = set()
        for info in zin.infolist():
            names.add(info.filename)
            payload = replacements.get(info.filename, zin.read(info.filename))
            zout.writestr(info, payload)
        for name, payload in replacements.items():
            if name in names:
                continue
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zout.writestr(info, payload)
    return target.getvalue()


def append_month_rows(workbook_bytes: bytes, month_rows: dict[str, list[list[object]]]) -> AppendResult:
    if not zipfile.is_zipfile(io.BytesIO(workbook_bytes)):
        raise OperationalWorkbookError("arquivo não é XLSX válido")

    with zipfile.ZipFile(io.BytesIO(workbook_bytes), "r") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    required = {"xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    if not required.issubset(files):
        raise OperationalWorkbookError("pacote XLSX incompleto")

    shared = _shared_strings(files)
    sheet_paths = _workbook_sheets(files)
    original_sha = _digest(workbook_bytes)
    existing_global: set[str] = set()
    prepared: dict[str, tuple[str, ET.Element, int, dict[int, str], dict[str, str]]] = {}

    for month in MONTHS:
        sheet_path = sheet_paths.get(month)
        if not sheet_path or sheet_path not in files:
            continue
        root = ET.fromstring(files[sheet_path])
        try:
            header_row, _ = _find_header_row(root, shared)
        except OperationalWorkbookError:
            if month_rows.get(month):
                raise
            continue
        existing_global.update(
            _existing_links(files, sheet_path, root, shared, header_row)
        )
        if month_rows.get(month):
            styles, row_attrs = _style_template(root, header_row)
            prepared[month] = (sheet_path, root, header_row, styles, row_attrs)

    for month, rows in month_rows.items():
        if not rows:
            continue
        if month not in MONTHS:
            raise OperationalWorkbookError(f"mês inválido: {month}")
        if month not in prepared:
            raise OperationalWorkbookError(f"aba mensal ausente ou incompatível: {month}")

    appended_by_month: dict[str, int] = {}
    duplicate_count = 0

    for month in MONTHS:
        rows = month_rows.get(month) or []
        if not rows:
            continue
        sheet_path, root, header_row, styles, row_attrs = prepared[month]
        sheet_data = root.find(f"{{{MAIN_NS}}}sheetData")
        if sheet_data is None:
            raise OperationalWorkbookError(f"aba sem sheetData: {month}")
        current_rows = [int(row.get("r", "0")) for row in sheet_data.findall(f"{{{MAIN_NS}}}row")]
        last_row = max(current_rows or [header_row])
        appended = 0

        for values in rows:
            if len(values) != 9:
                raise OperationalWorkbookError("linha operacional deve ter exatamente 9 colunas")
            link = _canonical_or_raw(str(values[8] or ""))
            if not link:
                raise OperationalWorkbookError("linha operacional sem LINK")
            if link in existing_global:
                duplicate_count += 1
                continue

            last_row += 1
            row = ET.Element(f"{{{MAIN_NS}}}row", {"r": str(last_row), **row_attrs})
            for col, value in enumerate(values, start=1):
                ref = f"{_col_name(col)}{last_row}"
                row.append(_inline_cell(ref, value, styles.get(col)))
            sheet_data.append(row)
            _append_hyperlink(files, sheet_path, root, f"I{last_row}", str(values[8]))
            existing_global.add(link)
            appended += 1

        if appended:
            _update_refs(files, sheet_path, root, header_row, last_row)
            files[sheet_path] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        appended_by_month[month] = appended

    appended_count = sum(appended_by_month.values())
    if appended_count == 0:
        output = workbook_bytes
    else:
        output = _serialize_zip(workbook_bytes, files)

    evidence = {
        "status": "PASS",
        "contract": "clipping-operational-append/1.0.0",
        "input_sha256": original_sha,
        "output_sha256": _digest(output),
        "appended_count": appended_count,
        "duplicate_count": duplicate_count,
        "appended_by_month": appended_by_month,
        "no_op": appended_count == 0,
        "scheduled": False,
        "production_enabled": False,
        "credentials_persisted": False,
        "tokens_persisted": False,
        "secrets_captured": False,
    }
    return AppendResult(output, evidence)
