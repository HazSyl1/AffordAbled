from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.services.complex_settlement import SettlementInput, calculate_complex_settlement
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.runtime import CreateSettlementDraftToolInput
from app.infrastructure.ai.agents.split import SplitToolset
from app.infrastructure.database.repositories.sqlalchemy_complex_settlement_repository import _preview


def test_ai_settlement_draft_rejects_dropped_digit_in_quoted_charge() -> None:
    request = 'Dinner mains worth ₹12,000 and starters worth ₹6,000.'
    context = HandoffContext(user_id=uuid4(), request=request)
    data = SettlementInput.model_validate({
        'title': 'Dinner', 'participants': ['You', 'A'],
        'bills': [{'id': 'dinner', 'merchant': 'Dinner',
                   'charges': [{'id': 'mains', 'label': 'Mains', 'amount_paise': 120000,
                                'shared_by': ['You', 'A'], 'source_quote': 'mains worth ₹12,000'}],
                   'payments': [{'person': 'You'}]}],
    })
    with pytest.raises(ValueError, match='does not match its quoted source'):
        SplitToolset._validate_settlement_amount_evidence(data, context)

    data.bills[0].charges[0].amount_paise = 1200000
    SplitToolset._validate_settlement_amount_evidence(data, context)


@pytest.mark.parametrize('short_amount', ['12k', '₹12k', '12 K', '12 thousand'])
def test_ai_settlement_draft_expands_short_rupee_amounts(short_amount: str) -> None:
    context = HandoffContext(user_id=uuid4(), request=f'Dinner mains cost {short_amount}.')
    data = SettlementInput.model_validate({
        'title': 'Dinner', 'participants': ['You', 'A'],
        'bills': [{'id': 'dinner', 'merchant': 'Dinner',
                   'charges': [{'id': 'mains', 'label': 'Mains', 'amount_paise': 1200000,
                                'shared_by': ['You', 'A'], 'source_quote': f'mains cost {short_amount}'}],
                   'payments': [{'person': 'You'}]}],
    })
    SplitToolset._validate_settlement_amount_evidence(data, context)
    data.bills[0].charges[0].amount_paise = 120000
    with pytest.raises(ValueError, match='does not match its quoted source'):
        SplitToolset._validate_settlement_amount_evidence(data, context)


def test_ai_settlement_draft_accepts_sum_and_remainder_only_from_exact_quotes() -> None:
    request = 'A had a ₹1,200 burger and ₹800 tea. I paid ₹102 for food including a ₹2 card fee.'
    context = HandoffContext(user_id=uuid4(), request=request)
    data = SettlementInput.model_validate({
        'title': 'Cafe', 'participants': ['You', 'A'],
        'bills': [{'id': 'cafe', 'merchant': 'Cafe', 'charges': [
            {'id': 'a-food', 'label': 'A food', 'amount_paise': 200000, 'shared_by': ['A'],
             'source_quote': '₹1,200 burger and ₹800 tea'},
            {'id': 'other', 'label': 'Other food', 'amount_paise': 10000, 'shared_by': ['You'],
             'source_quote': '₹102 for food including a ₹2 card fee'},
        ], 'payments': [{'person': 'You'}]}],
    })
    SplitToolset._validate_settlement_amount_evidence(data, context)

    data.bills[0].charges[0].source_quote = '₹2,000 burger and tea'
    with pytest.raises(ValueError, match='short, exact source_quote'):
        SplitToolset._validate_settlement_amount_evidence(data, context)


def test_ai_settlement_evidence_distinguishes_people_count_from_money() -> None:
    context = HandoffContext(user_id=uuid4(), request='Mains shared by 6 people cost ₹12,000.')
    data = SettlementInput.model_validate({
        'title': 'Dinner', 'participants': ['You', 'A'],
        'bills': [{'id': 'dinner', 'merchant': 'Dinner',
                   'charges': [{'id': 'mains', 'label': 'Mains', 'amount_paise': 1206000,
                                'shared_by': ['You', 'A'],
                                'source_quote': 'Mains shared by 6 people cost ₹12,000'}],
                   'payments': [{'person': 'You'}]}],
    })
    with pytest.raises(ValueError, match='does not match its quoted source'):
        SplitToolset._validate_settlement_amount_evidence(data, context)


