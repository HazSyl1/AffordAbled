from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


def normalize_key(value: str | None) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip()).casefold()


_SELF_SPLIT_SUBJECTS = {'me', 'myself', 'self', 'you', 'owner', 'my share'}


def is_self_split_subject(value: str | None) -> bool:
    """Return whether a split subject refers to the current user, not a contact."""
    return normalize_key(value) in _SELF_SPLIT_SUBJECTS


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, default=str)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class MemoryCandidate:
    scope: str
    subject_key: str
    memory_type: str
    value_json: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return fingerprint({
            'scope': self.scope,
            'subject_key': self.subject_key,
            'memory_type': self.memory_type,
            'value': self.value_json,
        })


def candidates_for_event(*, action: str, before: dict[str, Any], after: dict[str, Any]) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    extracted = after.get('memory_candidates')
    if action == 'accepted' and isinstance(extracted, list):
        allowed = {
            ('merchant', 'category_mapping'), ('merchant', 'account_mapping'),
            ('user', 'user_preference'), ('person', 'split_person_preference'),
        }
        for item in extracted[:3]:
            if not isinstance(item, dict):
                continue
            scope = str(item.get('scope') or '')
            memory_type = str(item.get('memory_type') or '')
            subject = normalize_key(str(item.get('subject_key') or ''))
            value = item.get('value_json')
            if (scope, memory_type) not in allowed or not subject or not isinstance(value, dict):
                continue
            if memory_type in {'category_mapping', 'account_mapping'}:
                id_key = 'category_id' if memory_type == 'category_mapping' else 'account_id'
                if not value.get(id_key):
                    continue
                candidate_value = {id_key: str(value[id_key])}
            else:
                if not value.get('key') or not value.get('value'):
                    continue
                candidate_value = {'key': str(value['key'])[:80], 'value': str(value['value'])[:160]}
            candidates.append(MemoryCandidate(scope, subject, memory_type, candidate_value))
        return candidates

    merchant = normalize_key(str(after.get('merchant') or before.get('merchant') or ''))
    if action in {'accepted', 'edited'} and merchant:
        if before.get('category_id') != after.get('category_id') and after.get('category_id'):
            candidates.append(MemoryCandidate(
                'merchant', merchant, 'category_mapping', {'category_id': str(after['category_id'])},
            ))
        if before.get('account_id') != after.get('account_id') and after.get('account_id'):
            candidates.append(MemoryCandidate(
                'merchant', merchant, 'account_mapping', {'account_id': str(after['account_id'])},
            ))

    if action in {'accepted', 'edited'}:
        mode = str(after.get('mode') or '')
        for participant in after.get('participants') or []:
            if not isinstance(participant, dict):
                continue
            name = normalize_key(str(participant.get('name') or ''))
            if not name or is_self_split_subject(name) or not mode:
                continue
            value: dict[str, Any] = {'mode': mode}
            if participant.get('share_ratio') is not None:
                value['share_ratio'] = participant['share_ratio']
            candidates.append(MemoryCandidate('person', name, 'split_method', value))
    return candidates
