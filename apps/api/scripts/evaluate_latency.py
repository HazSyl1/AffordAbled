"""Opt-in HTTP latency evaluation against a running API; no application imports."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

READ_SCENARIOS = {
    'accounts': '/accounts',
    'transactions': '/transactions',
    'categories': '/categories',
    'splits': '/splits',
    'person_balances': '/splits/balances',
    'threads': '/threads',
    'recurring_transactions': '/recurring-transactions',
}


@dataclass
class Sample:
    scenario: str
    elapsed_ms: float
    successful: bool
    status_code: int | None = None
    error: str | None = None
    request_id: str | None = None
    submit_ms: float | None = None
    server_turn_ms: float | None = None
    queue_wait_ms: float | None = None
    processing_ms: float | None = None


def percentile(values: list[float], percent: float) -> float | None:
    """Nearest-rank percentile, including a defined result for a single sample."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


def summarize(samples: list[Sample]) -> dict:
    result = {}
    for scenario in sorted({sample.scenario for sample in samples}):
        rows = [row for row in samples if row.scenario == scenario]
        successful = [row.elapsed_ms for row in rows if row.successful]
        errors: dict[str, int] = {}
        for row in rows:
            if not row.successful:
                key = row.error or str(row.status_code)
                errors[key] = errors.get(key, 0) + 1
        result[scenario] = {
            'samples': len(rows), 'successful': len(successful),
            'error_rate': (len(rows) - len(successful)) / len(rows),
            'success_latency_ms': {
                f'p{p}': percentile(successful, p) for p in (50, 95, 99)
            },
            'all_attempts_p99_ms': percentile([row.elapsed_ms for row in rows], 99),
            'submit_p50_ms': percentile([row.submit_ms for row in rows if row.submit_ms is not None], 50),
            'server_turn_p50_ms': percentile(
                [row.server_turn_ms for row in rows if row.server_turn_ms is not None], 50,
            ),
            'queue_wait_p50_ms': percentile([row.queue_wait_ms for row in rows if row.queue_wait_ms is not None], 50),
            'processing_p50_ms': percentile([row.processing_ms for row in rows if row.processing_ms is not None], 50),
            'p99_confidence': 'preliminary: fewer than 1000 successes' if len(successful) < 1000 else
                              'inspect repeated runs and tail samples',
            'errors': errors,
        }
    return result


