from __future__ import annotations

import argparse
import subprocess
import sys


def run_command(command: list[str]) -> None:
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run API tasks with migration safety checks.')
    parser.add_argument(
        '--migrate-only',
        action='store_true',
        help='Apply latest Alembic migrations and exit.',
    )
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()

    print('Applying Alembic migrations to head...')
    run_command([sys.executable, '-m', 'alembic', 'upgrade', 'head'])

    if args.migrate_only:
        print('Migrations are up to date.')
        return

    print(f'Starting API on http://{args.host}:{args.port} ...')
    run_command(
        [
            sys.executable,
            '-m',
            'uvicorn',
            'app.main:app',
            '--host',
            args.host,
            '--port',
            str(args.port),
            '--reload',
        ]
    )


if __name__ == '__main__':
    main()