def test_ai_settlement_evidence_accepts_explicit_quantity_and_price() -> None:
    context = HandoffContext(user_id=uuid4(), request='A got 7 drinks at ₹7,000 each.')
    data = SettlementInput.model_validate({
        'title': 'Drinks', 'participants': ['You', 'A'],
        'bills': [{'id': 'bar', 'merchant': 'Bar',
                   'charges': [{'id': 'drinks', 'label': 'Drinks', 'amount_paise': 4900000,
                                'shared_by': ['A'], 'source_quote': '7 drinks at ₹7,000 each'}],
                   'payments': [{'person': 'You'}]}],
    })
    SplitToolset._validate_settlement_amount_evidence(data, context)


def test_ai_settlement_converts_derived_booking_fee_to_calculated_extra() -> None:
    context = HandoffContext(
        user_id=uuid4(), request='Cab: 1800 fare + 2% booking fee split by B C D. B paid the whole cab.'
    )
    data = SettlementInput.model_validate({
        'title': 'Cab', 'participants': ['You', 'B', 'C', 'D'],
        'bills': [{'id': 'cab', 'merchant': 'Cab', 'charges': [
            {'id': 'fare', 'label': 'Fare', 'amount_paise': 180000,
             'shared_by': ['B', 'C', 'D'], 'source_quote': '1800 fare'},
            {'id': 'booking', 'label': 'Booking Fee', 'amount_paise': 3600,
             'shared_by': ['B', 'C', 'D'], 'source_quote': '2% booking fee'},
        ], 'payments': [{'person': 'B', 'covered_charge_ids': ['fare', 'booking']}]}],
    })
    SplitToolset._normalize_percentage_charges(data, context)
    SplitToolset._validate_settlement_amount_evidence(data, context)
    assert [charge.id for charge in data.bills[0].charges] == ['fare']
    assert data.bills[0].extras[0].rate_bps == 200
    assert data.bills[0].extras[0].base_charge_ids == ['fare']
    assert data.bills[0].payments[0].covered_charge_ids == ['fare']
    assert data.bills[0].payments[0].covered_extra_ids == ['booking']
    assert calculate_complex_settlement(data).bills[0]['payment_amounts_paise'] == [183600]


def test_tool_schema_moves_percentage_fee_out_of_charges_before_validation() -> None:
    tool_input = CreateSettlementDraftToolInput.model_validate({'arguments': {'data': {
        'title': 'Cab', 'participants': ['You', 'B', 'C', 'D'],
        'bills': [{'id': 'cab_bill', 'merchant': 'Cab', 'charges': [
            {'id': 'cab_fare', 'label': 'Cab fare', 'source_quote': '1800 fare',
             'amount_paise': 180000, 'shared_by': ['B', 'C', 'D']},
            {'id': 'cab_booking_fee', 'kind': 'fee', 'label': 'Booking fee (2% on fare)',
             'source_quote': '2% booking fee', 'base_charge_ids': ['cab_fare'],
             'rate_bps': 200, 'shared_by': ['B', 'C', 'D']},
        ], 'payments': [{'person': 'B', 'covered_charge_ids': ['cab_fare', 'cab_booking_fee']}]}],
    }}})
    data = tool_input.arguments.data
    context = HandoffContext(user_id=uuid4(), request='Cab: 1800 fare + 2% booking fee. B paid the cab.')
    SplitToolset._validate_settlement_amount_evidence(data, context)
    assert [row.id for row in data.bills[0].charges] == ['cab_fare']
    assert data.bills[0].extras[0].rate_bps == 200
    assert data.bills[0].payments[0].covered_extra_ids == ['cab_booking_fee']
    assert calculate_complex_settlement(data).total_paise == 183600


