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


def _build_optional_extraction_llm(settings: Any) -> Any | None:
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError:
        return None

    deployment = settings.azure_openai_extraction_deployment or settings.azure_openai_deployment
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key or not deployment:
        return None

    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=deployment,
        api_version=settings.azure_openai_api_version,
        temperature=0,
        timeout=20,
        max_retries=1,
    )


def main() -> None:
    _bootstrap_import_path()

    from app.core.config import get_settings
    from app.infrastructure.ai.intent_classifier import KeywordIntentClassifier
    from app.infrastructure.ai.langgraph_chat_orchestrator import LangGraphChatOrchestrator
    from app.infrastructure.ai.semantic_guardrail import KeywordSemanticGuardrail

    parser = argparse.ArgumentParser(description='Export LangGraph chat workflow diagram.')
    parser.add_argument(
        '--output-dir',
        default='artifacts/langgraph',
        help='Directory where chat_langgraph.mmd and chat_langgraph.png are written.',
    )
    args = parser.parse_args()

    settings = get_settings()
    extraction_llm = _build_optional_extraction_llm(settings)

    orchestrator = LangGraphChatOrchestrator(
        checkpointer=InMemorySaver(),
        semantic_guardrail=KeywordSemanticGuardrail(),
        intent_classifier=KeywordIntentClassifier(),
        transaction_service=_NoopTransactionService(),
        account_repository=_EmptyAccountRepository(),
        category_repository=_EmptyCategoryRepository(),
        extraction_llm=extraction_llm,
    )

    mermaid_path, png_path = orchestrator.save_graph_assets(_api_root() / args.output_dir)
    print(f'Mermaid diagram: {mermaid_path}')
    if png_path is not None:
        print(f'PNG diagram: {png_path}')
    else:
        print('PNG render skipped (Mermaid PNG render unavailable in current environment).')


if __name__ == '__main__':
    main()
