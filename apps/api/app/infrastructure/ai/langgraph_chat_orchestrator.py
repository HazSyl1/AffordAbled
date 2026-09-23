from __future__ import annotations

import uuid
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langsmith import traceable

from app.domain.ports import DetectedIntent, GuardrailDecision, IntentClassifier, SemanticGuardrail

_REFUSAL_MESSAGE = (
    "I'm your finance assistant — I can only help with money matters. "
    'Want me to log a transaction, check spending, or split a bill?'
)


class ChatGraphState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class LangGraphChatOrchestrator:
    def __init__(
        self,
        *,
        checkpointer: Any,
        semantic_guardrail: SemanticGuardrail,
        intent_classifier: IntentClassifier,
    ) -> None:
        self._semantic_guardrail = semantic_guardrail
        self._intent_classifier = intent_classifier

        self._guardrail_chain = (
            ChatPromptTemplate.from_messages(
                [
                    ('system', 'Classify whether this user message is in finance scope.'),
                    ('human', '{message}'),
                ]
            )
            | RunnableLambda(self._extract_message_from_prompt)
            | RunnableLambda(self._semantic_guardrail.assess)
        )

        self._intent_chain = (
            ChatPromptTemplate.from_messages(
                [
                    ('system', 'Classify the finance intent for this user message.'),
                    ('human', '{message}'),
                ]
            )
            | RunnableLambda(self._extract_message_from_prompt)
            | RunnableLambda(self._intent_classifier.classify)
        )

        builder = StateGraph(ChatGraphState)
        builder.add_node('assistant', self._assistant_node)
        builder.add_edge(START, 'assistant')
        builder.add_edge('assistant', END)
        self._graph = builder.compile(checkpointer=checkpointer)

    @traceable(name='langgraph_chat_turn', run_type='chain')
    async def run_turn(self, *, user_id: uuid.UUID, thread_id: str, message: str) -> str:
        checkpoint_thread_id = f'{user_id}:{thread_id}'
        result = await self._graph.ainvoke(
            {'messages': [HumanMessage(content=message)]},
            config={
                'configurable': {
                    'thread_id': checkpoint_thread_id,
                    'checkpoint_ns': str(user_id),
                }
            },
        )

        for item in reversed(result['messages']):
            if isinstance(item, AIMessage):
                return str(item.content)

        return _REFUSAL_MESSAGE

    async def _assistant_node(self, state: ChatGraphState) -> dict[str, list[AIMessage]]:
        latest_user_message = self._latest_user_message(state['messages'])
        if not latest_user_message:
            return {'messages': [AIMessage(content=_REFUSAL_MESSAGE)]}

        guardrail_decision = self._as_guardrail_decision(
            await self._guardrail_chain.ainvoke({'message': latest_user_message})
        )
        if guardrail_decision == GuardrailDecision.BLOCK:
            return {'messages': [AIMessage(content=_REFUSAL_MESSAGE)]}

        if guardrail_decision == GuardrailDecision.NEEDS_CLASSIFICATION:
            detected_intent = self._as_detected_intent(
                await self._intent_chain.ainvoke({'message': latest_user_message})
            )
            if detected_intent == DetectedIntent.OFF_TOPIC:
                return {'messages': [AIMessage(content=_REFUSAL_MESSAGE)]}

        previous_user_message = self._previous_user_message(state['messages'])
        if previous_user_message:
            reply = f'Got it. You said: "{latest_user_message}". Earlier you mentioned: "{previous_user_message}".'
        else:
            reply = f'Got it. You said: "{latest_user_message}".'

        return {'messages': [AIMessage(content=reply)]}

    @staticmethod
    def _extract_message_from_prompt(prompt_value: Any) -> str:
        messages = getattr(prompt_value, 'messages', [])
        if not messages:
            return ''
        return str(messages[-1].content)

    @staticmethod
    def _latest_user_message(messages: list[BaseMessage]) -> str:
        for item in reversed(messages):
            if isinstance(item, HumanMessage):
                return str(item.content)
        return ''

    @staticmethod
    def _previous_user_message(messages: list[BaseMessage]) -> str:
        seen_latest_user = False
        for item in reversed(messages):
            if not isinstance(item, HumanMessage):
                continue
            if not seen_latest_user:
                seen_latest_user = True
                continue
            return str(item.content)
        return ''

    @staticmethod
    def _as_guardrail_decision(value: GuardrailDecision | str) -> GuardrailDecision:
        if isinstance(value, GuardrailDecision):
            return value
        normalized_value = str(value).strip().lower()
        for decision in GuardrailDecision:
            if decision.value == normalized_value:
                return decision
        return GuardrailDecision.BLOCK

    @staticmethod
    def _as_detected_intent(value: DetectedIntent | str) -> DetectedIntent:
        if isinstance(value, DetectedIntent):
            return value
        normalized_value = str(value).strip().lower()
        for intent in DetectedIntent:
            if intent.value == normalized_value:
                return intent
        return DetectedIntent.OFF_TOPIC


