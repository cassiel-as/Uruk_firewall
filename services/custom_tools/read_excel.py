"""
URUK auto-upgraded tool: read_excel
Installed: 2026-05-30T14:23:31.244364
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='read_excel',
    description='Read a local .xlsx workbook without executing macros and return JSON with workbook path, sheet names, selected sheet, rows, and optional header-based records.',
    args=[ArgSpec(**a) for a in [{'name': 'path', 'type': 'str', 'required': True, 'description': 'Local path to the .xlsx file.'}, {'name': 'sheet', 'type': 'str', 'required': False, 'description': 'Sheet name to read; defaults to the first sheet.'}, {'name': 'max_rows', 'type': 'int', 'required': False, 'description': 'Maximum rows to return, default 200 and capped at 5000.'}, {'name': 'header_row', 'type': 'bool', 'required': False, 'description': 'When true, also return records using the first returned row as headers.'}, {'name': 'include_empty', 'type': 'bool', 'required': False, 'description': 'When true, preserve empty rows in the returned row list.'}]],
    needs_visual=False,
    category='file',
)

def execute(args: dict) -> dict:
    try:
        import os
        import posixpath
        import zipfile
        import xml.etree.ElementTree as ET

        args = args or {}
        path = args.get("path")
        if not path:
            return {"ok": False, "error": "missing_path"}

        abs_path = os.path.abspath(os.path.expanduser(str(path)))
        if not os.path.isfile(abs_path):
            return {"ok": False, "error": "file_not_found", "path": abs_path}
        if not abs_path.lower().endswith(".xlsx"):
            return {"ok": False, "error": "unsupported_format", "message": "read_excel supports .xlsx files only", "path": abs_path}
        if os.path.getsize(abs_path) > 50 * 1024 * 1024:
            return {"ok": False, "error": "file_too_large", "message": "xlsx file exceeds 50 MB safety limit", "path": abs_path}

        def as_bool(value, default=False):
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

        max_rows = int(args.get("max_rows") or 200)
        if max_rows < 1:
            max_rows = 1
        if max_rows > 5000:
            max_rows = 5000
        sheet_arg = args.get("sheet")
        sheet_arg = str(sheet_arg) if sheet_arg not in (None, "") else None
        header_row = as_bool(args.get("header_row"), False)
        include_empty = as_bool(args.get("include_empty"), False)

        with zipfile.ZipFile(abs_path) as zf:
            names = set(zf.namelist())
            if "xl/workbook.xml" not in names:
                return {"ok": False, "error": "invalid_xlsx", "message": "workbook metadata missing"}

            def local_name(tag):
                return tag.rsplit("}", 1)[-1]

            def read_xml(part):
                if part not in names:
                    return None
                info = zf.getinfo(part)
                if info.file_size > 20 * 1024 * 1024:
                    raise ValueError("xlsx_part_too_large:" + part)
                return ET.fromstring(zf.read(part))

            shared = []
            if "xl/sharedStrings.xml" in names:
                shared_root = read_xml("xl/sharedStrings.xml")
                for item in shared_root.iter():
                    if local_name(item.tag) == "si":
                        pieces = []
                        for node in item.iter():
                            if local_name(node.tag) == "t" and node.text:
                                pieces.append(node.text)
                        shared.append("".join(pieces))

            rels = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rel_root = read_xml("xl/_rels/workbook.xml.rels")
                for rel in rel_root:
                    if local_name(rel.tag) == "Relationship":
                        rid = rel.attrib.get("Id")
                        target = rel.attrib.get("Target")
                        if rid and target:
                            target = target.replace("\\", "/")
                            if target.startswith("/"):
                                part = target.lstrip("/")
                            else:
                                part = posixpath.normpath(posixpath.join("xl", target))
                            rels[rid] = part

            workbook_root = read_xml("xl/workbook.xml")
            sheets = []
            rel_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            for node in workbook_root.iter():
                if local_name(node.tag) == "sheet":
                    name = node.attrib.get("name", "")
                    rid = node.attrib.get(rel_key) or node.attrib.get("r:id")
                    part = rels.get(rid)
                    if name and part:
                        sheets.append({"name": name, "part": part})

            if not sheets:
                return {"ok": False, "error": "no_sheets"}

            chosen = None
            if sheet_arg:
                for item in sheets:
                    if item["name"] == sheet_arg:
                        chosen = item
                        break
                if chosen is None:
                    lowered = sheet_arg.lower()
                    for item in sheets:
                        if item["name"].lower() == lowered:
                            chosen = item
                            break
                if chosen is None:
                    return {"ok": False, "error": "sheet_not_found", "sheet": sheet_arg, "sheets": [s["name"] for s in sheets]}
            else:
                chosen = sheets[0]

            if chosen["part"] not in names:
                return {"ok": False, "error": "sheet_part_missing", "sheet": chosen["name"]}

            def column_index(cell_ref):
                letters = "".join(ch for ch in str(cell_ref) if ch.isalpha()).upper()
                if not letters:
                    return 1
                value = 0
                for ch in letters:
                    value = value * 26 + (ord(ch) - ord("A") + 1)
                return value

            def cell_value(cell):
                cell_type = cell.attrib.get("t")
                value_node = None
                inline_parts = []
                for child in cell.iter():
                    name = local_name(child.tag)
                    if name == "v" and value_node is None:
                        value_node = child
                    elif cell_type == "inlineStr" and name == "t" and child.text:
                        inline_parts.append(child.text)

                if cell_type == "inlineStr":
                    return "".join(inline_parts)

                raw = "" if value_node is None or value_node.text is None else value_node.text
                if raw == "":
                    return ""
                if cell_type == "s":
                    try:
                        return shared[int(raw)]
                    except Exception:
                        return raw
                if cell_type == "b":
                    return raw in ("1", "true", "TRUE")
                if cell_type in ("str", "e"):
                    return raw
                try:
                    number = float(raw)
                    if number.is_integer():
                        return int(number)
                    return number
                except Exception:
                    return raw

            sheet_root = read_xml(chosen["part"])
            rows = []
            for row_node in sheet_root.iter():
                if local_name(row_node.tag) != "row":
                    continue
                cells = {}
                max_col = 0
                for cell in list(row_node):
                    if local_name(cell.tag) != "c":
                        continue
                    idx = column_index(cell.attrib.get("r", ""))
                    max_col = max(max_col, idx)
                    cells[idx] = cell_value(cell)
                row_values = [cells.get(i, "") for i in range(1, max_col + 1)]
                if include_empty or any(v not in ("", None) for v in row_values):
                    rows.append(row_values)
                if len(rows) >= max_rows:
                    break

            result = {
                "ok": True,
                "path": abs_path,
                "sheet": chosen["name"],
                "sheets": [s["name"] for s in sheets],
                "rows": rows,
                "row_count": len(rows),
                "max_rows": max_rows
            }

            if header_row and rows:
                headers = [str(h) if h is not None else "" for h in rows[0]]
                records = []
                for row in rows[1:]:
                    record = {}
                    for i, header in enumerate(headers):
                        key = header or ("column_" + str(i + 1))
                        record[key] = row[i] if i < len(row) else ""
                    records.append(record)
                result["records"] = records
                result["record_count"] = len(records)

            return result
    except Exception as e:
        return {"ok": False, "error": str(e)}
