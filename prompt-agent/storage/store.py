from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from common import structlog
from common.core.paths import get_tool_data_dir
from common.storage.base import (
    create_memory_engine,
    create_session_factory,
    create_sqlite_engine,
    run_alembic_migrations,
    session_scope,
)
from core.models import Prompt, PromptExecution
from storage.models import Base, ExecutionModel, PromptModel

logger = structlog.get_logger(__name__)


class PromptStore:
    def __init__(self, path: str | None = None):
        if path is None:
            path = str(get_tool_data_dir("prompt") / "prompts.db")
        self._path = path
        if path == ":memory:":
            self.engine = create_memory_engine()
            self._is_memory = True
        else:
            self.engine = create_sqlite_engine("prompt", "prompts.db", db_path=path)
            self._is_memory = False

        self.session_factory = create_session_factory(self.engine)
        self._run_migrations()

    def _run_migrations(self) -> None:
        if self._is_memory:
            Base.metadata.create_all(self.engine)
            logger.info("db_migration_complete", target="memory")
            return

        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        expanded = Path(self._path).expanduser()
        run_alembic_migrations(
            "prompt",
            alembic_ini,
            db_url_override=f"sqlite+pysqlite:///{expanded}",
        )

    @staticmethod
    def _to_prompt(row: PromptModel) -> Prompt:
        return Prompt(
            name=row.name,
            content=row.content,
            description=row.description,
            model_provider=row.model_provider,
            model_name=row.model_name,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
            metadata=json.loads(row.metadata_json),
            created_at=datetime.fromisoformat(row.created_at) if row.created_at else None,
            updated_at=datetime.fromisoformat(row.updated_at) if row.updated_at else None,
        )

    def create_prompt(self, prompt: Prompt) -> None:
        with session_scope(self.session_factory) as session:
            existing = session.execute(
                select(PromptModel).where(PromptModel.name == prompt.name)
            ).scalar_one_or_none()
            if existing:
                raise ValueError(f"Prompt already exists: {prompt.name}")

            now = datetime.utcnow().isoformat()
            session.add(
                PromptModel(
                    name=prompt.name,
                    content=prompt.content,
                    description=prompt.description,
                    model_provider=prompt.model_provider,
                    model_name=prompt.model_name,
                    temperature=prompt.temperature,
                    max_tokens=prompt.max_tokens,
                    metadata_json=json.dumps(prompt.metadata),
                    created_at=now,
                    updated_at=now,
                )
            )
        logger.info("prompt_created", name=prompt.name)

    def get_prompt(self, name: str) -> Prompt | None:
        with session_scope(self.session_factory) as session:
            row = session.execute(
                select(PromptModel).where(PromptModel.name == name)
            ).scalar_one_or_none()
            return self._to_prompt(row) if row else None

    def list_prompts(self) -> list[Prompt]:
        with session_scope(self.session_factory) as session:
            rows = session.execute(select(PromptModel).order_by(PromptModel.name)).scalars().all()
            return [self._to_prompt(row) for row in rows]

    def update_prompt(self, name: str, **updates) -> bool:
        with session_scope(self.session_factory) as session:
            row = session.execute(
                select(PromptModel).where(PromptModel.name == name)
            ).scalar_one_or_none()
            if not row:
                return False

            allowed = {
                "content",
                "description",
                "model_provider",
                "model_name",
                "temperature",
                "max_tokens",
                "metadata_json",
            }
            for key, value in updates.items():
                if key not in allowed:
                    raise ValueError(f"Unsupported update field: {key}")
                setattr(row, key, value)
            row.updated_at = datetime.utcnow().isoformat()
            logger.info("prompt_updated", name=name, fields=sorted(updates.keys()))
            return True

    def delete_prompt(self, name: str) -> bool:
        with session_scope(self.session_factory) as session:
            result = session.execute(delete(PromptModel).where(PromptModel.name == name))
            deleted = bool(result.rowcount and result.rowcount > 0)
        if deleted:
            logger.info("prompt_deleted", name=name)
        return deleted

    def record_execution(self, execution: PromptExecution) -> None:
        with session_scope(self.session_factory) as session:
            session.add(
                ExecutionModel(
                    prompt_name=execution.prompt_name,
                    input_args_json=json.dumps(execution.input_args),
                    resolved_content=execution.resolved_content,
                    output=execution.output,
                    model_provider=execution.model_provider,
                    model_name=execution.model_name,
                    timestamp=execution.timestamp.isoformat(),
                    metadata_json=json.dumps(execution.metadata),
                )
            )
        logger.info("execution_recorded", prompt=execution.prompt_name)
