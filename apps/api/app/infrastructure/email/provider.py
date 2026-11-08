from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass

from app.infrastructure.email.message import RenderedEmail


@dataclass(frozen=True)
class EmailSendResult:
    successful: bool
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class AzureAcsEmailProvider:
    def __init__(self, connection_string: str, sender_address: str, timeout_seconds: int = 30) -> None:
        from azure.communication.email import EmailClient

        self._client = EmailClient.from_connection_string(connection_string)
        self._sender_address = sender_address
        self._timeout_seconds = max(5, timeout_seconds)

    async def send(self, *, recipient_email: str, email: RenderedEmail, notification_id) -> EmailSendResult:
        message = {
            'senderAddress': self._sender_address,
            'recipients': {'to': [{'address': recipient_email}]},
            'content': {
                'subject': email.subject,
                'plainText': email.plain_text,
                'html': email.html,
            },
            'attachments': [
                {
                    'name': attachment.name,
                    'contentType': attachment.content_type,
                    'contentInBase64': base64.b64encode(attachment.content).decode('ascii'),
                    'contentId': attachment.content_id,
                }
                for attachment in email.inline_attachments
            ],
            'userEngagementTrackingDisabled': True,
        }
        try:
            poller = await asyncio.wait_for(
                asyncio.to_thread(self._client.begin_send, message), timeout=self._timeout_seconds,
            )
            result = await asyncio.wait_for(asyncio.to_thread(poller.result), timeout=self._timeout_seconds)
            status = str(result.get('status', '')).casefold() if isinstance(result, dict) else ''
            if status and status != 'succeeded':
                return EmailSendResult(False, error_code='provider_rejected', error_message=f'Email status: {status}')
            message_id = result.get('id') if isinstance(result, dict) else None
            return EmailSendResult(True, message_id=message_id)
        except TimeoutError:
            return EmailSendResult(False, error_code='provider_timeout', error_message='Email provider timed out.')
        except Exception as error:
            return EmailSendResult(False, error_code='provider_exception', error_message=type(error).__name__)
