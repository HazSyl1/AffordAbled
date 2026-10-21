from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.types import Command

from app.application.services.image_service import ImageService
from app.application.services.itemized_split import ItemAllocation, calculate_itemized_split
from app.application.services.quantity_split import QuantityAllocation, calculate_quantity_split
from app.application.services.split_service import ParticipantShare
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.runtime import ToolBoundSpecialistRuntime
from app.infrastructure.ai.agents.split import SplitToolset
from app.infrastructure.ai.agents.supervisor_graph import (
    AgentGraphState,
    _canonicalize_split_task_queue,
    _obvious_specialist,
    _required_tools,
    _split_task_for_request,
    _with_verified_split_total,
)
from tests.helpers import auth_headers, register_and_get_token


def test_itemized_calculation_uses_exact_paise_and_flags_dietary_conflicts() -> None:
    calculation = calculate_itemized_split(
        99000,
        ['Isha', 'Piyush'],
        [
            ItemAllocation('Veg pizza', 30000, ['me', 'Isha'], 'vegetarian'),
            ItemAllocation('Chicken', 45000, ['me', 'Piyush'], 'contains_meat'),
            ItemAllocation('Fries', 15000, ['me', 'Isha', 'Piyush'], 'vegan'),
            ItemAllocation('Tax', 9000, ['me', 'Isha', 'Piyush'], 'shared_charge'),
        ],
        {'isha': 'vegetarian'},
    )
    assert calculation.owner_share_paise == 45500
    assert calculation.participant_shares == {'Isha': 23000, 'Piyush': 30500}
    assert calculation.warnings == []
    assert sum(calculation.participant_shares.values()) + calculation.owner_share_paise == 99000

    conflict = calculate_itemized_split(
        300, ['Isha'], [ItemAllocation('Chicken', 300, ['Isha'], 'contains_meat')],
        {'isha': 'vegetarian'},
    )
    assert 'Isha' in conflict.warnings[0]
    with pytest.raises(ValueError, match='missing ₹0.01'):
        calculate_itemized_split(301, ['Isha'], [ItemAllocation('Pizza', 300, ['me', 'Isha'])])

    with pytest.raises(ValueError, match=r'missing ₹312\.00'):
        calculate_itemized_split(
            404700, ['Isha'], [ItemAllocation('Receipt items', 373500, ['me', 'Isha'])],
        )


def test_itemized_split_includes_owner_by_default_but_honors_explicit_exclusion() -> None:
    calculation = calculate_itemized_split(
        350000,
        ['Shreyas', 'Sudhansu', 'Rujul', 'Sujal'],
        [
            ItemAllocation('Alcohol', 200000, ['Rujul', 'Sudhansu']),
            ItemAllocation('Non-alcoholic items', 150000, ['Rujul', 'Shreyas', 'Sudhansu', 'Sujal']),
        ],
    )

    assert calculation.owner_share_paise == 96667
    assert calculation.participant_shares == {
        'Shreyas': 30000,
        'Sudhansu': 96666,
        'Rujul': 96667,
        'Sujal': 30000,
    }
    assert sum(calculation.participant_shares.values()) + calculation.owner_share_paise == 350000

    owner_did_not_share = calculate_itemized_split(
        10000,
        ['Sujal'],
        [ItemAllocation('Alcohol', 10000, ['Sujal'], owner_excluded=True)],
    )
    assert owner_did_not_share.owner_share_paise == 0
    assert owner_did_not_share.participant_shares == {'Sujal': 10000}


def test_supervisor_keeps_itemized_and_preference_tasks_distinct() -> None:
    itemized = _split_task_for_request('Spent 990 on dinner with Isha and Piyush. Isha had veg pizza.')
    assert itemized is not None and 'itemized split' in itemized
    assert _required_tools(itemized, 'split') == {'create_split'}
    equal = _split_task_for_request('Spent 990 on dinner with Isha and Piyush, split equally.')
    assert equal is not None and 'equal split' in equal
    assert _required_tools('Remember that Isha is vegetarian', 'split') == {'set_split_contact_preference'}
    assert _obvious_specialist('Isha is veg') == 'split'
    assert _obvious_specialist('Piyush eats meat') == 'split'
    assert _required_tools('Piyush eats meat', 'split') == {'set_split_contact_preference'}


