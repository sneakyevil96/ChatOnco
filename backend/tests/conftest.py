import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.settings import get_settings


@pytest.fixture
def database_session() -> Iterator[Session]:
    if os.getenv("RUN_DATABASE_TESTS") != "1":
        pytest.skip("PostgreSQL integration tests are disabled")

    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
    engine.dispose()

