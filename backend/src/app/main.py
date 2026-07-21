from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.project_config import ProjectCatalog
from app.core.settings import get_settings
from app.db.session import create_database_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.project_catalog = ProjectCatalog.load(settings.project_config_dir)
    app.state.database_engine = create_database_engine(settings.database_url)
    app.state.database_session_factory = create_session_factory(app.state.database_engine)
    yield
    await app.state.database_engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Screening Support Platform API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