def test_split_task_preserves_complete_multi_person_allocation_request() -> None:
    request = (
        'Spent 927383 rs on 7 people: A, B, C, D, E, F, G and myself. '
        'A, B and C got 7 vodka cranberries each, which were 7000 rs each. '
        'Rest of the bill will be divided among everyone equally.'
    )

    task = _split_task_for_request(request)

    assert task is not None
    assert request in task
    assert '927383' in task
    assert '7 vodka cranberries each' in task
    assert 'divided among everyone equally' in task


def test_supervisor_replaces_compressed_split_task_with_full_original_request() -> None:
    request = (
        'Spent 927383 rs on 7 people: A, B, C, D, E, F, G and myself. '
        'A, B and C got 7 vodka cranberries each, which were 7000 rs each. '
        'Rest of the bill will be divided among everyone equally.'
    )

    queue = _canonicalize_split_task_queue(
        ['Record the expense.', 'Split the remainder equally among the group.'],
        request,
    )

    assert len(queue) == 2
    assert queue[0] == request
    assert request in queue[1]
    assert '7000 rs each' in queue[1]
    assert '927383' in queue[1]

    split_only_queue = _canonicalize_split_task_queue(
        ['Split the remainder equally among the group.'],
        request,
    )
    assert split_only_queue[0] == request
    assert len(split_only_queue) == 2
    assert request in split_only_queue[1]


def test_supervisor_collapses_duplicate_remainder_split_tasks() -> None:
    request = (
        'Spent 927383 rs on 7 people: A, B, C, D, E, F, G and myself. '
        'A, B and C got 7 vodka cranberries each at 7000 rs each. '
        'Rest divided equally. A owes C 17000. B contributed 29000. C owes B 20000.'
    )

    queue = _canonicalize_split_task_queue(
        [
            'Record the expense.',
            'Split the full expense with the listed people.',
            'Confirm the split of ₹780,383 equally among everyone with the specified settlement plan.',
            'Remember Isha is vegetarian.',
        ],
        request,
    )

    assert queue[0] == request
    assert sum(_required_tools(task, 'split') == {'create_split'} for task in queue) == 1
    canonical_split_task = next(task for task in queue if _required_tools(task, 'split') == {'create_split'})
    assert request in canonical_split_task
    assert '780,383' not in canonical_split_task
    assert 'Remember Isha is vegetarian.' in queue


def test_pending_split_task_carries_database_verified_transaction_total() -> None:
    task = 'Create an equal split. Original request: spent 100 on dinner.'

    enriched = _with_verified_split_total(task, {'amount_paise': 92738300})

    assert enriched.endswith('Verified recorded transaction total: ₹927,383.00.')


def test_split_rejects_saved_contacts_not_named_in_the_request() -> None:
    context = HandoffContext(
        user_id=uuid.uuid4(),
        request='Spent 2000 on dinner with Isha and Piyush',
        constraints={
            'original_request': 'Spent 2000 on dinner with Isha and Piyush',
            'latest_user_reply': 'Actually include Sarthak too',
        },
    )
    people = [ParticipantShare(name, 0) for name in ('Isha', 'Piyush')]
    SplitToolset._validate_requested_people(people, context)

    SplitToolset._validate_requested_people([*people, ParticipantShare('Sarthak', 0)], context)
    with pytest.raises(ValueError, match='Rahul'):
        SplitToolset._validate_requested_people([*people, ParticipantShare('Rahul', 0)], context)


def test_split_allows_clear_typo_resolution_to_a_saved_contact() -> None:
    context = HandoffContext(
        user_id=uuid.uuid4(),
        request='Spent 2000 on dinner with Piyus',
        constraints={
            'original_request': 'Spent 2000 on dinner with Piyus',
            'available_split_contacts': ['Piyush'],
        },
    )
    SplitToolset._validate_requested_people([ParticipantShare('Piyush', 0)], context)


