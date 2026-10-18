from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


def normalize_key(value: str | None) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip()).casefold()


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
            if not name or not mode:
                continue
            value: dict[str, Any] = {'mode': mode}
            if participant.get('share_ratio') is not None:
                value['share_ratio'] = participant['share_ratio']
            candidates.append(MemoryCandidate('person', name, 'split_method', value))
    return candidates
