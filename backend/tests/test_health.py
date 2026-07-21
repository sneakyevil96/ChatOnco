import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import create_app


def test_liveness_endpoint() -> None:
    async def request_liveness():
        app = create_app()
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                return await client.get("/api/v1/health/live")

    response = asyncio.run(request_liveness())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