def test_split_uses_preserved_history_when_specialist_request_is_shortened() -> None:
    context = HandoffContext(
        user_id=uuid.uuid4(),
        request='Create the split for the recorded expense.',
        history=[{
            'role': 'user',
            'content': (
                'Spent 927383 on 7 people: A, B, C, D, E, F, G and myself. '
                'A, B and C got 7 vodka cranberries each at 7000 each.'
            ),
        }],
        constraints={'original_request': 'record the expense and then split it'},
    )
    SplitToolset._validate_requested_people(
        [ParticipantShare(name, 0) for name in 'ABCDEFG'], context,
    )


@pytest.mark.asyncio
async def test_receipt_ocr_keeps_item_lines_within_chat_request_limit() -> None:
    class FakeOcr:
        async def analyze(self, _image: bytes, *, content_type: str) -> str:
            assert content_type == 'image/png'
            return '\n'.join(f'Item {index} 10.00' for index in range(500))

    result = await ImageService(FakeOcr()).analyze_image(
        b'png', content_type='image/png', filename='dinner.png',
    )
    assert 'Item 0 10.00\nItem 1 10.00' in result.prompt
    assert 'exactly one transaction' in result.prompt
    assert 'final grand total' in result.prompt
    assert 'ask me to confirm it' in result.prompt
    assert len(result.prompt) < 8000
    assert _split_task_for_request(result.prompt) is None


@pytest.mark.asyncio
async def test_chat_itemized_split_requires_review_before_create(monkeypatch: pytest.MonkeyPatch) -> None:
    transaction_id = uuid.uuid4()
    saved: list[tuple] = []
    questions: list[str] = []

    class FakeSplits:
        async def list_contact_preferences(self, _user_id):
            return [SimpleNamespace(normalized_name='isha', dietary_preference='vegetarian')]

        async def create(self, *args):
            saved.append(args)
            return SimpleNamespace(
                id=uuid.uuid4(), transaction_id=transaction_id, title=args[2], owner_share_paise=args[6],
                participants=[SimpleNamespace(name=person.name, share_paise=person.share_paise)
                              for person in args[5]],
            )

    class FakeTransactions:
        async def get_transaction(self, _user_id, _transaction_id):
            return SimpleNamespace(id=transaction_id, type=SimpleNamespace(value='expense'),
                                   amount_paise=30000, merchant='Dinner', note=None)

    def confirm(payload):
        questions.append(payload['question'])
        return 'yes'

    monkeypatch.setattr('app.infrastructure.ai.agents.split.interrupt', confirm)
    toolset = SplitToolset(FakeSplits(), FakeTransactions())
    context = HandoffContext(user_id=uuid.uuid4(), request='Split the veg meal with Isha',
                             constraints={'created_transaction_ids': [str(transaction_id)]})
    result = await toolset.create_split(context, {
        'participants': ['Isha'],
        'items': [{'name': 'Veg meal', 'amount_paise': 30000,
                   'shared_by': ['me', 'Isha'], 'food_type': 'vegetarian'}],
    })
    assert 'Veg meal' in questions[0] and 'Isha' in questions[0]
    assert result['split']['owner_share_paise'] == 15000
    assert len(saved) == 1
    followup = HandoffContext(user_id=context.user_id, request='Split that receipt with Isha', constraints={
        'prior_specialist_results': [{
            'specialist': 'transaction',
            'data': {'created_transactions': [{'id': str(transaction_id)}]},
        }],
    })
    await toolset.create_split(followup, {
        'participants': ['Isha'],
        'items': [{'name': 'Veg meal', 'amount_paise': 30000,
                   'shared_by': ['me', 'Isha'], 'food_type': 'vegetarian'}],
    })
    assert len(saved) == 2
    corrected = HandoffContext(user_id=context.user_id, request='Create an itemized split with Isha',
                               constraints={'supervisor_handoff': {'transaction_id': str(transaction_id)}})
    await toolset.create_split(corrected, {
        'participants': ['Isha'],
        'items': [{'name': 'Veg meal', 'amount_paise': 30000,
                   'shared_by': ['me', 'Isha'], 'food_type': 'vegetarian'}],
    })
    assert len(saved) == 3