def test_tool_schema_canonicalizes_owner_across_participants_and_bill_roles() -> None:
    tool_input = CreateSettlementDraftToolInput.model_validate({'arguments': {'data': {
        'title': 'Dinner', 'participants': ['A', 'me', 'B', 'You'],
        'bills': [{'id': 'dinner', 'merchant': 'Dinner', 'charges': [
            {'id': 'food', 'label': 'Food', 'amount_paise': 30000,
             'shared_by': ['A', 'I', 'B'], 'paid_by': 'my card'},
        ], 'discounts': [{'label': '10% dinner coupon', 'charge_ids': ['food'], 'rate_bps': 1000}],
            'payments': [{'person': 'me'}]}],
        'debts': [{'debtor': 'I', 'creditor': 'A', 'amount_paise': 500}],
    }}})
    data = tool_input.arguments.data

    assert data.participants == ['You', 'A', 'B']
    assert data.bills[0].charges[0].shared_by == ['A', 'You', 'B']
    assert data.bills[0].charges[0].paid_by == 'You'
    assert data.bills[0].payments[0].person == 'You'
    assert data.debts[0].debtor == 'You'
    result = calculate_complex_settlement(data)
    assert result.total_paise == 27000
    assert result.shares_paise == {'You': 9000, 'A': 9000, 'B': 9000}
    assert result.paid_paise == {'You': 27000, 'A': 0, 'B': 0}


def test_tool_schema_inserts_owner_but_preserves_other_names() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe', 'participants': ['Sarthak', 'A'],
        'bills': [{'id': 'cafe', 'merchant': 'Cafe', 'charges': [
            {'id': 'tea', 'label': 'Tea', 'amount_paise': 20000,
             'shared_by': ['Sarthak', 'A'], 'paid_by': 'Sarthak'},
        ]}],
    })

    assert data.participants == ['You', 'Sarthak', 'A']
    assert data.bills[0].charges[0].shared_by == ['Sarthak', 'A']
    assert calculate_complex_settlement(data).paid_paise['Sarthak'] == 20000


@pytest.mark.parametrize('mistaken_amount_paise', [200, 3500])
def test_ai_settlement_calculates_booking_fee_from_percentage(mistaken_amount_paise: int) -> None:
    context = HandoffContext(user_id=uuid4(), request='Cab: 1800 fare + 2% booking fee.')
    data = SettlementInput.model_validate({
        'title': 'Cab', 'participants': ['You', 'B'],
        'bills': [{'id': 'cab', 'merchant': 'Cab', 'charges': [
            {'id': 'fare', 'label': 'Fare', 'amount_paise': 180000,
             'shared_by': ['B'], 'paid_by': 'B', 'source_quote': '1800 fare'},
            {'id': 'booking', 'label': 'Booking Fee', 'amount_paise': mistaken_amount_paise,
             'shared_by': ['B'], 'paid_by': 'B', 'source_quote': '2% booking fee'},
        ]}],
    })
    SplitToolset._normalize_percentage_charges(data, context)
    SplitToolset._validate_settlement_amount_evidence(data, context)
    assert data.bills[0].extras[0].rate_bps == 200
    assert calculate_complex_settlement(data).total_paise == 183600


def test_ai_settlement_rejects_percentage_rate_that_does_not_match_quote() -> None:
    context = HandoffContext(user_id=uuid4(), request='Cab: 1800 fare and 2% booking fee.')
    data = SettlementInput.model_validate({
        'title': 'Cab', 'participants': ['You', 'B'],
        'bills': [{'id': 'cab', 'merchant': 'Cab', 'charges': [
            {'id': 'fare', 'label': 'Fare', 'amount_paise': 180000,
             'shared_by': ['B'], 'source_quote': '1800 fare'},
        ], 'extras': [{'id': 'fee', 'kind': 'fee', 'label': 'Booking Fee',
                       'rate_bps': 2, 'base_charge_ids': ['fare'], 'shared_by': ['B'],
                       'source_quote': '2% booking fee'}], 'payments': [{'person': 'B'}]}],
    })
    with pytest.raises(ValueError, match='rate must match the quoted percentage'):
        SplitToolset._validate_settlement_amount_evidence(data, context)


