from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthContext, get_database_session, require_password_changed
from app.core.project_config import BrandingConfig, ProjectCatalog, ProjectId
from app.db.models.auth import OperatorProjectMembership
from app.db.models.enums import OperatorRole

router = APIRouter()


class PublicProject(BaseModel):
    project_id: str
    public_name: str
    branding: BrandingConfig
    membership_id: str
    role: OperatorRole


@router.get("")
async def list_projects(
    request: Request,
    auth: AuthContext = Depends(require_password_changed),
    database: AsyncSession = Depends(get_database_session),
) -> list[PublicProject]:
    catalog: ProjectCatalog = request.app.state.project_catalog
    memberships = list(
        await database.scalars(
            select(OperatorProjectMembership).where(
                OperatorProjectMembership.operator_account_id == auth.account.id,
                OperatorProjectMembership.is_active.is_(True),
            )
        )
    )
    return [
        PublicProject(
            project_id=membership.project_id,
            public_name=catalog.get(ProjectId(membership.project_id)).public_name,
            branding=catalog.get(ProjectId(membership.project_id)).branding,
            membership_id=str(membership.id),
            role=membership.role,
        )
        for membership in memberships
    ]
