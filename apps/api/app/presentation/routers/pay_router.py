# ruff: noqa: E501  (inline HTML/CSS template)
from __future__ import annotations

import base64
import json
import uuid
from decimal import Decimal
from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.application.services.split_notification_service import SplitNotificationService
from app.infrastructure.email.message import build_payment_qr_png
from app.presentation.routers.splits_router import get_split_notification_service

router = APIRouter(prefix='/pay', tags=['pay'], include_in_schema=False)

_HEADERS = {
    'Cache-Control': 'private, no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex',
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'",
}

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pay with UPI &middot; AffordAbled</title>
<style>
body{{margin:0;background:#f5f3f8;font-family:Arial,Helvetica,sans-serif;color:#1f2937}}
.card{{max-width:420px;margin:32px auto;background:#fff;border-radius:18px;overflow:hidden;border:1px solid #e8e3ee}}
.head{{background:#a855f7;color:#fff;padding:20px 24px;font-weight:700;font-size:20px}}
.body{{padding:24px;text-align:center}}
.amount{{font-size:38px;font-weight:800;color:#4c1d95;margin:8px 0 4px}}
.muted{{color:#6b7280;font-size:14px;line-height:21px}}
.btn{{display:inline-block;margin:20px 0 6px;background:#a855f7;color:#fff;text-decoration:none;font-weight:700;padding:14px 32px;border-radius:10px}}
.qr{{margin:24px auto 8px;width:200px;height:200px;border:1px solid #e5e7eb;border-radius:12px;padding:8px;background:#fff}}
.divider{{margin:20px 0;color:#9ca3af;font-size:13px}}
.box{{margin-top:18px;background:#f4efff;border-radius:12px;padding:12px;font-size:14px;word-break:break-all}}
</style></head><body><div class="card"><div class="head">AffordAbled</div><div class="body">
<div class="muted">{greeting}</div>
<div class="amount">{amount}</div>
<div class="muted">to <strong>{payee}</strong></div>
<a class="btn" href="{link}">Open my UPI app</a>
<div class="muted">If nothing opens, you are probably on a computer.</div>
<div class="divider">&mdash; or scan this QR code &mdash;</div>
<img class="qr" src="{qr_data_uri}" alt="QR code for UPI payment" />
<div class="box">UPI ID: <strong>{upi_id}</strong></div>
<p class="muted">Verify the payee and amount in your UPI app before paying.</p>
</div></div>
<script>setTimeout(function(){{window.location.href={js_link};}},400);</script>
</body></html>"""


def render_pay_page(data: dict) -> str:
    amount = Decimal(data['amount_paise']) / Decimal(100)
    payee = data['payee_name'] or data['payee_upi_id']
    qr_png = build_payment_qr_png(data['upi_link'])
    qr_b64 = base64.b64encode(qr_png).decode('ascii')
    return _PAGE.format(
        greeting=escape(f"Hi {data['recipient_name']}, you have a payment request"),
        amount=escape(f'₹{amount:,.2f}'),
        payee=escape(payee),
        link=escape(data['upi_link'], quote=True),
        upi_id=escape(data['payee_upi_id']),
        qr_data_uri=f'data:image/png;base64,{qr_b64}',
        js_link=json.dumps(data['upi_link']).replace('<', r'<'),
    )


@router.get('/{notification_id}', response_class=HTMLResponse)
async def payment_page(
    notification_id: uuid.UUID,
    service: SplitNotificationService = Depends(get_split_notification_service),
) -> HTMLResponse:
    data = await service.payment_page_data(notification_id)
    if data is None:
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<body style="font-family:Arial;text-align:center;padding:48px">'
            '<h2>This payment request is no longer available</h2>'
            '<p>Ask the sender for a fresh reminder.</p></body>',
            status_code=404, headers=_HEADERS,
        )
    return HTMLResponse(render_pay_page(data), headers=_HEADERS)