def test_row_payers_create_distinct_payments_without_changing_cost_shares() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe', 'participants': ['You', 'A', 'E'],
        'bills': [{'id': 'cafe', 'merchant': 'Cafe', 'charges': [
            {'id': 'burger', 'label': 'Burger', 'amount_paise': 120000,
             'shared_by': ['A'], 'paid_by': 'A'},
            {'id': 'tea', 'label': 'Tea', 'amount_paise': 80000,
             'shared_by': ['A'], 'paid_by': 'A'},
            {'id': 'shared', 'label': 'Shared food', 'amount_paise': 600000,
             'shared_by': ['You', 'E'], 'paid_by': 'You'},
        ], 'extras': [
            {'id': 'a-tip', 'label': 'A tip', 'kind': 'tip', 'rate_bps': 500,
             'base_charge_ids': ['burger', 'tea'], 'shared_by': ['A'], 'paid_by': 'A'},
            {'id': 'e-tip', 'label': 'E tip', 'kind': 'tip', 'rate_bps': 500,
             'base_charge_ids': ['burger', 'tea', 'shared'],
             'shared_by': ['E'], 'paid_by': 'You'},
        ]}],
    })
    assert [payment.person for payment in data.bills[0].payments] == ['A', 'You']
    result = calculate_complex_settlement(data)
    assert result.paid_paise == {'You': 640000, 'A': 210000, 'E': 0}
    assert result.shares_paise == {'You': 300000, 'A': 210000, 'E': 340000}


def test_row_payers_with_multi_payer_coupon_need_actual_payments() -> None:
    with pytest.raises(ValueError, match='enter each actual payment amount'):
        SettlementInput.model_validate({
            'title': 'Cafe', 'participants': ['You', 'A'],
            'bills': [{'id': 'cafe', 'merchant': 'Cafe', 'charges': [
                {'id': 'a', 'label': 'A food', 'amount_paise': 10000,
                 'shared_by': ['A'], 'paid_by': 'A'},
                {'id': 'mine', 'label': 'My food', 'amount_paise': 10000,
                 'shared_by': ['You'], 'paid_by': 'You'},
            ], 'discounts': [{'label': 'Coupon', 'rate_bps': 1000,
                              'charge_ids': ['a', 'mine']}]}],
        })


def test_ai_settlement_converts_fee_in_coupon_covered_bill() -> None:
    context = HandoffContext(
        user_id=uuid4(),
        request='Dinner had 18k food subtotal (12k mains and 6k starters). '
                '4% service fee on the 18k subtotal. Then 10% coupon on food+fee.',
    )
    data = SettlementInput.model_validate({
        'title': 'Dinner', 'participants': ['You', 'A'],
        'bills': [{'id': 'dinner', 'merchant': 'Dinner', 'charges': [
            {'id': 'mains', 'label': 'Mains', 'amount_paise': 1200000,
             'shared_by': ['You', 'A'], 'source_quote': '12k mains'},
            {'id': 'starters', 'label': 'Starters', 'amount_paise': 600000,
             'shared_by': ['You', 'A'], 'source_quote': '6k starters'},
            {'id': 'fee', 'label': 'Service Fee', 'amount_paise': 72000,
             'shared_by': ['A'], 'source_quote': '4% service fee on the 18k subtotal'},
        ], 'discounts': [{'label': 'Coupon', 'charge_ids': ['mains', 'starters', 'fee'],
                          'rate_bps': 1000, 'source_quote': '10% coupon'}],
            'payments': [{'person': 'You'}]}],
    })
    SplitToolset._normalize_percentage_charges(data, context)
    SplitToolset._validate_settlement_amount_evidence(data, context)
    assert data.bills[0].discounts[0].charge_ids == ['mains', 'starters']
    assert data.bills[0].discounts[0].include_extras is True
    assert calculate_complex_settlement(data).total_paise == 1684800


