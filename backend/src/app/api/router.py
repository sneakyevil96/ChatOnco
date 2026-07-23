from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.operators import router as operators_router
from app.api.routes.operations import router as operations_router
from app.api.routes.projects import router as projects_router
from app.api.routes.tickets import router as tickets_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["authentication"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(projects_router, prefix="/projects", tags=["projects"])
api_router.include_router(
    tickets_router,
    prefix="/projects/{project_id}/tickets",
    tags=["tickets"],
)
api_router.include_router(
    operators_router,
    prefix="/projects/{project_id}/operators",
    tags=["operator administration"],
)
api_router.include_router(
    operations_router,
    prefix="/projects/{project_id}/operations",
    tags=["project operations"],
)
