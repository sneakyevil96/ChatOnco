#!/bin/sh
set -eu

alembic upgrade head
python -m app.commands.sync_projects
exec uvicorn app.main:app \
    --host 0.0.0.0 \
	--port 8000 \
	--no-access-log \
    --reload \
    --reload-dir src \
    --reload-dir config
