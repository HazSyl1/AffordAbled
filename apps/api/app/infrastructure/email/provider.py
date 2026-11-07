from __future__ import annotations

import asyncio
from dataclasses import dataclass


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

    async def send(self, *, recipient_email: str, subject: str, body: str, notification_id) -> EmailSendResult:
        message = {
            'senderAddress': self._sender_address,
            'recipients': {'to': [{'address': recipient_email}]},
            'content': {'subject': subject, 'plainText': body},
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
