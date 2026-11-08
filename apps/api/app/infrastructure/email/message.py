# ruff: noqa: E501  (inline-styled HTML email template)
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from html import escape
from io import BytesIO

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_M

BRAND_PURPLE = '#a855f7'
BRAND_PURPLE_LIGHT = '#f4efff'
LOGO_CONTENT_ID = 'affordabled-logo'
QR_CONTENT_ID = 'affordabled-payment-qr'


@dataclass(frozen=True)
class InlineEmailAttachment:
    name: str
    content_type: str
    content: bytes
    content_id: str


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    plain_text: str
    html: str
    inline_attachments: tuple[InlineEmailAttachment, ...]


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()


@lru_cache(maxsize=1)
def build_affordabled_logo_png() -> bytes:
    """Render the existing wallet favicon as an email-safe PNG."""
    scale = 2
    image = Image.new('RGBA', (64 * scale, 64 * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    purple = '#863bff'
    light_purple = '#d9c2ff'
    draw.rounded_rectangle((0, 0, 128, 128), radius=32, fill=purple)
    draw.rounded_rectangle((26, 46, 102, 106), radius=10, fill='white')
    draw.line((34, 46, 34, 40, 44, 30, 88, 30, 98, 40, 98, 46), fill='white', width=8, joint='curve')
    draw.rounded_rectangle((76, 70, 106, 90), radius=10, fill=light_purple)
    draw.ellipse((82, 76, 90, 84), fill=purple)
    return _png_bytes(image)


def build_payment_qr_png(upi_link: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(upi_link)
    qr.make(fit=True)
    image = qr.make_image(fill_color='#111827', back_color='white').convert('RGB')
    return _png_bytes(image)


def render_payment_request_email(
    *, subject: str, plain_text: str, contact_name: str, creator_name: str,
    amount_paise: int, note: str, upi_id: str, upi_link: str,
    pay_url: str | None = None, app_url: str | None = None,
) -> RenderedEmail:
    amount = Decimal(amount_paise) / Decimal(100)
    amount_text = f'₹{amount:,.2f}'
    safe_contact = escape(contact_name)
    safe_creator = escape(creator_name)
    safe_note = escape(' '.join(note.split()))
    safe_upi_id = escape(upi_id)
    # Mail clients (Gmail, Outlook) strip upi:// links, so the button opens an https page that hands off to the UPI app.
    safe_button_link = escape(pay_url or upi_link, quote=True)
    safe_app_url = escape(app_url, quote=True) if app_url else None
    app_cta = (
        f'<a href="{safe_app_url}" style="display:inline-block;background:#ffffff;color:{BRAND_PURPLE};'
        'border:2px solid ' + BRAND_PURPLE + ';text-decoration:none;font-size:14px;font-weight:700;'
        'padding:10px 24px;border-radius:10px;">Try AffordAbled free &rarr;</a>'
        if safe_app_url else ''
    )

    html = f'''<!doctype html>
<html lang="en">
  <body style="margin:0;padding:0;background:#f5f3f8;color:#1f2937;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f3f8;">
      <tr>
        <td align="center" style="padding:32px 12px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
                 style="max-width:600px;background:#ffffff;border-radius:18px;overflow:hidden;border:1px solid #e8e3ee;">
            <tr>
              <td style="background:{BRAND_PURPLE};padding:22px 28px;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td style="padding-right:12px;vertical-align:middle;">
                      <img src="cid:{LOGO_CONTENT_ID}" width="44" height="44" alt="AffordAbled"
                           style="display:block;border:0;border-radius:11px;" />
                    </td>
                    <td style="vertical-align:middle;color:#ffffff;font-size:23px;font-weight:700;letter-spacing:-0.3px;">
                      AffordAbled
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:34px 32px 8px;">
                <p style="margin:0 0 14px;font-size:16px;line-height:24px;">Hi {safe_contact},</p>
                <p style="margin:0;color:#4b5563;font-size:16px;line-height:25px;">
                  <strong style="color:#1f2937;">{safe_creator}</strong> sent you a payment request through AffordAbled.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 32px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
                       style="background:{BRAND_PURPLE_LIGHT};border-radius:14px;">
                  <tr>
                    <td align="center" style="padding:26px 20px 22px;">
                      <div style="color:#6b7280;font-size:13px;font-weight:700;letter-spacing:0.8px;text-transform:uppercase;">
                        Amount requested
                      </div>
                      <div style="margin-top:8px;color:#4c1d95;font-size:38px;line-height:46px;font-weight:800;">
                        {amount_text}
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:2px 32px 24px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
                       style="font-size:15px;line-height:22px;">
                  <tr>
                    <td style="padding:10px 0;color:#6b7280;width:36%;border-bottom:1px solid #eeeaf2;">For</td>
                    <td style="padding:10px 0;color:#1f2937;font-weight:600;border-bottom:1px solid #eeeaf2;">{safe_note}</td>
                  </tr>
                  <tr>
                    <td style="padding:10px 0;color:#6b7280;border-bottom:1px solid #eeeaf2;">Requested by</td>
                    <td style="padding:10px 0;color:#1f2937;font-weight:600;border-bottom:1px solid #eeeaf2;">{safe_creator}</td>
                  </tr>
                  <tr>
                    <td style="padding:10px 0;color:#6b7280;">Pay to</td>
                    <td style="padding:10px 0;color:#1f2937;font-weight:600;">{safe_upi_id}</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:2px 32px 28px;">
                <a href="{safe_button_link}"
                   style="display:inline-block;background:{BRAND_PURPLE};color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;padding:14px 30px;border-radius:10px;">
                  Pay with UPI
                </a>
                <div style="margin-top:10px;color:#6b7280;font-size:12px;">Opens your UPI app on your phone.</div>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:0 32px 30px;">
                <div style="color:#6b7280;font-size:13px;line-height:20px;">
                  On the payment page you'll also find a <strong>QR code</strong> you can scan with any UPI app.
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 32px;">
                <div style="background:#fff8e6;border:1px solid #f5dfaa;border-radius:10px;padding:14px 16px;color:#6b521a;font-size:13px;line-height:20px;">
                  Before paying, verify the payee UPI ID and amount in your UPI app. If you were not expecting this request, contact the requester directly.
                </div>
              </td>
            </tr>
            <tr>
              <td align="center" style="background:{BRAND_PURPLE_LIGHT};border-top:1px solid #eeeaf2;padding:26px 28px;">
                <div style="color:#4c1d95;font-size:16px;font-weight:800;">Meet AffordAbled</div>
                <div style="margin-top:8px;color:#4b5563;font-size:13px;line-height:20px;">
                  Your personal AI wallet. Track every account, log expenses just by chatting or sending a receipt photo,
                  split bills with friends, and send UPI payment reminders like this one &mdash; all in one place.
                </div>
                <div style="margin-top:12px;font-size:14px;">{app_cta}</div>
              </td>
            </tr>
            <tr>
              <td align="center" style="background:#faf9fb;border-top:1px solid #eeeaf2;padding:22px 28px;color:#7c7485;font-size:12px;line-height:19px;">
                This is an automated message from AffordAbled.<br />Please do not reply to this email.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>'''

    return RenderedEmail(
        subject=subject,
        plain_text=plain_text,
        html=html,
        inline_attachments=(
            InlineEmailAttachment(
                name='affordabled-logo.png', content_type='image/png',
                content=build_affordabled_logo_png(), content_id=LOGO_CONTENT_ID,
            ),
        ),
    )
