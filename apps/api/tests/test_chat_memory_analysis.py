from __future__ import annotations

import uuid

import pytest

from app.application.services.memory_service import candidates_for_event
from app.infrastructure.ai.agents.chat_memory_analysis import (
    ChatMemoryAnalysis,
    ExtractedMemoryCandidate,
    extract_chat_memory_candidates,
)


class _StructuredFake:
    def __init__(self, result):
        self.result = result

    async def ainvoke(self, _messages):
        return self.result


class _FakeLlm:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, _schema):
        return _StructuredFake(self.result)


@pytest.mark.asyncio
async def test_extracts_category_memory_only_when_quote_and_category_are_verified() -> None:
    category_id = uuid.uuid4()
    llm = _FakeLlm(ChatMemoryAnalysis(candidates=[ExtractedMemoryCandidate(
        kind='category_mapping', subject='PCM', value='Medicines', evidence='Medicines',
    )]))

    results = await extract_chat_memory_candidates(llm, {
        'history': [
            {'role': 'user', 'content': 'spent 99 on pcm'},
            {'role': 'assistant', 'content': 'Which category should I use?'},
            {'role': 'user', 'content': 'Medicines'},
        ],
        'categories': [{'id': str(category_id), 'name': 'Medicines'}],
        'accounts': [],
        'signal': {'signal_type': 'category_mapping', 'subject_hint': 'pcm'},
    })

    assert results == [{
        'scope': 'merchant', 'subject_key': 'pcm', 'memory_type': 'category_mapping',
        'value_json': {'category_id': str(category_id)},
    }]


@pytest.mark.asyncio
async def test_rejects_assistant_only_evidence_and_unknown_category() -> None:
    llm = _FakeLlm(ChatMemoryAnalysis(candidates=[
        ExtractedMemoryCandidate(kind='category_mapping', subject='pcm', value='Fake', evidence='Food'),
    ]))
    result = await extract_chat_memory_candidates(llm, {
        'history': [
            {'role': 'user', 'content': 'spent 99 on pcm'},
            {'role': 'assistant', 'content': 'Food would work.'},
        ],
        'categories': [{'id': str(uuid.uuid4()), 'name': 'Food'}],
        'accounts': [],
        'signal': {'signal_type': 'category_mapping', 'subject_hint': 'pcm'},
    })
    assert result == []


def test_extracted_candidates_enter_existing_three_event_review_pipeline() -> None:
    candidates = candidates_for_event(action='accepted', before={}, after={
        'memory_candidates': [{
            'scope': 'person', 'subject_key': 'isha', 'memory_type': 'split_person_preference',
            'value_json': {'key': 'diet', 'value': 'vegetarian'},
        },
        # Reject unsupported model-produced memory types.
        {
            'scope': 'person', 'subject_key': 'me', 'memory_type': 'secret',
            'value_json': {'value': 'unsafe'},
        }],
    })
    assert len(candidates) == 1
    assert candidates[0].memory_type == 'split_person_preference'
    assert candidates[0].subject_key == 'isha'
