from fastapi import APIRouter

from app.presentation.routers.accounts_router import router as accounts_router
from app.presentation.routers.auth_router import router as auth_router
from app.presentation.routers.categories_router import router as categories_router
from app.presentation.routers.transactions_router import router as transactions_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(accounts_router)
api_router.include_router(categories_router)
api_router.include_router(transactions_router)
