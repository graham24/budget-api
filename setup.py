import importlib
import os
import subprocess

from sqlalchemy import create_engine
from sqlmodel import SQLModel

from alembic import command
from alembic.config import Config

root_path = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else os.getcwd()
)

requirements_path = os.path.join(root_path, "requirements.txt")

subprocess.run(["pip3", "install", "-r", requirements_path], check=True)

# Import every model module so SQLModel registers their tables (mirrors
# migrations/env.py's discovery), then create any tables that don't exist
# yet. On a fresh DB this creates the full current schema in one shot;
# existing migrations only contain incremental diffs (ALTER TABLE etc),
# not full CREATE TABLE statements, so they assume the base tables are
# already there.
models_path = os.path.join(root_path, "models")
for file in os.listdir(models_path):
    if file.endswith(".py") and file not in ["__init__.py", "db.py"]:
        importlib.import_module(f"models.{file[:-3]}")

from models.db import db_url  # noqa: E402 (needs env vars loaded first)

engine = create_engine(db_url)
SQLModel.metadata.create_all(engine)

# create_all() just established the full current schema (this script is
# for bootstrapping a fresh DB only), so record that state directly rather
# than replaying migrations whose ALTERs already apply.
alembic_cfg = Config(os.path.join(root_path, "alembic.ini"))
command.stamp(alembic_cfg, "head")
