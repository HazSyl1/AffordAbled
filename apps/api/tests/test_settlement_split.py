from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.application.services.quantity_split import QuantityAllocation
from app.application.services.settlement_split import (
    SettlementDebt,
    SplitContribution,
    calculate_settlement_split,
)
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.split import SplitToolset


def test_quantity_allocations_support_multiple_groups_and_overlapping_people() -> None:
    calculation = calculate_settlement_split(
        total_paise=26_500_000,
        participant_names=['A', 'B', 'C', 'D'],
        allocations=[
            QuantityAllocation(['A', 'B', 'C'], quantity_per_person=7, unit_price_paise=700_000),
            QuantityAllocation(['C', 'D'], quantity_per_person=3, unit_price_paise=300_000),
        ],
        contributions=[],
        debts=[],
    )

    assert calculation.priced_items_paise == 16_500_000
    assert calculation.remainder_paise == 10_000_000
    assert calculation.owner_share_paise == 2_000_000
    assert calculation.participant_shares == {
        'A': 6_900_000,
        'B': 6_900_000,
        'C': 7_800_000,
        'D': 2_900_000,
    }
    assert calculation.owner_share_paise + sum(calculation.participant_shares.values()) == 26_500_000


def test_debts_and_contributions_are_netted_into_exact_transfers() -> None:
    calculation = calculate_settlement_split(
        total_paise=92_738_300,
        participant_names=list('ABCDEFG'),
        allocations=[QuantityAllocation(['A', 'B', 'C'], 7, 700_000)],
        contributions=[SplitContribution('B', 2_900_000)],
        debts=[
            SettlementDebt('A', 'C', 1_700_000),
            SettlementDebt('C', 'B', 2_000_000),
        ],
    )

    assert calculation.owner_share_paise == 9_754_788
    assert calculation.participant_shares['A'] == 14_654_788
    assert calculation.participant_shares['B'] == 14_654_788
    assert calculation.participant_shares['C'] == 14_654_788
    assert sum(item.amount_paise for item in calculation.transfers) == 80_083_512
    assert {item.debtor for item in calculation.transfers} == set('ABCDEFG')
    assert {item.creditor for item in calculation.transfers} == {'You'}
    assert calculation.contributions == [SplitContribution('B', 2_900_000)]


def test_settlement_calculator_rejects_unknown_people_and_overpayment() -> None:
    with pytest.raises(ValueError, match='listed split participant'):
        calculate_settlement_split(
            10_000, ['A'], [], [], [SettlementDebt('A', 'Unknown', 100)],
        )

    with pytest.raises(ValueError, match='cannot exceed'):
        calculate_settlement_split(
            10_000, ['A'], [], [SplitContribution('A', 10_001)], [],
        )


def test_equal_expense_can_include_contributions_and_existing_debts() -> None:
    calculation = calculate_settlement_split(
        total_paise=3_000_000,
        participant_names=['A', 'B'],
        allocations=[],
        contributions=[SplitContribution('B', 1_000_000)],
        debts=[SettlementDebt('A', 'B', 500_000)],
    )

    assert calculation.owner_share_paise == 1_000_000
    assert calculation.participant_shares == {'A': 1_000_000, 'B': 1_000_000}
    assert [(item.debtor, item.creditor, item.amount_paise) for item in calculation.transfers] == [
        ('A', 'You', 1_000_000), ('A', 'B', 500_000),
    ]


@pytest.mark.asyncio
async def test_chat_split_reviews_and_persists_exact_settlement_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    transaction_id = uuid.uuid4()
    user_id = uuid.uuid4()
    saved: list[tuple] = []
    reviews: list[str] = []

    class FakeSplits:
        async def create(self, *args):
            saved.append(args)
            return SimpleNamespace(
                id=uuid.uuid4(), transaction_id=transaction_id, title=args[2],
                owner_share_paise=args[6], participants=[
                    SimpleNamespace(name=person.name, share_paise=person.share_paise)
                    for person in args[5]
                ],
            )

    class FakeTransactions:
        async def get_transaction(self, _user_id, _transaction_id):
            return SimpleNamespace(
                id=transaction_id, type=SimpleNamespace(value='expense'),
                amount_paise=92_738_300, merchant='Dinner', note=None,
            )

    def confirm(payload):
        reviews.append(payload['question'])
        return 'yes'

    monkeypatch.setattr('app.infrastructure.ai.agents.split.interrupt', confirm)
    request = (
        'Spent 927383 rs on 7 people A B C D E F G and myself. A B and C got 7 vodka cranberries '
        'each at 7000 rs each. Rest divided equally. A owes C 17000. B contributed 29000. C owes B 20000.'
    )
    context = HandoffContext(
        user_id=user_id, request=request,
        constraints={'created_transaction_ids': [str(transaction_id)], 'original_request': request},
    )
    result = await SplitToolset(FakeSplits(), FakeTransactions()).create_split(context, {
        'participants': list('ABCDEFG'),
        'quantity_allocations': [{
            'item_name': 'Vodka cranberry', 'people': ['A', 'B', 'C'],
            'quantity_per_person': 7, 'unit_price_rupees': Decimal('7000'),
        }],
        'debts': [
            {'debtor': 'A', 'creditor': 'C', 'amount_rupees': Decimal('17000')},
            {'debtor': 'C', 'creditor': 'B', 'amount_rupees': Decimal('20000')},
        ],
        'contributions': [{'person': 'B', 'amount_rupees': Decimal('29000')}],
    })

    assert 'A pays You ₹163,547.88' in reviews[0]
    assert 'B pays You ₹97,547.88' in reviews[0]
    assert 'C pays You ₹149,547.88' in reviews[0]
    assert len(saved) == 1
    assert saved[0][8]['contributions'] == [{'person': 'B', 'amount_paise': 2_900_000}]
    assert saved[0][8]['quantity_allocations'][0]['item_name'] == 'Vodka cranberry'
    assert result['split']['settlement_breakdown'] == saved[0][8]