async def measure(
    client: httpx.AsyncClient, scenario: str, *, deadline_seconds: float = 120,
    poll_seconds: float = 1.5, messages: list[str] | None = None,
) -> Sample:
    started = time.perf_counter()
    sample = Sample(scenario, 0, False)
    try:
        # The deadline covers submission, polling and every turn in the conversation.
        async with asyncio.timeout(deadline_seconds):
            if scenario in READ_SCENARIOS:
                response = await client.get('/api/v1' + READ_SCENARIOS[scenario])
                sample.status_code = response.status_code
                sample.request_id = response.headers.get('X-Request-ID')
                response.raise_for_status()
                if not isinstance(response.json(), list):
                    sample.error = 'unexpected_response'
                else:
                    sample.successful = True
            else:
                thread_id = str(uuid.uuid4())
                server_ms = 0.0
                queue_wait_ms = 0.0
                processing_ms = 0.0
                submit_ms = 0.0
                for message in messages or ['What are my account balances?']:
                    turn_id = str(uuid.uuid4())
                    submit_start = time.perf_counter()
                    response = await client.post('/api/v1/chat/turns', json={
                        'turn_id': turn_id, 'thread_id': thread_id, 'message': message, 'timezone': 'Asia/Calcutta',
                    })
                    submit_ms += (time.perf_counter() - submit_start) * 1000
                    sample.status_code = response.status_code
                    sample.request_id = response.headers.get('X-Request-ID')
                    response.raise_for_status()
                    payload = response.json()
                    while payload['status'] not in {'succeeded', 'failed'}:
                        await asyncio.sleep(poll_seconds)
                        response = await client.get(f'/api/v1/chat/turns/{turn_id}')
                        sample.status_code = response.status_code
                        response.raise_for_status()
                        payload = response.json()
                    if payload['status'] == 'failed':
                        sample.error = 'chat_failed'
                        break
                    if not isinstance(payload.get('result'), dict) or not payload['result'].get('message'):
                        sample.error = 'missing_chat_result'
                        break
                    if payload.get('created_at') and payload.get('completed_at'):
                        created_at = datetime.fromisoformat(payload['created_at'])
                        completed_at = datetime.fromisoformat(payload['completed_at'])
                        server_ms += (completed_at - created_at).total_seconds() * 1000
                    elif payload.get('created_at') and payload.get('updated_at'):
                        server_ms += (
                            datetime.fromisoformat(payload['updated_at'])
                            - datetime.fromisoformat(payload['created_at'])
                        ).total_seconds() * 1000
                    if payload.get('created_at') and payload.get('claimed_at'):
                        queue_wait_ms += (
                            datetime.fromisoformat(payload['claimed_at'])
                            - datetime.fromisoformat(payload['created_at'])
                        ).total_seconds() * 1000
                    if payload.get('claimed_at') and payload.get('completed_at'):
                        processing_ms += (
                            datetime.fromisoformat(payload['completed_at'])
                            - datetime.fromisoformat(payload['claimed_at'])
                        ).total_seconds() * 1000
                else:
                    sample.successful = True
                sample.submit_ms = submit_ms
                sample.server_turn_ms = server_ms or None
                sample.queue_wait_ms = queue_wait_ms or None
                sample.processing_ms = processing_ms or None
    except httpx.HTTPStatusError as error:
        sample.status_code = error.response.status_code
        sample.error = f'http_{error.response.status_code}'
    except (TimeoutError, httpx.TimeoutException):
        sample.error = 'timeout'
    except httpx.RequestError:
        sample.error = 'network_error'
    except (KeyError, ValueError, TypeError):
        sample.error = 'unexpected_response'
    finally:
        sample.elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return sample


async def evaluate(args: argparse.Namespace) -> dict:
    token = os.environ.get('PERF_ACCESS_TOKEN', '').strip()
    if not token:
        email = os.environ.get('PERF_EMAIL', '').strip()
        password = os.environ.get('PERF_PASSWORD', '')
        if not email or not password:
            raise ValueError('Set PERF_ACCESS_TOKEN or both PERF_EMAIL and PERF_PASSWORD.')
    scenarios = args.scenarios.split(',')
    if any(name not in READ_SCENARIOS and name != 'chat' for name in scenarios):
        raise ValueError('Unknown scenario. Choose: ' + ','.join([*READ_SCENARIOS, 'chat']))
    if 'chat' in scenarios and not args.allow_chat:
        raise ValueError('Chat needs --allow-chat: it creates threads/jobs and consumes model quota.')
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.path not in {'', '/'}:
        raise ValueError('--base-url must be the API origin without /api/v1.')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Do not embed credentials or query parameters in --base-url.')
    local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    if not local and (not args.allow_remote or parsed.scheme != 'https'):
        raise ValueError('Remote runs require https and --allow-remote. Use a dedicated test account.')
    if not token:
        async with httpx.AsyncClient(base_url=args.base_url.rstrip('/'), timeout=args.timeout) as login_client:
            response = await login_client.post('/api/v1/auth/login', json={'email': email, 'password': password})
        if response.status_code != 200:
            raise ValueError(f'Login failed with HTTP {response.status_code}; check the test account credentials.')
        token = response.json().get('access_token', '')
        if not token:
            raise ValueError('Login succeeded but the API did not return an access token.')
    samples = []
    warmup_failures = 0
    started = time.perf_counter()
    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip('/'), headers={'Authorization': f'Bearer {token}'},
        timeout=args.timeout, follow_redirects=False,
        limits=httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency),
    ) as client:
        # Warm up each scenario sequentially, retaining the number of failed warmup attempts.
        for scenario in scenarios:
            for _ in range(args.warmup):
                row = await measure(client, scenario, deadline_seconds=args.timeout,
                                    poll_seconds=args.poll_seconds, messages=args.chat_message)
                warmup_failures += not row.successful
        for scenario in scenarios:
            queue: asyncio.Queue[int] = asyncio.Queue()
            for index in range(args.samples):
                queue.put_nowait(index)

            async def worker(name: str = scenario, pending: asyncio.Queue[int] = queue) -> None:
                while not pending.empty():
                    pending.get_nowait()
                    row = await measure(client, name, deadline_seconds=args.timeout,
                                        poll_seconds=args.poll_seconds, messages=args.chat_message)
                    samples.append(row)
                    if args.pause:
                        await asyncio.sleep(args.pause)

            await asyncio.gather(*(worker() for _ in range(args.concurrency)))
            print(f'{scenario}: completed {args.samples} measured attempts', flush=True)
    return {
        'schema_version': 1, 'recorded_at': datetime.now(UTC).isoformat(),
        'metadata': {
            'environment': args.environment, 'base_url': args.base_url, 'revision': args.revision,
            'concurrency': args.concurrency, 'samples_per_scenario': args.samples,
            'warmup_per_scenario': args.warmup, 'warmup_failures': warmup_failures,
            'poll_seconds': args.poll_seconds, 'timeout_seconds': args.timeout,
            'chat_turns_per_conversation': len(args.chat_message or ['default']),
            'duration_seconds': round(time.perf_counter() - started, 3),
            'load_model': 'closed: each worker waits for completion before its next attempt',
        },
        'summary': summarize(samples), 'samples': [asdict(row) for row in samples],
    }


