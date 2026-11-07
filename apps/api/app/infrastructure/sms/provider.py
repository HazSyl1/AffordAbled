from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SmsSendResult:
    successful: bool
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class AzureAcsSmsProvider:
    def __init__(self, connection_string: str, sender_number: str, timeout_seconds: int = 15) -> None:
        if not connection_string or not sender_number:
            raise ValueError('Azure SMS connection string and sender number are required.')
        from azure.communication.sms import SmsClient

        self._client = SmsClient.from_connection_string(connection_string)
        self._sender_number = sender_number
        self._timeout_seconds = max(1, timeout_seconds)

    async def send(
        self, *, recipient_phone: str, message: str, notification_id: uuid.UUID,
    ) -> SmsSendResult:
        try:
            responses = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.send,
                    from_=self._sender_number,
                    to=recipient_phone,
                    message=message,
                    enable_delivery_report=False,
                    tag=str(notification_id),
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return SmsSendResult(False, error_code='provider_timeout', error_message='SMS provider response timed out.')
        response = responses[0] if responses else None
        if response is None:
            return SmsSendResult(
                False, error_code='empty_provider_response', error_message='SMS provider returned no result.',
            )
        if bool(getattr(response, 'successful', False)):
            return SmsSendResult(True, message_id=str(getattr(response, 'message_id', '') or '') or None)
        return SmsSendResult(
            False,
            message_id=str(getattr(response, 'message_id', '') or '') or None,
            error_code=str(getattr(response, 'http_status_code', '') or 'provider_rejected'),
            error_message=str(getattr(response, 'error_message', '') or 'SMS provider rejected the request.'),
        )
