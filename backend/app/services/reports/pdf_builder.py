"""PDF report generation helper using ReportLab (WP-11)."""

from decimal import Decimal
import io
from typing import Any, List, Optional, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# Theme Colors
NAVY = colors.HexColor("#1F497D")
DARK_GRAY = colors.HexColor("#333333")
LIGHT_GRAY = colors.HexColor("#F2F2F2")
BORDER_GRAY = colors.HexColor("#D9D9D9")
TEXT_MUTED = colors.HexColor("#595959")


class NumberedCanvas(canvas.Canvas):
    """Canvas that computes total page count dynamically in a second pass."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(TEXT_MUTED)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(self._pagesize[0] - 36, 20, page_text)
        self.drawString(36, 20, "Arya Global Digital · Dual-Programme Referral Platform · Confidential")
        self.setStrokeColor(BORDER_GRAY)
        self.setLineWidth(0.5)
        self.line(36, 30, self._pagesize[0] - 36, 30)
        self.restoreState()


class PDFReportBuilder:
    """Builder class for generating clean, structured PDF reports."""

    def __init__(self, title: str, is_landscape: bool = True):
        self.title = title
        self.is_landscape = is_landscape
        self.buffer = io.BytesIO()
        self.pagesize = landscape(A4) if is_landscape else portrait(A4)
        self.doc = SimpleDocTemplate(
            self.buffer,
            pagesize=self.pagesize,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=42,
        )
        self.story = []
        self._init_styles()

    def _init_styles(self):
        base_styles = getSampleStyleSheet()
        self.styles = {
            "title": ParagraphStyle(
                "DocTitle",
                parent=base_styles["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=16,
                leading=20,
                textColor=NAVY,
                spaceAfter=4,
            ),
            "subtitle": ParagraphStyle(
                "DocSubtitle",
                parent=base_styles["Normal"],
                fontName="Helvetica-Oblique",
                fontSize=9,
                leading=12,
                textColor=TEXT_MUTED,
                spaceAfter=10,
            ),
            "meta_label": ParagraphStyle(
                "MetaLabel",
                fontName="Helvetica-Bold",
                fontSize=8,
                leading=10,
                textColor=DARK_GRAY,
            ),
            "meta_val": ParagraphStyle(
                "MetaVal",
                fontName="Helvetica",
                fontSize=8,
                leading=10,
                textColor=DARK_GRAY,
            ),
            "section_heading": ParagraphStyle(
                "SectionHeading",
                parent=base_styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=12,
                leading=15,
                textColor=NAVY,
                spaceBefore=10,
                spaceAfter=6,
            ),
            "tbl_header": ParagraphStyle(
                "TblHeader",
                fontName="Helvetica-Bold",
                fontSize=7.5,
                leading=9.5,
                textColor=colors.white,
                alignment=1,  # Center
            ),
            "tbl_cell": ParagraphStyle(
                "TblCell",
                fontName="Helvetica",
                fontSize=7,
                leading=9,
                textColor=DARK_GRAY,
            ),
            "tbl_cell_right": ParagraphStyle(
                "TblCellRight",
                fontName="Helvetica",
                fontSize=7,
                leading=9,
                textColor=DARK_GRAY,
                alignment=2,  # Right
            ),
            "tbl_total_right": ParagraphStyle(
                "TblTotalRight",
                fontName="Helvetica-Bold",
                fontSize=7.5,
                leading=9.5,
                textColor=DARK_GRAY,
                alignment=2,
            ),
            "tbl_total_left": ParagraphStyle(
                "TblTotalLeft",
                fontName="Helvetica-Bold",
                fontSize=7.5,
                leading=9.5,
                textColor=DARK_GRAY,
            ),
        }

    def add_title_block(
        self,
        report_title: str,
        subtitle: Optional[str] = None,
        metadata: Optional[List[Sequence[str]]] = None,
    ):
        """Add document header banner and metadata block."""
        self.story.append(Paragraph(report_title, self.styles["title"]))
        if subtitle:
            self.story.append(Paragraph(subtitle, self.styles["subtitle"]))

        if metadata:
            meta_rows = []
            for k, v in metadata:
                meta_rows.append([
                    Paragraph(str(k), self.styles["meta_label"]),
                    Paragraph(str(v), self.styles["meta_val"]),
                ])
            meta_table = Table(meta_rows, colWidths=[120, None])
            meta_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            self.story.append(meta_table)
            self.story.append(Spacer(1, 10))

    def add_section_heading(self, heading: str):
        """Add section subheading."""
        self.story.append(Paragraph(heading, self.styles["section_heading"]))

    def add_table(
        self,
        headers: List[str],
        data_rows: List[List[Any]],
        col_widths: Optional[List[float]] = None,
        total_row: Optional[List[Any]] = None,
    ):
        """Add styled data table with headers and optional totals."""
        table_content = []

        # 1. Header row
        header_cells = [Paragraph(str(h), self.styles["tbl_header"]) for h in headers]
        table_content.append(header_cells)

        # 2. Data rows
        for row in data_rows:
            row_cells = []
            for val in row:
                if isinstance(val, (Decimal, float, int)):
                    txt = f"{val:,.2f}" if isinstance(val, (Decimal, float)) else str(val)
                    p = Paragraph(txt, self.styles["tbl_cell_right"])
                else:
                    p = Paragraph(str(val if val is not None else "-"), self.styles["tbl_cell"])
                row_cells.append(p)
            table_content.append(row_cells)

        # 3. Optional totals row
        if total_row:
            tot_cells = []
            for val in total_row:
                if isinstance(val, (Decimal, float, int)):
                    txt = f"{val:,.2f}" if isinstance(val, (Decimal, float)) else str(val)
                    p = Paragraph(txt, self.styles["tbl_total_right"])
                else:
                    p = Paragraph(str(val if val is not None else ""), self.styles["tbl_total_left"])
                tot_cells.append(p)
            table_content.append(tot_cells)

        # Determine styling
        t_style = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ]

        # Alternating row colors
        num_data_rows = len(data_rows)
        for i in range(1, num_data_rows + 1):
            if i % 2 == 0:
                t_style.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GRAY))

        # Totals row border
        if total_row:
            tot_idx = len(table_content) - 1
            t_style.append(("LINEABOVE", (0, tot_idx), (-1, tot_idx), 1, colors.black))
            t_style.append(("LINEBELOW", (0, tot_idx), (-1, tot_idx), 1.5, colors.black))
            t_style.append(("BACKGROUND", (0, tot_idx), (-1, tot_idx), colors.HexColor("#EAECEE")))

        pdf_table = Table(table_content, colWidths=col_widths, repeatRows=1)
        pdf_table.setStyle(TableStyle(t_style))
        self.story.append(pdf_table)
        self.story.append(Spacer(1, 10))

    def to_bytes(self) -> bytes:
        """Build and render PDF to bytes."""
        self.doc.build(self.story, canvasmaker=NumberedCanvas)
        self.buffer.seek(0)
        return self.buffer.getvalue()

