import asyncio
import sys

# psycopg3's async mode is incompatible with Windows' default ProactorEventLoop.
# This must run before any async engine/connection is created (Alembic, uvicorn, pytest
# all import this package first), so it is set once here rather than per-entrypoint.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
