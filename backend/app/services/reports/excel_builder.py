"""Excel (.xlsx) report generation helper using openpyxl (WP-11)."""

from decimal import Decimal
import io
from typing import Any, List, Optional, Sequence, Union

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Design constants
NAVY_HEADER_FILL = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
TOTAL_FONT = Font(name="Calibri", size=11, bold=True, color="000000")
REGULAR_FONT = Font(name="Calibri", size=10, bold=False, color="000000")
TITLE_FONT = Font(name="Calibri", size=14, bold=True, color="1F497D")
SUBTITLE_FONT = Font(name="Calibri", size=10, italic=True, color="595959")

THIN_BORDER_SIDE = Side(border_style="thin", color="D9D9D9")
DOUBLE_BOTTOM_SIDE = Side(border_style="double", color="000000")
TOP_THIN_SIDE = Side(border_style="thin", color="000000")

CELL_BORDER = Border(
    left=THIN_BORDER_SIDE,
    right=THIN_BORDER_SIDE,
    top=THIN_BORDER_SIDE,
    bottom=THIN_BORDER_SIDE,
)

TOTAL_ROW_BORDER = Border(
    top=TOP_THIN_SIDE,
    bottom=DOUBLE_BOTTOM_SIDE,
)


class ExcelReportBuilder:
    """Builder class for structured, beautifully styled multi-worksheet Excel reports."""

    def __init__(self, title: str):
        self.workbook = openpyxl.Workbook()
        self.title = title
        # Remove default sheet if unused or rename it
        self.default_sheet = self.workbook.active
        self.default_sheet_used = False

    def create_sheet(self, sheet_name: str) -> openpyxl.worksheet.worksheet.Worksheet:
        """Create or reuse the primary worksheet with the given name."""
        safe_name = sheet_name[:31]  # Excel limits sheet names to 31 chars
        if not self.default_sheet_used:
            ws = self.default_sheet
            ws.title = safe_name
            self.default_sheet_used = True
        else:
            ws = self.workbook.create_sheet(title=safe_name)
        ws.views.sheetView[0].showGridLines = True
        return ws

    def add_title_block(
        self,
        ws: openpyxl.worksheet.worksheet.Worksheet,
        report_title: str,
        subtitle: Optional[str] = None,
        metadata: Optional[List[Sequence[str]]] = None,
    ) -> int:
        """Add a professional title, optional subtitle, and key-value metadata block. Returns next available row."""
        ws.append([report_title])
        ws.cell(row=1, column=1).font = TITLE_FONT
        current_row = 2

        if subtitle:
            ws.append([subtitle])
            ws.cell(row=current_row, column=1).font = SUBTITLE_FONT
            current_row += 1

        if metadata:
            current_row += 1
            for k, v in metadata:
                ws.append([k, v])
                ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=10, bold=True)
                ws.cell(row=current_row, column=2).font = REGULAR_FONT
                current_row += 1

        # Blank row before table
        ws.append([])
        return current_row + 1

    def add_table(
        self,
        ws: openpyxl.worksheet.worksheet.Worksheet,
        headers: List[str],
        rows: List[List[Any]],
        start_row: Optional[int] = None,
        total_row: Optional[List[Any]] = None,
    ) -> int:
        """Append a data table with styled headers, formatted cells, and optional totals row."""
        # 1. Header row
        ws.append(headers)
        header_row_idx = ws.max_row
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.fill = NAVY_HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # 2. Data rows
        for row_data in rows:
            ws.append(row_data)
            current_row_idx = ws.max_row
            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=current_row_idx, column=col_idx)
                cell.font = REGULAR_FONT
                cell.border = CELL_BORDER

                if isinstance(val, (Decimal, float)):
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif isinstance(val, int):
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.alignment = Alignment(horizontal="left")

        # 3. Optional totals row
        if total_row:
            ws.append(total_row)
            tot_row_idx = ws.max_row
            for col_idx, val in enumerate(total_row, start=1):
                cell = ws.cell(row=tot_row_idx, column=col_idx)
                cell.font = TOTAL_FONT
                cell.border = TOTAL_ROW_BORDER
                if isinstance(val, (Decimal, float)):
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif isinstance(val, int):
                    cell.alignment = Alignment(horizontal="right")
                else:
                    cell.alignment = Alignment(horizontal="left")

        # 4. Auto-fit column widths
        self.auto_fit_columns(ws)
        return ws.max_row + 1

    @staticmethod
    def auto_fit_columns(ws: openpyxl.worksheet.worksheet.Worksheet, min_width: int = 12, max_width: int = 40):
        """Adjust column widths dynamically based on cell content lengths."""
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, min_width), max_width)

    def to_bytes(self) -> bytes:
        """Render workbook to binary bytes buffer."""
        buffer = io.BytesIO()
        self.workbook.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()

