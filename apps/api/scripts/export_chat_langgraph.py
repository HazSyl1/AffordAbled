from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver


def _api_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bootstrap_import_path() -> None:
    api_root = _api_root()
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))


class _NoopTransactionService:
    async def create_transaction(self, data: Any) -> Any:  # pragma: no cover
        del data
        raise RuntimeError('Not used for graph rendering')


class _EmptyAccountRepository:
    async def list_for_user(self, user_id: Any) -> list[Any]:  # pragma: no cover
        del user_id
        return []


class _EmptyCategoryRepository:
    async def list_for_user(self, user_id: Any) -> list[Any]:  # pragma: no cover
        del user_id
        return []


class _EmptyTransactionRepository:
    async def list_for_user(self, user_id: Any, *, include_deleted: bool = False) -> list[Any]:  # pragma: no cover
        del user_id
        del include_deleted
        return []


def main() -> None:
    _bootstrap_import_path()

    from app.application.services.account_service import AccountService
    from app.application.services.category_service import CategoryService
    from app.infrastructure.ai.agents.supervisor_graph import AgenticSupervisorGraph
    from app.infrastructure.ai.semantic_guardrail import KeywordSemanticGuardrail
    from app.infrastructure.ai.tools import TransactionQueryTools

    parser = argparse.ArgumentParser(description='Export LangGraph chat workflow diagram.')
    parser.add_argument(
        '--output-dir',
        default='artifacts/langgraph',
        help='Directory where chat_langgraph.mmd and chat_langgraph.png are written.',
    )
    args = parser.parse_args()

    class DiagramLlm:
        def with_structured_output(self, schema: Any, **_kwargs: Any) -> Any:
            from langchain_core.runnables import RunnableLambda

            return RunnableLambda(lambda _input: schema.model_construct())

    account_repository = _EmptyAccountRepository()
    category_repository = _EmptyCategoryRepository()
    graph = AgenticSupervisorGraph(
        checkpointer=InMemorySaver(),
        guardrail=KeywordSemanticGuardrail(),
        llm=DiagramLlm(),
        category_service=CategoryService(category_repository=category_repository),
        account_service=AccountService(account_repository=account_repository),
        transaction_service=_NoopTransactionService(),
        query_tools=TransactionQueryTools(
            transaction_repository=_EmptyTransactionRepository(),
            account_repository=account_repository,
            category_repository=category_repository,
        ),
    )

    output_dir = _api_root() / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    mermaid_path = output_dir / 'agentic_chat_langgraph.mmd'
    mermaid_path.write_text(graph.graph.get_graph().draw_mermaid(), encoding='utf-8')
    png_path = None
    print(f'Mermaid diagram: {mermaid_path}')
    if png_path is not None:
        print(f'PNG diagram: {png_path}')
    else:
        print('PNG render skipped (Mermaid PNG render unavailable in current environment).')


if __name__ == '__main__':
    main()
