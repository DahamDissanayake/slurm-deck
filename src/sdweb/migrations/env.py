"""Alembic environment. The URL comes from sdweb.db.migrate, or from
SD_DATABASE_URL when run with the alembic command."""

import os

from alembic import context
from sqlalchemy import create_engine

from sdweb.db import sa_url
from sdweb.models import Base

config = context.config
url = config.attributes.get("url") or sa_url(os.environ["SD_DATABASE_URL"])
if "agent_password" not in config.attributes:
    config.attributes["agent_password"] = os.environ.get("SD_AGENT_DB_PASSWORD", "")

connectable = create_engine(url)
with connectable.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
connectable.dispose()