def test_complete_dinner_cafe_cab_request_keeps_percentage_charges_and_debt_distinct() -> None:
    request = (
        'Dinner had 18k food subtotal (12k mains and 6k starters). '
        '4% service fee on the 18k subtotal; then 10% coupon on food+fee. '
        'Cafe: A had 1200 burger and 800 tea with a 5% tip on that 2k. '
        "Rest 6k food shared by us. E covers an extra tip of 5% on the cafe's full 8k food subtotal. "
        'Cab: 1800 fare + 2% booking fee. Also C owes A 500.'
    )
    context = HandoffContext(user_id=uuid4(), request=request)
    data = SettlementInput.model_validate({
        'title': 'Dinner, cafe and cab', 'participants': ['You', 'A', 'B', 'C', 'D', 'E'],
        'debts': [{'debtor': 'C', 'creditor': 'A', 'amount_paise': 50000}],
        'bills': [
            {'id': 'dinner', 'merchant': 'Dinner', 'charges': [
                {'id': 'mains', 'label': 'Mains', 'amount_paise': 1200000,
                 'shared_by': ['You', 'A', 'B', 'C', 'D', 'E'], 'source_quote': '12k mains'},
                {'id': 'starters', 'label': 'Starters', 'amount_paise': 600000,
                 'shared_by': ['You', 'A', 'B', 'E'], 'source_quote': '6k starters'},
                {'id': 'service', 'label': 'Service Fee', 'amount_paise': 72000,
                 'shared_by': ['A', 'C', 'D', 'E'], 'source_quote': '4% service fee on the 18k subtotal'},
            ], 'discounts': [{'label': 'Coupon', 'charge_ids': ['mains', 'starters', 'service'],
                              'rate_bps': 1000, 'source_quote': '10% coupon'}],
                'payments': [{'person': 'You'}]},
            {'id': 'cafe', 'merchant': 'Cafe', 'charges': [
                {'id': 'burger', 'label': 'Burger', 'amount_paise': 120000,
                 'shared_by': ['A'], 'source_quote': '1200 burger'},
                {'id': 'tea', 'label': 'Tea', 'amount_paise': 80000,
                 'shared_by': ['A'], 'source_quote': '800 tea'},
                {'id': 'shared', 'label': 'Shared Food', 'amount_paise': 600000,
                 'shared_by': ['You', 'B', 'C', 'D', 'E'], 'source_quote': 'Rest 6k food'},
                {'id': 'a-tip', 'label': 'A Tip', 'amount_paise': 10000,
                 'shared_by': ['A'], 'source_quote': '5% tip on that 2k'},
                {'id': 'e-tip', 'label': 'E Extra Tip', 'amount_paise': 40000,
                 'shared_by': ['E'], 'source_quote': "5% on the cafe's full 8k food subtotal"},
            ], 'payments': [
                {'person': 'A', 'covered_charge_ids': ['burger', 'tea', 'a-tip']},
                {'person': 'You', 'covered_charge_ids': ['shared', 'e-tip']},
            ]},
            {'id': 'cab', 'merchant': 'Cab', 'charges': [
                {'id': 'fare', 'label': 'Fare', 'amount_paise': 180000,
                 'shared_by': ['B', 'C', 'D'], 'source_quote': '1800 fare'},
                {'id': 'booking', 'label': 'Booking Fee', 'amount_paise': 3600,
                 'shared_by': ['B', 'C', 'D'], 'source_quote': '2% booking fee'},
            ], 'payments': [{'person': 'B', 'covered_charge_ids': ['fare', 'booking']}]},
        ],
    })
    SplitToolset._normalize_percentage_charges(data, context)
    SplitToolset._validate_settlement_amount_evidence(data, context)
    result = calculate_complex_settlement(data)
    assert [bill['total_paise'] for bill in result.bills] == [1684800, 850000, 183600]
    assert result.total_paise == 2718400
    assert result.paid_paise == {'You': 2324800, 'A': 210000, 'B': 183600,
                                 'C': 0, 'D': 0, 'E': 0}
    assert [(row['debtor'], row['creditor'], row['amount_paise']) for row in result.transfers] == [
        ('E', 'You', 491200), ('C', 'You', 427400), ('D', 'You', 377400),
        ('B', 'You', 312600), ('A', 'You', 281200),
    ]


