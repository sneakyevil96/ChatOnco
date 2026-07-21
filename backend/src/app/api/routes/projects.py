from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.project_config import BrandingConfig, ProjectCatalog

router = APIRouter()


class PublicProject(BaseModel):
    project_id: str
    public_name: str
    branding: BrandingConfig


@router.get("")
async def list_projects(request: Request) -> list[PublicProject]:
    catalog: ProjectCatalog = request.app.state.project_catalog
    return [
        PublicProject(
            project_id=project.project_id.value,
            public_name=project.public_name,
            branding=project.branding,
        )
        for project in catalog.all()
    ]

