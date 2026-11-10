from __future__ import annotations

import argparse

import httpx
import pytest

from scripts.evaluate_latency import Sample, evaluate, measure, percentile, summarize


def test_percentiles_and_failures_do_not_hide_empty_or_small_samples() -> None:
    assert percentile([], 99) is None
    assert percentile([7], 99) == 7
    assert percentile(list(range(1, 101)), 50) == 50
    assert percentile(list(range(1, 101)), 99) == 99
    summary = summarize([Sample('accounts', 10, True), Sample('accounts', 100, False, error='timeout')])
    assert summary['accounts']['error_rate'] == 0.5
    assert summary['accounts']['success_latency_ms']['p99'] == 10
    assert summary['accounts']['all_attempts_p99_ms'] == 100
    assert 'preliminary' in summary['accounts']['p99_confidence']
    failed = summarize([Sample('chat', 100, False, error='timeout')])
    assert failed['chat']['success_latency_ms']['p50'] is None


@pytest.mark.parametrize('status', [401, 429, 500])
async def test_http_errors_are_reported_instead_of_counting_as_fast_successes(status: int) -> None:
    async with httpx.AsyncClient(
        base_url='http://test', transport=httpx.MockTransport(lambda _: httpx.Response(status)),
    ) as client:
        row = await measure(client, 'accounts')
    assert not row.successful
    assert row.error == f'http_{status}'


async def test_chat_measures_completion_and_preserves_thread_across_sequential_turns() -> None:
    submissions = []
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.method == 'POST':
            import json
            submissions.append(json.loads(request.content))
            return httpx.Response(202, json={'status': 'queued'}, headers={'X-Request-ID': 'trace-id'})
        polls += 1
        return httpx.Response(200, json={
            'status': 'succeeded', 'result': {'message': 'Your balance is available.'},
            'created_at': '2026-11-10T12:00:00+00:00', 'claimed_at': '2026-11-10T12:00:00.100000+00:00',
            'completed_at': '2026-11-10T12:00:02+00:00', 'updated_at': '2026-11-10T12:00:02+00:00',
        })

    async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handler)) as client:
        row = await measure(client, 'chat', poll_seconds=0.001, messages=['My balance?', 'And this month?'])
    assert row.successful and polls == 2
    assert submissions[0]['thread_id'] == submissions[1]['thread_id']
    assert submissions[0]['turn_id'] != submissions[1]['turn_id']
    assert row.server_turn_ms == 4000
    assert row.queue_wait_ms == 200
    assert row.processing_ms == 3800
    assert row.request_id == 'trace-id'


async def test_queued_chat_hits_total_deadline_without_resubmitting() -> None:
    submissions = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal submissions
        submissions += request.method == 'POST'
        return httpx.Response(202 if request.method == 'POST' else 200, json={'status': 'queued'})

    async with httpx.AsyncClient(base_url='http://test', transport=httpx.MockTransport(handler)) as client:
        row = await measure(client, 'chat', deadline_seconds=0.02, poll_seconds=0.001)
    assert row.error == 'timeout' and not row.successful
    assert submissions == 1


async def test_failed_chat_job_is_an_error_even_if_http_poll_succeeded() -> None:
    async with httpx.AsyncClient(
        base_url='http://test',
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'status': 'failed'})),
    ) as client:
        row = await measure(client, 'chat')
    assert row.error == 'chat_failed' and not row.successful


async def test_runner_excludes_warmup_and_does_not_include_credentials_in_report(monkeypatch) -> None:
    calls = []
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[], headers={'X-Request-ID': 'request-1'})

    def client_factory(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setenv('PERF_ACCESS_TOKEN', 'secret-test-token')
    monkeypatch.setattr('scripts.evaluate_latency.httpx.AsyncClient', client_factory)
    args = argparse.Namespace(
        scenarios='accounts', allow_chat=False, base_url='http://localhost:8000',
        timeout=2, concurrency=2, warmup=2, samples=5, poll_seconds=0.01, pause=0,
        chat_message=None, environment='local', revision='test',
    )
    report = await evaluate(args)
    assert len(calls) == 7
    assert len(report['samples']) == 5
    assert report['summary']['accounts']['successful'] == 5
    assert all(request.headers['Authorization'] == 'Bearer secret-test-token' for request in calls)
    assert 'secret-test-token' not in str(report)


async def test_runner_requires_explicit_opt_in_for_remote_or_chat(monkeypatch) -> None:
    monkeypatch.setenv('PERF_ACCESS_TOKEN', 'test-token')
    with pytest.raises(ValueError, match='--allow-chat'):
        await evaluate(argparse.Namespace(scenarios='chat', allow_chat=False))
    with pytest.raises(ValueError, match='--allow-remote'):
        await evaluate(argparse.Namespace(
            scenarios='accounts', base_url='https://api.example.com', allow_remote=False,
        ))
