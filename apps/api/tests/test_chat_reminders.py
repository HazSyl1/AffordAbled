import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.services.chat_service import ChatResponseOutput
from app.infrastructure.ai.agents.contracts import HandoffContext
from app.infrastructure.ai.agents.split import SplitToolset
from app.infrastructure.ai.agents.supervisor_graph import (
    AgenticChatOrchestrator,
    _obvious_specialist,
    _required_tools,
)
from app.presentation.schemas.chat import ChatResponse


def make_split(title='Dinner', *, direction='to_you', settled=0, transaction=True, settlement=None):
    return SimpleNamespace(
        id=uuid.uuid4(), title=title, direction=direction,
        transaction_id=uuid.uuid4() if transaction else None, settlement_breakdown=settlement,
        participants=[SimpleNamespace(id=uuid.uuid4(), name=name, share_paise=5000, settled_paise=settled)
                      for name in ['Rahul', 'Isha']],
    )


@pytest.mark.parametrize('message', [
    'Send Rahul an email reminder for dinner', 'Remind Rahul to pay me',
    'Email a payment request for Dinner', 'Send reminders for the dinner split',
])
def test_reminders_route_to_existing_split_tool(message):
    assert _obvious_specialist(message) == 'split'
    assert _required_tools(message, 'split') == {'prepare_split_reminder'}


@pytest.mark.asyncio
async def test_reminder_targets_requested_person_and_survives_response_serialization():
    split = make_split()
    service = SimpleNamespace(list_for_user=AsyncMock(return_value=[split]))
    context = HandoffContext(user_id=uuid.uuid4(), request='Remind Rahul about dinner')
    result = await SplitToolset(service, None).prepare_split_reminder(
        context, {'person_name': 'rahul', 'title': 'dinner'},
    )
    service.list_for_user.assert_awaited_once_with(context.user_id)
    assert result['status'] == 'awaiting_confirmation'
    assert result['reminder_request'] == {
        'split_id': str(split.id), 'participant_ids': [str(split.participants[0].id)],
    }
    payload = ChatResponseOutput(thread_id='thread', message='Review reminder',
                                 reminder_requests=[result['reminder_request']]).to_public_dict()
    assert ChatResponse.model_validate(payload).model_dump(mode='json')['reminder_requests'] == [
        result['reminder_request'],
    ]


@pytest.mark.asyncio
async def test_ambiguous_reminder_requires_choice_then_resolves_verified_id():
    splits = [make_split('Dinner Friday'), make_split('Dinner Saturday')]
    tool = SplitToolset(SimpleNamespace(list_for_user=AsyncMock(return_value=splits)), None)
    context = HandoffContext(user_id=uuid.uuid4(), request='Remind Rahul')
    with pytest.raises(ValueError, match='More than one split'):
        await tool.prepare_split_reminder(context, {'person_name': 'Rahul'})
    result = await tool.prepare_split_reminder(context, {'split_id': str(splits[1].id)})
    assert result['reminder_request']['split_id'] == str(splits[1].id)


@pytest.mark.parametrize('split', [
    make_split(settled=5000), make_split(direction='by_you', transaction=False),
    make_split(settlement={'transfers': []}),
])
@pytest.mark.asyncio
async def test_ineligible_splits_cannot_prepare_reminders(split):
    tool = SplitToolset(SimpleNamespace(list_for_user=AsyncMock(return_value=[split])), None)
    with pytest.raises(ValueError, match='No matching unpaid'):
        await tool.prepare_split_reminder(HandoffContext(user_id=uuid.uuid4(), request='Reminder for dinner'),
                                          {'title': 'Dinner'})


@pytest.mark.asyncio
async def test_unspecified_reminder_does_not_select_arbitrary_split():
    service = SimpleNamespace(list_for_user=AsyncMock(return_value=[make_split()]))
    with pytest.raises(ValueError, match='Which split or person'):
        await SplitToolset(service, None).prepare_split_reminder(
            HandoffContext(user_id=uuid.uuid4(), request='Send a reminder'), {},
        )
    service.list_for_user.assert_not_awaited()


@pytest.mark.parametrize('interrupted', [False, True])
@pytest.mark.asyncio
async def test_reminder_survives_task_transition_but_waits_for_unfinished_turn(interrupted):
    request = {'split_id': str(uuid.uuid4()), 'participant_ids': [str(uuid.uuid4())]}
    graph = SimpleNamespace(
        invoke=AsyncMock(return_value={
            'reminder_requests': [request], 'results': [], 'tasks_completed': not interrupted,
            '__interrupt__': [SimpleNamespace(value={'question': 'Which account?'})] if interrupted else [],
        }),
        graph=SimpleNamespace(aupdate_state=AsyncMock()),
    )
    response = await AgenticChatOrchestrator(graph).run_turn(
        user_id=uuid.uuid4(), thread_id='reminder-thread', message='Send Rahul a reminder',
    )
    assert response.reminder_requests == ([] if interrupted else [request])
