from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO, StringIO

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

HEADERS = (
    'occurred_at', 'type', 'amount_rupees', 'account', 'category', 'to_account', 'merchant',
)
CONTENT_TYPES = {
    'csv': 'text/csv; charset=utf-8',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'pdf': 'application/pdf',
}


@dataclass(frozen=True)
class ReportRow:
    transaction_id: str
    occurred_at: datetime
    type: str
    amount_paise: int
    account: str
    category: str
    to_account: str
    merchant: str

    def values(self) -> tuple[str | Decimal, ...]:
        return (
            self.occurred_at.isoformat(), self.type, Decimal(self.amount_paise) / 100,
            self.account, self.category, self.to_account, self.merchant,
        )


def _safe_spreadsheet_value(value: str | Decimal) -> str | Decimal:
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def render_csv(rows: list[ReportRow]) -> bytes:
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(HEADERS)
    for row in rows:
        writer.writerow([_safe_spreadsheet_value(value) for value in row.values()])
    return buffer.getvalue().encode('utf-8-sig')


def render_xlsx(rows: list[ReportRow]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Transactions')
    sheet.append(HEADERS)
    for row in rows:
        sheet.append([_safe_spreadsheet_value(value) for value in row.values()])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _pdf_text(value: str, *, limit: int = 48) -> str:
    return value.encode('latin-1', errors='replace').decode('latin-1')[:limit]


def render_pdf(rows: list[ReportRow]) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=landscape(A4), invariant=1)
    width, height = landscape(A4)
    total_expense = sum(row.amount_paise for row in rows if row.type == 'expense')
    total_income = sum(row.amount_paise for row in rows if row.type in {'income', 'refund'})

    def page_header() -> float:
        document.setFont('Helvetica-Bold', 16)
        document.drawString(36, height - 38, 'AffordAbled transaction report')
        document.setFont('Helvetica', 10)
        document.drawString(
            36, height - 57,
            f'{len(rows)} transactions  |  Expenses INR {total_expense / 100:,.2f}'
            f'  |  Income INR {total_income / 100:,.2f}',
        )
        document.setFont('Helvetica-Bold', 9)
        for x, heading in ((36, 'Date'), (145, 'Type'), (210, 'Amount'), (295, 'Account'),
                           (405, 'Category'), (520, 'To account'), (650, 'Merchant')):
            document.drawString(x, height - 82, heading)
        document.line(36, height - 88, width - 36, height - 88)
        return height - 105

    y = page_header()
    document.setFont('Helvetica', 8)
    for row in rows:
        if y < 38:
            document.showPage()
            y = page_header()
            document.setFont('Helvetica', 8)
        values = (
            (36, row.occurred_at.strftime('%Y-%m-%d %H:%M')),
            (145, row.type),
            (210, f'INR {row.amount_paise / 100:,.2f}'),
            (295, _pdf_text(row.account, limit=18)),
            (405, _pdf_text(row.category, limit=18)),
            (520, _pdf_text(row.to_account, limit=20)),
            (650, _pdf_text(row.merchant, limit=30)),
        )
        for x, value in values:
            document.drawString(x, y, value)
        y -= 16
    document.save()
    return output.getvalue()
