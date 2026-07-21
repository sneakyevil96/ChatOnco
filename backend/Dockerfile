FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /workspace/backend

COPY pyproject.toml ./
COPY src ./src
COPY config ./config
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts

RUN pip install --no-cache-dir .

FROM base AS development
RUN pip install --no-cache-dir --editable ".[dev]"

FROM base AS development-embeddings
RUN pip install --no-cache-dir --editable ".[dev,embeddings]"

FROM base AS production
RUN pip install --no-cache-dir ".[embeddings]"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
