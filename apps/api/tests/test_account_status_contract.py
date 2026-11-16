import pytest

from app.infrastructure.ai.agents.contracts import TaskContract
from app.infrastructure.ai.agents.supervisor_graph import (
    _obvious_specialist,
    _required_tools,
    _sync_task_contracts,
    _verify_task_contract,
)


@pytest.mark.parametrize('task_text', ['Account status', 'SBI account status', 'Show my account status'])
def test_account_status_requires_account_read(task_text):
    assert _obvious_specialist(task_text) == 'account'
    contract = TaskContract.model_validate(_sync_task_contracts([task_text], None, original_request=task_text)[0])
    assert contract.required_tools == ['list_accounts']
    assert contract.required_evidence == ['list_accounts:accounts']
    assert contract.intent == 'list_accounts'


@pytest.mark.parametrize('accounts', [[], [{'name': 'SBI', 'balance_paise': 6480200}]])
def test_account_status_completes_only_with_successful_task_bound_read(accounts):
    request = 'Account status'
    contract = TaskContract.model_validate(_sync_task_contracts([request], None, original_request=request)[0])
    result = {'status': 'success', 'task_id': contract.id, 'tool_observations': []}
    assert not _verify_task_contract(contract, result)
    observation = {'tool': 'list_accounts', 'ok': True, 'task_id': contract.id, 'data': {'accounts': accounts}}
    result['tool_observations'] = [observation]
    assert _verify_task_contract(contract, result)
    observation['ok'] = False
    assert not _verify_task_contract(contract, result)
    observation['ok'] = True
    observation['task_id'] = 'different-task'
    assert not _verify_task_contract(contract, result)


@pytest.mark.parametrize(('task_text', 'tools'), [
    ('Deactivate SBI account status', {'deactivate_account', 'update_account'}),
    ('Activate SBI account', {'activate_account', 'update_account'}),
    ('Show how to rename SBI account', {'rename_account', 'update_account'}),
    ('Delete SBI account', {'delete_account'}),
])
def test_account_status_read_does_not_override_mutation_requirements(task_text, tools):
    assert _required_tools(task_text, 'account') == tools