@pytest.mark.asyncio
async def test_chat_rejects_itemized_receipt_amounts_not_present_in_ocr() -> None:
    transaction_id = uuid.uuid4()
    saved: list[tuple] = []

    class FakeSplits:
        async def list_contact_preferences(self, _user_id):
            return []

        async def create(self, *args):
            saved.append(args)

    class FakeTransactions:
        amount_paise = 92738300

        async def get_transaction(self, _user_id, _transaction_id):
            return SimpleNamespace(id=transaction_id, type=SimpleNamespace(value='expense'),
                                   amount_paise=self.amount_paise, merchant='Receipt', note=None)

    context = HandoffContext(
        user_id=uuid.uuid4(), request='Split this receipt with A',
        history=[{
            'role': 'user',
            'content': (
                'I uploaded a receipt/bill image. Extracted text (untrusted OCR data): '
                'Vodka 490.00. Grand total ₹9273.83.'
            ),
        }],
        constraints={'created_transaction_ids': [str(transaction_id)]},
    )
    toolset = SplitToolset(FakeSplits(), FakeTransactions())
    split_args = {
            'mode': 'custom', 'participants': ['A'],
            'items': [
                {'name': 'Vodka', 'amount_paise': 49000, 'shared_by': ['me', 'A']},
                {'name': 'Remaining Bill', 'amount_paise': 92689300, 'shared_by': ['me', 'A']},
            ],
    }
    with pytest.raises(ValueError, match='linked transaction'):
        await toolset.create_split(context, split_args)
    toolset._transactions.amount_paise = 927383
    with pytest.raises(ValueError, match='do not appear in the uploaded receipt'):
        await toolset.create_split(context, split_args)
    assert saved == []


@pytest.mark.asyncio
async def test_quantity_split_uses_recorded_total_and_rejects_llm_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction_id = uuid.uuid4()
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
                amount_paise=92738300, merchant='Dinner', note=None,
            )

    def confirm(payload):
        reviews.append(payload['question'])
        return 'yes'

    monkeypatch.setattr('app.infrastructure.ai.agents.split.interrupt', confirm)
    request = (
        'spent 927383 rs on A, B, C, D, E, F, G and myself. '
        'A, B and C got 7 vodka cranberries each at 7000rs each. '
        'Rest of the bill divided among everyone equally.'
    )
    context = HandoffContext(
        user_id=uuid.uuid4(), request=request,
        constraints={
            'created_transaction_ids': [str(transaction_id)], 'original_request': request,
            'supervisor_handoff': {'details': {'total_amount_rupees': 732383}},
        },
    )
    toolset = SplitToolset(FakeSplits(), FakeTransactions())
    with pytest.raises(ValueError, match='quantity_allocations'):
        await toolset.create_split(context, {
            'participants': list('ABCDEFG'), 'mode': 'custom',
            'items': [{'name': 'Remaining Bill', 'amount_paise': 73238300,
                       'shared_by': ['me', *list('ABCDEFG')]}],
        })
    with pytest.raises(ValueError, match='match numbers in the user request'):
        await toolset.create_split(context, {
            'participants': list('ABCDEFG'),
            'quantity_allocations': [{
                'people': ['A', 'B', 'C'], 'quantity_per_person': 7,
                'unit_price_rupees': 65000,
            }],
        })
    result = await toolset.create_split(context, {
        'participants': list('ABCDEFG'), 'mode': 'custom',
        'quantity_allocations': [{
            'people': ['A', 'B', 'C'], 'quantity_per_person': 7,
            'unit_price_rupees': 7000,
        }],
    })
    assert '₹780,383.00' in reviews[0]
    assert result['split']['total_paise'] == 92738300
    assert result['split']['owner_share_paise'] == 9754788
    assert result['split']['participants'][0]['share_paise'] == 14654788
    assert result['split']['participants'][-1]['share_paise'] == 9754787
    assert len(saved) == 1


def test_quantity_split_rejects_fixed_items_above_total() -> None:
    with pytest.raises(ValueError, match='exceed'):
        calculate_quantity_split(
            10000, ['A'], [QuantityAllocation(['A'], quantity_per_person=2, unit_price_paise=6000)],
        )


