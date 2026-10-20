from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from app.application.services.memory_service import normalize_key


class ExtractedMemoryCandidate(BaseModel):
    kind: Literal['category_mapping', 'account_mapping', 'user_preference', 'split_person_preference']
    subject: str = Field(min_length=1, max_length=120, description='Merchant, person, or user subject.')
    value: str = Field(min_length=1, max_length=160, description='Selected category/account or preference value.')
    preference_key: str | None = Field(default=None, max_length=80)
    evidence: str = Field(min_length=1, max_length=240, description='Exact quote from a user message.')


class ChatMemoryAnalysis(BaseModel):
    candidates: list[ExtractedMemoryCandidate] = Field(default_factory=list, max_length=8)


_ANALYSIS_PROMPT = """Extract only durable user preferences supported by this conversation.
The record exists because a specialist marked a clarification or correction as a memory signal. Use the attached
transaction summary to connect the user's exact answer to the merchant and the selected owned category/account.
Return no candidate unless the user message itself provides clear evidence. Never treat the assistant's suggestion
as user preference. Evidence must be an exact short quote from a user message in the supplied history.

Kinds:
- category_mapping: a user selected a category for a merchant after being asked; subject is merchant, value is the
  exact available category name.
- account_mapping: a user selected an account for a merchant after being asked; subject is merchant, value is the
  exact available account name.
- user_preference: an explicit reusable preference about how the user wants transactions handled.
- split_person_preference: an explicit preference about a named split contact, not inferred from item assignment.

Do not return a one-time transaction fact, amount, date, or preference inferred from repetition unless the user
explicitly states it. Do not invent participants, IDs, categories, accounts, or preference values. At most 3
high-confidence candidates. If unsure, return an empty list."""


async def extract_chat_memory_candidates(llm, payload: dict) -> list[dict]:
    structured = llm.with_structured_output(ChatMemoryAnalysis)
    result = await structured.ainvoke([
        ('system', _ANALYSIS_PROMPT),
        ('human', json.dumps(payload, ensure_ascii=False, separators=(',', ':'))),
    ])
    parsed = result if isinstance(result, ChatMemoryAnalysis) else ChatMemoryAnalysis.model_validate(result)
    user_quotes = [
        normalize_key(str(message.get('content') or ''))
        for message in payload.get('history', [])
        if message.get('role') == 'user'
    ]
    categories = {
        normalize_key(str(item.get('name'))): item
        for item in payload.get('categories', []) if item.get('id') and item.get('name')
    }
    accounts = {
        normalize_key(str(item.get('name'))): item
        for item in payload.get('accounts', []) if item.get('id') and item.get('name')
    }
    signal = payload.get('signal') or {}
    signal_type = signal.get('signal_type')
    expected_kind = {
        'category_mapping': 'category_mapping',
        'account_mapping': 'account_mapping',
        'preference': 'user_preference',
        'split_preference': 'split_person_preference',
    }.get(signal_type)
    subject_hint = normalize_key(str(signal.get('subject_hint') or ''))
    valid: list[dict] = []
    for candidate in parsed.candidates:
        if candidate.kind != expected_kind:
            continue
        evidence = normalize_key(candidate.evidence)
        if not evidence or not any(evidence in quote for quote in user_quotes):
            continue
        subject = normalize_key(candidate.subject)
        if subject_hint and candidate.kind in {'category_mapping', 'account_mapping'} and subject != subject_hint:
            continue
        value = normalize_key(candidate.value)
        if candidate.kind == 'category_mapping':
            selected = categories.get(value)
            if selected is None or not subject:
                continue
            valid.append({
                'scope': 'merchant', 'subject_key': subject, 'memory_type': 'category_mapping',
                'value_json': {'category_id': str(selected['id'])},
            })
        elif candidate.kind == 'account_mapping':
            selected = accounts.get(value)
            if selected is None or not subject:
                continue
            valid.append({
                'scope': 'merchant', 'subject_key': subject, 'memory_type': 'account_mapping',
                'value_json': {'account_id': str(selected['id'])},
            })
        elif candidate.kind in {'user_preference', 'split_person_preference'} and candidate.preference_key:
            valid.append({
                'scope': 'user' if candidate.kind == 'user_preference' else 'person',
                'subject_key': 'user' if candidate.kind == 'user_preference' else subject,
                'memory_type': candidate.kind,
                'value_json': {'key': normalize_key(candidate.preference_key), 'value': candidate.value.strip()},
            })
    return valid[:3]
