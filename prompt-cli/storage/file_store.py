from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import frontmatter
import yaml

from common import structlog
from common.core.paths import get_prompts_dir
from core.models import Prompt

logger = structlog.get_logger(__name__)

VALID_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_NAME_LENGTH = 64


class FilePromptStore:
    def __init__(self, prompts_dir: Path | None = None):
        if prompts_dir is None:
            prompts_dir = get_prompts_dir()
        self._prompts_dir = prompts_dir

    def _sanitize_name(self, name: str) -> str:
        sanitized = name.lower().strip()
        sanitized = re.sub(r"[^a-z0-9]+", "-", sanitized)
        sanitized = re.sub(r"-+", "-", sanitized)
        sanitized = sanitized.strip("-")
        return sanitized[:MAX_NAME_LENGTH]

    def _validate_name(self, name: str) -> None:
        sanitized = self._sanitize_name(name)
        if not sanitized:
            raise ValueError("Name cannot be empty")
        if not VALID_NAME_PATTERN.match(sanitized):
            raise ValueError(
                "Name must be alphanumeric with hyphens only "
                "(lowercase, starts with letter or digit)"
            )

    def _get_file_path(self, name: str) -> Path:
        sanitized = self._sanitize_name(name)
        return self._prompts_dir / f"{sanitized}.md"

    def _find_by_name(self, name: str) -> Path | None:
        sanitized = self._sanitize_name(name)
        file_path = self._prompts_dir / f"{sanitized}.md"
        if file_path.exists():
            return file_path
        return None

    def _load_prompt_from_file(self, file_path: Path) -> Prompt:
        try:
            content = file_path.read_text(encoding="utf-8")
            post = frontmatter.loads(content)

            return Prompt(
                name=post.metadata.get("name", file_path.stem),
                content=post.content,
                description=post.metadata.get("description", ""),
                model_provider=post.metadata.get("model_provider", ""),
                model_name=post.metadata.get("model_name", ""),
                temperature=post.metadata.get("temperature", 0.3),
                max_tokens=post.metadata.get("max_tokens", 4096),
                metadata=post.metadata.get("metadata", {}),
                created_at=datetime.fromisoformat(post.metadata["created_at"])
                if post.metadata.get("created_at")
                else None,
                updated_at=datetime.fromisoformat(post.metadata["updated_at"])
                if post.metadata.get("updated_at")
                else None,
            )
        except Exception as e:
            raise ValueError(
                f"FAIL LOUDLY: Failed to load prompt from {file_path}: {e}"
            )

    def _save_prompt_to_file(self, prompt: Prompt, file_path: Path) -> None:
        metadata = {
            "name": prompt.name,
            "description": prompt.description,
            "model_provider": prompt.model_provider,
            "model_name": prompt.model_name,
            "temperature": prompt.temperature,
            "max_tokens": prompt.max_tokens,
        }
        if prompt.metadata:
            metadata["metadata"] = prompt.metadata
        if prompt.created_at:
            metadata["created_at"] = prompt.created_at.isoformat()
        if prompt.updated_at:
            metadata["updated_at"] = prompt.updated_at.isoformat()

        content = frontmatter.dumps(frontmatter.Post(prompt.content, **metadata))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def create_prompt(self, prompt: Prompt) -> None:
        self._validate_name(prompt.name)
        file_path = self._get_file_path(prompt.name)
        if file_path.exists():
            raise ValueError(f"Prompt already exists: {prompt.name}")

        now = datetime.utcnow()
        prompt.created_at = now
        prompt.updated_at = now

        self._save_prompt_to_file(prompt, file_path)
        logger.info("prompt_created", name=prompt.name, path=str(file_path))

    def get_prompt(self, name: str) -> Prompt | None:
        file_path = self._find_by_name(name)
        if file_path is None:
            return None
        return self._load_prompt_from_file(file_path)

    def list_prompts(self) -> list[Prompt]:
        prompts = []
        for file_path in sorted(self._prompts_dir.glob("*.md")):
            prompt = self._load_prompt_from_file(file_path)
            prompts.append(prompt)
        return prompts

    def update_prompt(self, name: str, **updates) -> bool:
        file_path = self._find_by_name(name)
        if file_path is None:
            return False

        prompt = self._load_prompt_from_file(file_path)

        allowed = {
            "content",
            "description",
            "model_provider",
            "model_name",
            "temperature",
            "max_tokens",
            "metadata",
        }
        for key, value in updates.items():
            if key not in allowed:
                raise ValueError(f"Unsupported update field: {key}")
            setattr(prompt, key, value)

        prompt.updated_at = datetime.utcnow()
        self._save_prompt_to_file(prompt, file_path)
        logger.info("prompt_updated", name=name, fields=sorted(updates.keys()))
        return True

    def delete_prompt(self, name: str) -> bool:
        file_path = self._find_by_name(name)
        if file_path is None:
            return False
        file_path.unlink()
        logger.info("prompt_deleted", name=name)
        return True

    def get_file_path(self, name: str) -> Path | None:
        return self._find_by_name(name)

    def validate_prompt(self, name: str) -> Prompt:
        file_path = self._find_by_name(name)
        if file_path is None:
            raise FileNotFoundError(f"FAIL LOUDLY: Prompt not found: {name}")
        return self._load_prompt_from_file(file_path)

    def validate_all_prompts(self) -> dict:
        result = {"valid": [], "errors": []}
        for file_path in sorted(self._prompts_dir.glob("*.md")):
            try:
                prompt = self._load_prompt_from_file(file_path)
                result["valid"].append(prompt.name)
            except ValueError as e:
                result["errors"].append({"file": str(file_path), "error": str(e)})
        return result