@pytest.mark.asyncio
async def test_chat_can_record_standalone_money_owed_without_transaction() -> None:
    captured: list[tuple] = []

    class FakeSplits:
        async def create_owed(self, user_id, title, name, amount_paise):
            captured.append((user_id, title, name, amount_paise))
            return SimpleNamespace(
                id=uuid.uuid4(), title=title,
                participants=[SimpleNamespace(name='Isha', share_paise=amount_paise)],
            )

    user_id = uuid.uuid4()
    context = HandoffContext(user_id=user_id, request='Isha owes me 500 for tickets')
    toolset = SplitToolset(FakeSplits(), SimpleNamespace())
    result = await toolset.create_owed(context, {
        'name': 'isha', 'title': 'Concert tickets', 'amount_paise': 50000,
    })

    assert result['receivable']['kind'] == 'money_owed'
    assert result['receivable']['person'] == 'Isha'
    assert result['receivable']['amount_paise'] == 50000
    assert captured == [(user_id, 'Concert tickets', 'isha', 50000)]
    assert _obvious_specialist(context.request) == 'split'
    assert _required_tools(context.request, 'split') == {'create_owed'}


@pytest.mark.asyncio
async def test_chat_split_never_saves_owner_as_external_participant() -> None:
    transaction_id = uuid.uuid4()
    saved: list[tuple] = []

    class FakeSplits:
        async def create(self, *args):
            saved.append(args)
            return SimpleNamespace(
                id=uuid.uuid4(), transaction_id=transaction_id, title=args[2], owner_share_paise=5000,
                participants=[SimpleNamespace(name=person.name, share_paise=person.share_paise)
                              for person in args[5]],
            )

    class FakeTransactions:
        async def get_transaction(self, _user_id, _transaction_id):
            return SimpleNamespace(id=transaction_id, type=SimpleNamespace(value='expense'),
                                   amount_paise=10000, merchant='Dinner', note=None)

    context = HandoffContext(
        user_id=uuid.uuid4(), request='Split dinner with me and Isha',
        constraints={'created_transaction_ids': [str(transaction_id)]},
    )
    result = await SplitToolset(FakeSplits(), FakeTransactions()).create_split(context, {
        'participants': ['Me', 'Isha'], 'mode': 'equal',
    })

    assert len(saved) == 1
    assert [person.name for person in saved[0][5]] == ['Isha']
    assert result['split']['participants'] == [{'name': 'Isha', 'share_paise': 0}]


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,expected_saves', [
    ('yes', 1), ('No, Isha did not share the meal', 0),
])
async def test_itemized_split_tool_pauses_and_resumes_inside_graph(answer: str, expected_saves: int) -> None:
    transaction_id = uuid.uuid4()
    user_id = uuid.uuid4()
    saves: list[tuple] = []

    class FakeSplits:
        async def list_contact_preferences(self, _user_id):
            return []

        async def create(self, *args):
            saves.append(args)
            return SimpleNamespace(
                id=uuid.uuid4(), transaction_id=transaction_id, title=args[2], owner_share_paise=args[6],
                participants=[SimpleNamespace(name=person.name, share_paise=person.share_paise)
                              for person in args[5]],
            )

    class FakeTransactions:
        async def get_transaction(self, _user_id, _transaction_id):
            return SimpleNamespace(id=transaction_id, type=SimpleNamespace(value='expense'),
                                   amount_paise=30000, merchant='Dinner', note=None)

    class FakeModel:
        def bind_tools(self, _tools):
            async def respond(messages):
                if isinstance(messages[-1], ToolMessage):
                    if '"ok": false' in str(messages[-1].content):
                        return AIMessage(content='The split was not saved. Please correct the items.')
                    return AIMessage(content='The reviewed itemized split was saved.')
                return AIMessage(content='', tool_calls=[{
                    'name': 'create_split', 'id': 'itemized-split', 'args': {'arguments': {
                        'participants': ['Isha'],
                        'items': [{'name': 'Veg meal', 'amount_paise': 30000,
                                   'shared_by': ['me', 'Isha'], 'food_type': 'vegetarian'}],
                    }},
                }])

            return RunnableLambda(respond)

    runtime = ToolBoundSpecialistRuntime(
        name='split', llm=FakeModel(), system_prompt='You are the split specialist.',
        tools=SplitToolset(FakeSplits(), FakeTransactions()).registry(),
    )
    parent = StateGraph(AgentGraphState)
    parent.add_node('split', runtime.build_persistent_subgraph(AgentGraphState))
    parent.add_edge(START, 'split')
    graph = parent.compile(checkpointer=MemorySaver())
    config = {'configurable': {'thread_id': str(uuid.uuid4())}}
    initial = await graph.ainvoke({
        'user_id': str(user_id), 'task_request': 'Create an itemized split with Isha',
        'task_queue': ['Create an itemized split with Isha'],
        'created_transaction_ids': [str(transaction_id)],
        'specialist_messages': [SystemMessage(content='Split specialist'), HumanMessage(content='Dinner with Isha')],
    }, config)
    assert initial.get('__interrupt__')
    assert saves == []
    resumed = await graph.ainvoke(Command(resume=answer), config)
    assert len(saves) == expected_saves
    assert resumed['results'][-1]['status'] == ('success' if expected_saves else 'partial')
    if not expected_saves:
        assert answer in resumed['results'][-1]['errors'][0]