def test_coupon_starters_and_card_fee_use_distinct_eligible_people() -> None:
    data = SettlementInput.model_validate({
        'title': 'Dinner',
        'participants': ['You', 'A', 'B', 'C', 'D', 'E'],
        'bills': [{
            'id': 'dinner', 'merchant': 'Dinner',
            'charges': [
                {'id': 'starters', 'label': 'Starters', 'amount_paise': 500000,
                 'shared_by': ['You', 'A', 'B', 'E']},
                {'id': 'meal', 'label': 'Other food', 'amount_paise': 1200000,
                 'shared_by': ['You', 'A', 'B', 'C', 'D', 'E']},
            ],
            'discounts': [{'label': 'Coupon', 'charge_ids': ['starters', 'meal'], 'rate_bps': 1000}],
            'extras': [{'label': 'Card fee', 'kind': 'fee', 'rate_bps': 270,
                        'base_charge_ids': ['starters', 'meal'], 'shared_by': ['A', 'C', 'D', 'E']}],
            'payments': [{'person': 'You', 'amount_paise': 1571310}],
            'stated_total_paise': 1571310,
        }],
    })
    result = calculate_complex_settlement(data)
    assert result.total_paise == 1571310
    assert result.bills[0]['rows'][-1]['amount_paise'] == 41310
    assert result.bills[0]['rows'][-1]['allocations'] == {
        'A': 10328, 'C': 10328, 'D': 10327, 'E': 10327,
    }
    assert result.bills[0]['shares_paise']['You'] == 292500
    assert sum(result.shares_paise.values()) == result.total_paise
    assert sum(result.balances_paise.values()) == 0


def test_coupon_after_card_fee_derives_one_payers_final_payment() -> None:
    data = SettlementInput.model_validate({
        'title': 'Swiggy dinner', 'participants': ['You', 'A', 'B', 'C', 'D', 'E'],
        'bills': [{
            'id': 'dinner', 'merchant': 'Swiggy',
            'charges': [{'id': 'meal', 'label': 'Meal', 'amount_paise': 1700000,
                         'shared_by': ['You', 'A', 'B', 'C', 'D', 'E']}],
            'extras': [{'label': 'Card fee', 'kind': 'fee', 'rate_bps': 270,
                        'base_charge_ids': ['meal'], 'shared_by': ['A', 'C', 'D', 'E']}],
            'discounts': [{'label': 'Swiggy coupon', 'charge_ids': ['meal'],
                           'rate_bps': 1000, 'include_extras': True}],
            'payments': [{'person': 'You'}],
        }],
    })
    result = calculate_complex_settlement(data)
    assert result.bills[0]['rows'][-2]['amount_paise'] == 45900
    assert result.bills[0]['rows'][-1]['amount_paise'] == -174590
    assert result.total_paise == 1571310
    assert result.paid_paise['You'] == 1571310
    assert sum(result.shares_paise.values()) == result.total_paise


def test_multiple_payers_must_specify_payment_amounts() -> None:
    data = SettlementInput.model_validate({
        'title': 'Dinner', 'participants': ['You', 'A'],
        'bills': [{'id': 'bill', 'merchant': 'Dinner',
                   'charges': [{'id': 'meal', 'label': 'Meal', 'amount_paise': 10000,
                                'shared_by': ['You', 'A']}],
                   'payments': [{'person': 'You'}, {'person': 'A', 'amount_paise': 5000}]}],
    })
    with pytest.raises(ValueError, match='specify what You paid'):
        calculate_complex_settlement(data)


