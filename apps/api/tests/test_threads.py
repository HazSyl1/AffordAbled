from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core.dependencies import get_semantic_guardrail, get_transaction_extraction_llm
from app.domain.ports import GuardrailAssessment, GuardrailDecision
from app.infrastructure.ai.agents.contracts import SpecialistDecision, SupervisorDecision
from tests.helpers import auth_headers, register_and_get_token


class AllowingGuardrail:
    async def assess(self, _message: str) -> GuardrailAssessment:
        return GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=1.0, layer="test")


class ReadOnlyAgenticLlm:
    """Keeps thread persistence testing independent of a deployed model."""

    def __init__(self) -> None:
        self.supervisor = [
            SupervisorDecision(action="route", specialist="analytics"),
            SupervisorDecision(action="finish"),
            SupervisorDecision(action="finish", response="No transactions found."),
        ]
        self.analytics = [SpecialistDecision(action="finish", summary="No transactions found.")]
        self.formatting = [SpecialistDecision(action="finish", summary="No transactions found.")]

    def with_structured_output(self, schema: type[Any], **_kwargs: Any) -> RunnableLambda:
        def respond(prompt: Any) -> Any:
            content = "\n".join(str(message.content) for message in prompt.to_messages())
            if schema is SupervisorDecision:
                return self.supervisor.pop(0)
            if schema is SpecialistDecision and "analytics specialist" in content:
                return self.analytics.pop(0)
            if schema is SpecialistDecision and "formatting specialist" in content:
                return self.formatting.pop(0)
            raise AssertionError("Unexpected agent call")

        return RunnableLambda(respond)

    def bind_tools(self, _tools: list[Any], **_kwargs: Any) -> RunnableLambda:
        async def respond(messages: list[Any]) -> AIMessage:
            system = str(messages[0].content)
            if "analytics specialist" in system or "formatting specialist" in system:
                return AIMessage(content="No transactions found.")
            raise AssertionError("Unexpected bound-tool specialist")

        return RunnableLambda(respond)


async def test_threads_router_crud_and_ownership(client: AsyncClient) -> None:
    owner_token = await register_and_get_token(client, 'threads-owner@example.com')
    other_token = await register_and_get_token(client, 'threads-other@example.com')

    create_response = await client.post(
        '/api/v1/threads',
        json={'thread_id': 'budget-thread', 'title': 'Budget Discussion'},
        headers=auth_headers(owner_token),
    )
    assert create_response.status_code == 201
    assert create_response.json()['thread_id'] == 'budget-thread'

    duplicate_response = await client.post(
        '/api/v1/threads',
        json={'thread_id': 'budget-thread'},
        headers=auth_headers(owner_token),
    )
    assert duplicate_response.status_code == 409

    list_owner_response = await client.get('/api/v1/threads', headers=auth_headers(owner_token))
    assert list_owner_response.status_code == 200
    assert len(list_owner_response.json()) == 1

    detail_owner_response = await client.get('/api/v1/threads/budget-thread', headers=auth_headers(owner_token))
    assert detail_owner_response.status_code == 200
    assert detail_owner_response.json()['thread']['thread_id'] == 'budget-thread'
    assert detail_owner_response.json()['messages'] == []

    detail_other_response = await client.get('/api/v1/threads/budget-thread', headers=auth_headers(other_token))
    assert detail_other_response.status_code == 404

    delete_other_response = await client.delete('/api/v1/threads/budget-thread', headers=auth_headers(other_token))
    assert delete_other_response.status_code == 404

    delete_owner_response = await client.delete('/api/v1/threads/budget-thread', headers=auth_headers(owner_token))
    assert delete_owner_response.status_code == 204

    final_list_response = await client.get('/api/v1/threads', headers=auth_headers(owner_token))
    assert final_list_response.status_code == 200
    assert final_list_response.json() == []


async def test_chat_messages_are_persisted_in_thread_history(client: AsyncClient, app: FastAPI) -> None:
    token = await register_and_get_token(client, 'threads-chat-persistence@example.com')
    app.dependency_overrides[get_semantic_guardrail] = lambda: AllowingGuardrail()
    app.dependency_overrides[get_transaction_extraction_llm] = lambda: ReadOnlyAgenticLlm()

    try:
        chat_response = await client.post(
            '/api/v1/chat',
            json={'message': 'show my transactions this week'},
            headers=auth_headers(token),
        )
        assert chat_response.status_code == 200

        thread_id = chat_response.json()['thread_id']
        detail_response = await client.get(f'/api/v1/threads/{thread_id}', headers=auth_headers(token))
        assert detail_response.status_code == 200

        payload = detail_response.json()
        assert payload['thread']['thread_id'] == thread_id
        assert payload['thread']['message_count'] >= 2
        roles = [message['role'] for message in payload['messages']]
        assert roles[0] == 'user'
        assert 'assistant' in roles
    finally:
        app.dependency_overrides.pop(get_semantic_guardrail, None)
        app.dependency_overrides.pop(get_transaction_extraction_llm, None)