@pytest.mark.asyncio
async def test_confirmed_split_save_failure_does_not_restart_confirmation() -> None:
    transaction_id = uuid.uuid4()
    user_id = uuid.uuid4()
    save_attempts = 0

    class FailingSplits:
        async def list_contact_preferences(self, _user_id):
            return []

        async def create(self, *_args):
            nonlocal save_attempts
            save_attempts += 1
            raise RuntimeError('settlement_breakdown column is missing')

    class FakeTransactions:
        async def get_transaction(self, _user_id, _transaction_id):
            return SimpleNamespace(
                id=transaction_id, type=SimpleNamespace(value='expense'),
                amount_paise=30000, merchant='Dinner', note=None,
            )

    class FakeModel:
        def bind_tools(self, _tools):
            async def respond(messages):
                if isinstance(messages[-1], ToolMessage):
                    return AIMessage(content='The split could not be saved.')
                return AIMessage(content='', tool_calls=[{
                    'name': 'create_split', 'id': 'itemized-split-save-failure', 'args': {'arguments': {
                        'participants': ['Isha'],
                        'items': [{'name': 'Dinner', 'amount_paise': 30000,
                                   'shared_by': ['me', 'Isha'], 'food_type': 'unknown'}],
                    }},
                }])

            return RunnableLambda(respond)

    runtime = ToolBoundSpecialistRuntime(
        name='split', llm=FakeModel(), system_prompt='You are the split specialist.',
        tools=SplitToolset(FailingSplits(), FakeTransactions()).registry(),
        non_retryable_tools={'create_split'},
    )
    parent = StateGraph(AgentGraphState)
    parent.add_node('split', runtime.build_persistent_subgraph(AgentGraphState))
    parent.add_edge(START, 'split')
    graph = parent.compile(checkpointer=MemorySaver())
    config = {'configurable': {'thread_id': str(uuid.uuid4())}}
    initial = await graph.ainvoke({
        'user_id': str(user_id), 'task_request': 'Create an itemized split with Isha',
        'task_queue': ['Create an itemized split with Isha'],
        'created_transaction_ids': [str(transaction_id)],
        'specialist_messages': [SystemMessage(content='Split specialist'), HumanMessage(content='Dinner with Isha')],
    }, config)
    assert initial.get('__interrupt__')

    resumed = await graph.ainvoke(Command(resume='yes'), config)

    assert not resumed.get('__interrupt__')
    assert save_attempts == 1
    assert resumed['results'][-1]['status'] == 'partial'
    assert 'settlement_breakdown column is missing' in resumed['results'][-1]['errors'][0]


