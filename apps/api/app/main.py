from __future__ import annotations

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.middleware import register_exception_handlers, register_middleware
from app.presentation.router import api_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AffordAbled API",
        swagger_ui_parameters={"persistAuthorization": True},
    )

    register_middleware(app, settings)
    register_exception_handlers(app)

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
