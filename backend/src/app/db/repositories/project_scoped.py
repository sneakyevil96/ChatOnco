from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ProjectOwnedEntity = TypeVar("ProjectOwnedEntity", bound=Base)


class ProjectScopedRepository(Generic[ProjectOwnedEntity]):
    """Base repository that makes project context mandatory for every query."""

    def __init__(
        self,
        session: AsyncSession,
        model: type[ProjectOwnedEntity],
        project_id: str,
    ) -> None:
        if not project_id:
            raise ValueError("A project identifier is required")
        self._session = session
        self._model = model
        self.project_id = project_id

    def select(self) -> Select[tuple[ProjectOwnedEntity]]:
        return select(self._model).where(self._model.project_id == self.project_id)

    async def get(self, entity_id: UUID) -> ProjectOwnedEntity | None:
        statement = self.select().where(self._model.id == entity_id)
        return await self._session.scalar(statement)

    async def list(self, *, limit: int = 100) -> list[ProjectOwnedEntity]:
        if limit < 1 or limit > 500:
            raise ValueError("Repository limit must be between 1 and 500")
        result = await self._session.scalars(self.select().limit(limit))
        return list(result)

