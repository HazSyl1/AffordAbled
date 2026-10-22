from fastapi import APIRouter

from app.presentation.routers.accounts_router import router as accounts_router
from app.presentation.routers.auth_router import router as auth_router
from app.presentation.routers.categories_router import router as categories_router
from app.presentation.routers.chat_router import router as chat_router
from app.presentation.routers.exports_router import router as exports_router
from app.presentation.routers.imports_router import router as imports_router
from app.presentation.routers.memories_router import router as memories_router
from app.presentation.routers.settlement_plans_router import router as settlement_plans_router
from app.presentation.routers.splits_router import router as splits_router
from app.presentation.routers.threads_router import router as threads_router
from app.presentation.routers.transactions_router import router as transactions_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(accounts_router)
api_router.include_router(categories_router)
api_router.include_router(chat_router)
api_router.include_router(exports_router)
api_router.include_router(imports_router)
api_router.include_router(memories_router)
api_router.include_router(settlement_plans_router)
api_router.include_router(splits_router)
api_router.include_router(threads_router)
api_router.include_router(transactions_router)