def markdown(report: dict) -> str:
    lines = ['# Application latency evaluation', '',
             'Client-observed API timings. Chat includes submission, queue, processing and polling.', '',
             '| Action | Success / attempts | p50 ms | p95 ms | p99 ms | Error rate |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name, stats in report['summary'].items():
        latency = stats['success_latency_ms']
        values = [f'{latency[key]:.1f}' if latency[key] is not None else 'N/A' for key in ('p50', 'p95', 'p99')]
        lines.append(f"| {name} | {stats['successful']} / {stats['samples']} | {' | '.join(values)} | "
                     f"{stats['error_rate']:.1%} |")
    lines.extend(['', 'Percentiles use successful attempts; JSON includes every failure, timeout and request ID.',
                  'Treat p99 as preliminary below 1000 successes per action. Repeat runs before drawing conclusions.',
                  '', '```json', json.dumps(report['metadata'], indent=2), '```', ''])
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--environment', default='local')
    parser.add_argument('--revision', default='unspecified')
    parser.add_argument('--scenarios', default=','.join(READ_SCENARIOS))
    parser.add_argument('--samples', type=int, default=100)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--poll-seconds', type=float, default=1.5)
    parser.add_argument('--pause', type=float, default=0.1)
    parser.add_argument('--allow-chat', action='store_true')
    parser.add_argument('--allow-remote', action='store_true')
    parser.add_argument('--chat-message', action='append', help='Repeat for sequential turns within one conversation.')
    parser.add_argument(
        '--output', type=Path, default=Path('.performance') / datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ'),
    )
    args = parser.parse_args()
    if min(args.samples, args.concurrency) < 1 or args.warmup < 0 or args.pause < 0:
        parser.error('Samples/concurrency must be positive; warmup/pause must be nonnegative.')
    if not all(math.isfinite(value) for value in (args.timeout, args.poll_seconds, args.pause)):
        parser.error('Timeout, poll interval and pause must be finite.')
    if args.timeout <= 0 or args.poll_seconds <= 0:
        parser.error('Timeout and poll interval must be positive.')
    try:
        report = asyncio.run(evaluate(args))
    except ValueError as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    rendered = markdown(report)
    (args.output / 'report.md').write_text(rendered, encoding='utf-8')
    print(rendered)
    print(f'Reports: {args.output.resolve()}')
    return int(report['metadata']['warmup_failures'] > 0 or any(
        stats['error_rate'] > 0 for stats in report['summary'].values()
    ))


if __name__ == '__main__':
    raise SystemExit(main())
