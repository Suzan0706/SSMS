"""Spreadsheet output that cannot run what people typed (CSV / formula injection).

A cell a spreadsheet program would treat as a formula (it starts with =, +, -, @, a tab or a return) is written as
text: in CSV with a leading apostrophe, in XLSX by storing the cell as a string, so it shows exactly as typed.
Every CSV and XLSX the system produces goes through here.
"""

from openpyxl.worksheet.worksheet import Worksheet

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def risky(text: str) -> bool:
    return text[:1] in FORMULA_START


def csv_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if risky(text) else text


def append(ws: Worksheet, values) -> None:
    """ws.append, except that a string is always stored as text, never as a formula."""
    ws.append(list(values))
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str) and risky(cell.value):
            cell.data_type = "s"
