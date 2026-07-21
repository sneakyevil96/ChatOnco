import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.core.project_config import ProjectCatalog, ProjectId
from app.main import create_app


PROJECT_CONFIG_DIR = Path(__file__).parents[1] / "config" / "projects"


def test_catalog_loads_both_projects_with_whatsapp_disabled() -> None:
    catalog = ProjectCatalog.load(PROJECT_CONFIG_DIR)

    assert [project.project_id for project in catalog.all()] == [
        ProjectId.ONCODIR,
        ProjectId.ONCOSCREEN,
    ]
    assert all(not project.whatsapp.enabled for project in catalog.all())
    assert all(not project.faq_retrieval.semantic_enabled for project in catalog.all())
    assert all(project.faq_retrieval.semantic_threshold is None for project in catalog.all())
    assert all(project.faq_retrieval.minimum_score_gap is None for project in catalog.all())
    assert all(project.content_status == "development_placeholder" for project in catalog.all())


def test_project_api_requires_authentication() -> None:
    async def request_projects():
        app = create_app()
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get("/api/v1/projects")

    response = asyncio.run(request_projects())

    assert response.status_code == 401
