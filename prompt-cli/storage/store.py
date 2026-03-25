from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from common import structlog
from common.core.paths import get_data_dir
from common.storage.base import (
    create_memory_engine,
    create_session_factory,
    create_sqlite_engine,
    session_scope,
)
from core.models import Prompt, PromptExecution
from storage.file_store import FilePromptStore
from storage.models import Base, ExecutionModel

logger = structlog.get_logger(__name__)


class PromptStore:
    def __init__(self, path: str | None = None, prompts_dir: Path | None = None):
        self._file_store = FilePromptStore(prompts_dir=prompts_dir)

        if path is None:
            path = str(get_data_dir() / "prompt" / "prompts.db")
        self._db_path = path
        if path == ":memory:":
            self.engine = create_memory_engine()
        else:
            self.engine = create_sqlite_engine("prompt", "prompts.db", db_path=path)

        Base.metadata.create_all(self.engine)
        self.session_factory = create_session_factory(self.engine)

    def create_prompt(self, prompt: Prompt) -> None:
        self._file_store.create_prompt(prompt)

    def get_prompt(self, name: str) -> Prompt | None:
        return self._file_store.get_prompt(name)

    def list_prompts(self) -> list[Prompt]:
        return self._file_store.list_prompts()

    def update_prompt(self, name: str, **updates) -> bool:
        return self._file_store.update_prompt(name, **updates)

    def delete_prompt(self, name: str) -> bool:
        return self._file_store.delete_prompt(name)

    def get_prompt_file_path(self, name: str) -> Path | None:
        return self._file_store.get_file_path(name)

    def validate_prompt(self, name: str) -> Prompt:
        return self._file_store.validate_prompt(name)

    def validate_all_prompts(self) -> dict:
        return self._file_store.validate_all_prompts()

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

    def list_executions(self, limit: int = 50) -> list[dict]:
        with session_scope(self.session_factory) as session:
            rows = (
                session.execute(
                    select(ExecutionModel)
                    .order_by(ExecutionModel.id.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "id": row.id,
                    "prompt_name": row.prompt_name,
                    "input_args": json.loads(row.input_args_json),
                    "resolved_content": row.resolved_content,
                    "output": row.output,
                    "model_provider": row.model_provider,
                    "model_name": row.model_name,
                    "timestamp": row.timestamp,
                    "metadata": json.loads(row.metadata_json),
                }
                for row in rows
            ]

    def truncate_executions(self) -> int:
        with session_scope(self.session_factory) as session:
            result = session.execute(delete(ExecutionModel))
            return result.rowcount or 0