def test_partial_payment_is_derived_from_item_and_tip_rows() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe XYZ', 'participants': ['You', 'A', 'E'],
        'bills': [{'id': 'xyz', 'merchant': 'Cafe XYZ',
                   'charges': [
                       {'id': 'vada', 'label': 'Vada pav', 'amount_paise': 100000, 'shared_by': ['A']},
                       {'id': 'other', 'label': 'Other food', 'amount_paise': 600000, 'shared_by': ['You']},
                   ],
                   'extras': [{'id': 'a-tip', 'label': "A's 5% tip", 'kind': 'tip',
                               'rate_bps': 500, 'base_charge_ids': ['vada'], 'shared_by': ['E']}],
                   'payments': [
                       {'person': 'A', 'covered_charge_ids': ['vada'], 'covered_extra_ids': ['a-tip']},
                       {'person': 'You', 'amount_paise': 600000},
                   ]}],
    })
    result = calculate_complex_settlement(data)
    assert result.bills[0]['payment_amounts_paise'] == [105000, 600000]
    assert result.shares_paise == {'You': 600000, 'A': 100000, 'E': 5000}
    assert result.transfers == [{'debtor': 'E', 'creditor': 'A', 'amount_paise': 5000}]


def test_covered_rows_cannot_hide_missing_cafe_payer() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe XYZ', 'participants': ['You', 'A'],
        'bills': [{'id': 'xyz', 'merchant': 'Cafe XYZ',
                   'charges': [
                       {'id': 'vada', 'label': 'Vada pav', 'amount_paise': 100000, 'shared_by': ['A']},
                       {'id': 'other', 'label': 'Other food', 'amount_paise': 600000, 'shared_by': ['You']},
                   ],
                   'extras': [{'id': 'a-tip', 'label': "A's 5% tip", 'kind': 'tip',
                               'rate_bps': 500, 'base_charge_ids': ['vada'], 'shared_by': ['A']}],
                   'payments': [{'person': 'A', 'covered_charge_ids': ['vada'],
                                 'covered_extra_ids': ['a-tip']},
                                {'person': 'You', 'amount_paise': 100000}],
                   }],
    })
    with pytest.raises(ValueError, match='₹5,000.00 remains without a payer'):
        calculate_complex_settlement(data)


def test_cafe_row_cannot_be_counted_as_paid_twice() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe XYZ', 'participants': ['You', 'A'],
        'bills': [{'id': 'xyz', 'merchant': 'Cafe XYZ',
                   'charges': [{'id': 'vada', 'label': 'Vada pav', 'amount_paise': 100000,
                                'shared_by': ['A']}],
                   'payments': [{'person': 'A', 'covered_charge_ids': ['vada']},
                                {'person': 'You', 'covered_charge_ids': ['vada']}]}],
    })
    with pytest.raises(ValueError, match='same row more than once'):
        calculate_complex_settlement(data)


def test_covered_row_with_coupon_requires_actual_payment() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe XYZ', 'participants': ['You', 'A'],
        'bills': [{'id': 'xyz', 'merchant': 'Cafe XYZ',
                   'charges': [{'id': 'vada', 'label': 'Vada pav', 'amount_paise': 100000,
                                'shared_by': ['A']}],
                   'discounts': [{'label': 'Coupon', 'charge_ids': ['vada'], 'rate_bps': 1000}],
                   'payments': [{'person': 'A', 'covered_charge_ids': ['vada']},
                                {'person': 'You', 'amount_paise': 1}]}],
    })
    with pytest.raises(ValueError, match='coupon affects covered rows'):
        calculate_complex_settlement(data)