@pytest.mark.asyncio
async def test_contact_memory_and_itemized_split_are_user_scoped(client: AsyncClient) -> None:
    owner = await register_and_get_token(client, 'itemized-owner@example.com')
    other = await register_and_get_token(client, 'itemized-other@example.com')
    headers = auth_headers(owner)
    preference = await client.put('/api/v1/splits/contacts/preferences', json={
        'name': 'Isha', 'dietary_preference': 'vegetarian',
    }, headers=headers)
    assert preference.status_code == 200, preference.text
    contact_id = preference.json()['id']
    assert preference.json()['dietary_preference'] == 'vegetarian'
    assert (await client.get('/api/v1/splits/contacts/preferences', headers=auth_headers(other))).json() == []
    assert (await client.delete(f'/api/v1/splits/contacts/preferences/{contact_id}',
                                headers=auth_headers(other))).status_code == 404

    account = await client.post('/api/v1/accounts', json={
        'name': 'Wallet', 'type': 'wallet', 'balance_paise': 200000, 'currency': 'INR',
    }, headers=headers)
    category = await client.post('/api/v1/categories', json={'name': 'Food', 'type': 'expense'}, headers=headers)
    assert account.status_code == category.status_code == 201
    transaction = await client.post('/api/v1/transactions', json={
        'account_id': account.json()['id'], 'category_id': category.json()['id'],
        'type': 'expense', 'amount_paise': 99000, 'occurred_at': '2026-10-17T12:00:00+00:00',
    }, headers=headers)
    assert transaction.status_code == 201, transaction.text
    payload = {
        'transaction_id': transaction.json()['id'], 'title': 'Dinner', 'amount_paise': 99000,
        'participants': ['Isha', 'Piyush'],
        'items': [
            {'name': 'Veg pizza', 'amount_paise': 30000, 'shared_by': ['me', 'Isha'], 'food_type': 'vegetarian'},
            {'name': 'Chicken', 'amount_paise': 45000, 'shared_by': ['me', 'Piyush'], 'food_type': 'contains_meat'},
            {'name': 'Fries', 'amount_paise': 15000, 'shared_by': ['me', 'Isha', 'Piyush'], 'food_type': 'vegan'},
            {'name': 'Tax', 'amount_paise': 9000, 'shared_by': ['me', 'Isha', 'Piyush'], 'food_type': 'shared_charge'},
        ],
    }
    preview = await client.post('/api/v1/splits/itemized/preview', json=payload, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()['participant_shares'] == {'Isha': 23000, 'Piyush': 30500}
    assert (await client.post('/api/v1/splits/itemized', json=payload, headers=headers)).status_code == 422
    created = await client.post('/api/v1/splits/itemized', json={**payload, 'confirmed': True}, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()['owner_share_paise'] == 45500
    assert len(created.json()['item_breakdown']) == 4
    assert (await client.get(f"/api/v1/splits/{created.json()['id']}",
                             headers=auth_headers(other))).status_code == 404
    removed = await client.delete(f'/api/v1/splits/contacts/preferences/{contact_id}', headers=headers)
    assert removed.status_code == 204
    for day in (18, 19):
        another_transaction = await client.post('/api/v1/transactions', json={
            'account_id': account.json()['id'], 'category_id': category.json()['id'],
            'type': 'expense', 'amount_paise': 30000,
            'occurred_at': f'2026-10-{day}T12:00:00+00:00',
        }, headers=headers)
        assert another_transaction.status_code == 201
        another_split = await client.post('/api/v1/splits/itemized', json={
            'transaction_id': another_transaction.json()['id'], 'title': 'Veg meal',
            'amount_paise': 30000, 'participants': ['Isha'], 'confirmed': True,
            'items': [{'name': 'Veg meal', 'amount_paise': 30000,
                       'shared_by': ['me', 'Isha'], 'food_type': 'vegetarian'}],
        }, headers=headers)
        assert another_split.status_code == 201, another_split.text
    suggestions = await client.get('/api/v1/splits/contacts/preference-suggestions', headers=headers)
    assert suggestions.json() == [
        {'name': 'Isha', 'suggested_preference': 'vegetarian', 'evidence_splits': 3},
    ]
    assert (await client.get('/api/v1/splits/contacts/preference-suggestions',
                             headers=auth_headers(other))).json() == []