def test_separate_cafe_tip_can_be_covered_by_another_friend() -> None:
    data = SettlementInput.model_validate({
        'title': 'Cafe',
        'participants': ['You', 'A', 'E'],
        'bills': [{
            'id': 'cafe', 'merchant': 'Cafe XYZ',
            'charges': [{'id': 'food', 'label': 'Food', 'amount_paise': 700000,
                         'shared_by': ['A']}],
            'extras': [{'kind': 'tip', 'label': 'Cafe tip', 'rate_bps': 500,
                        'base_paise': 700000, 'shared_by': ['E']}],
            'payments': [{'person': 'A', 'amount_paise': 735000}],
        }],
    })
    result = calculate_complex_settlement(data)
    assert result.shares_paise == {'You': 0, 'A': 700000, 'E': 35000}
    assert result.transfers == [{'debtor': 'E', 'creditor': 'A', 'amount_paise': 35000}]


def test_incomplete_payments_cannot_be_saved_as_a_balancing_remainder() -> None:
    data = SettlementInput.model_validate({
        'title': 'Unknown payment',
        'participants': ['You', 'A'],
        'bills': [{
            'id': 'bill', 'merchant': 'Cafe',
            'charges': [{'id': 'food', 'label': 'Food', 'amount_paise': 10000,
                         'shared_by': ['You', 'A']}],
            'payments': [{'person': 'You', 'amount_paise': 9000}],
        }],
    })
    with pytest.raises(ValueError, match='payments must equal'):
        calculate_complex_settlement(data)


def test_plan_revision_nets_already_settled_transfer() -> None:
    data = SettlementInput.model_validate({
        'title': 'Dinner', 'participants': ['You', 'A', 'B'],
        'bills': [{
            'id': 'dinner', 'merchant': 'Dinner',
            'charges': [{'id': 'meal', 'label': 'Meal', 'amount_paise': 90000,
                         'shared_by': ['You', 'A', 'B']}],
            'payments': [{'person': 'You', 'amount_paise': 90000}],
        }],
    })
    original = _preview(data)
    assert original['transfers'] == [
        {'debtor': 'A', 'creditor': 'You', 'amount_paise': 30000},
        {'debtor': 'B', 'creditor': 'You', 'amount_paise': 30000},
    ]
    prior = SimpleNamespace(transfers=[SimpleNamespace(
        id='settled-transfer', debtor='A', creditor='You', amount_paise=30000,
        settled_at='2026-10-20T12:00:00Z',
    )])
    revised = _preview(data, prior)
    assert revised['transfers'] == [{'debtor': 'B', 'creditor': 'You', 'amount_paise': 30000}]
    assert revised['settled_transfers'][0]['debtor'] == 'A'


def test_multiple_bills_keep_friend_payment_out_of_owner_wallet() -> None:
    data = SettlementInput.model_validate({
        'title': 'Dinner and cafe', 'participants': ['You', 'A', 'E'],
        'bills': [
            {'id': 'dinner', 'merchant': 'Dinner',
             'charges': [{'id': 'meal', 'label': 'Meal', 'amount_paise': 120000,
                          'shared_by': ['You', 'A', 'E']}],
             'payments': [{'person': 'You', 'amount_paise': 120000}]},
            {'id': 'cafe', 'merchant': 'Cafe',
             'charges': [{'id': 'tea', 'label': 'Tea', 'amount_paise': 10000, 'shared_by': ['A']}],
             'extras': [{'kind': 'tip', 'label': 'Tip', 'rate_bps': 500,
                         'base_charge_ids': ['tea'], 'shared_by': ['E']}],
             'payments': [{'person': 'A', 'amount_paise': 10500}]},
        ],
    })
    result = calculate_complex_settlement(data)
    assert result.paid_paise == {'You': 120000, 'A': 10500, 'E': 0}
    assert result.shares_paise == {'You': 40000, 'A': 50000, 'E': 40500}
    assert sum(row['amount_paise'] for row in result.transfers) == 80000
