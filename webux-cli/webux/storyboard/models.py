from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCENE_STEPS = ("gen_transcript", "gen_image_prompt", "gen_audio", "gen_image", "assemble_clip")

GLOBAL_STEPS = ("parse", "transcript", "image_prompt", "audio", "image", "clip", "chapter", "final")

# Maps global step name to the scene-level step name it corresponds to (if any)
GLOBAL_TO_SCENE_STEP: dict[str, str] = {
    "transcript": "gen_transcript",
    "image_prompt": "gen_image_prompt",
    "audio": "gen_audio",
    "image": "gen_image",
    "clip": "assemble_clip",
}


@dataclass
class StepState:
    status: str = "pending"          # pending|running|done|error|skipped
    output: str = ""
    start_time: float | None = None
    end_time: float | None = None
    output_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        elapsed = None
        if self.start_time and self.end_time:
            elapsed = round(self.end_time - self.start_time, 1)
        elif self.start_time:
            elapsed = round(now - self.start_time, 1)
        return {
            "status": self.status,
            "output": self.output,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "elapsed_seconds": elapsed,
            "output_file": self.output_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StepState":
        return cls(
            status=d.get("status", "pending"),
            output=d.get("output", ""),
            start_time=d.get("start_time"),
            end_time=d.get("end_time"),
            output_file=d.get("output_file"),
        )


@dataclass
class Scene:
    id: str                          # "ch00_sc00"
    title: str
    raw_description: str
    transcript: str = ""
    image_prompt: str = ""
    steps: dict[str, StepState] = field(
        default_factory=lambda: {k: StepState() for k in SCENE_STEPS}
    )
    audio_file: str | None = None
    image_file: str | None = None
    clip_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "raw_description": self.raw_description,
            "transcript": self.transcript,
            "image_prompt": self.image_prompt,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "audio_file": self.audio_file,
            "image_file": self.image_file,
            "clip_file": self.clip_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        steps_raw = d.get("steps", {})
        steps = {k: StepState() for k in SCENE_STEPS}
        for k in SCENE_STEPS:
            if k in steps_raw:
                steps[k] = StepState.from_dict(steps_raw[k])
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            raw_description=d.get("raw_description", ""),
            transcript=d.get("transcript", ""),
            image_prompt=d.get("image_prompt", ""),
            steps=steps,
            audio_file=d.get("audio_file"),
            image_file=d.get("image_file"),
            clip_file=d.get("clip_file"),
        )

    def reset_from_step(self, from_step: str) -> None:
        """Clear this step and all downstream scene steps."""
        idx = list(SCENE_STEPS).index(from_step)
        for step_name in SCENE_STEPS[idx:]:
            self.steps[step_name] = StepState()
        if from_step in ("gen_audio", "gen_image_prompt", "gen_transcript"):
            pass
        if from_step in ("gen_audio",):
            self.audio_file = None
        if from_step in ("gen_image",):
            self.image_file = None
        if from_step in ("assemble_clip", "gen_image", "gen_audio"):
            self.clip_file = None


@dataclass
class Chapter:
    id: str                          # "ch00"
    title: str
    scenes: list[Scene] = field(default_factory=list)
    merge_step: StepState = field(default_factory=StepState)
    chapter_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scenes": [s.to_dict() for s in self.scenes],
            "merge_step": self.merge_step.to_dict(),
            "chapter_file": self.chapter_file,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Chapter":
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            scenes=[Scene.from_dict(s) for s in d.get("scenes", [])],
            merge_step=StepState.from_dict(d.get("merge_step", {})),
            chapter_file=d.get("chapter_file"),
        )


_MAX_CONSOLE_ENTRIES = 200


@dataclass
class ProjectState:
    script_text: str
    workdir: str                     # abs path to storyboard output subdir
    parse_step: StepState = field(default_factory=StepState)
    chapters: list[Chapter] = field(default_factory=list)
    final_step: StepState = field(default_factory=StepState)
    final_file: str | None = None
    console_log: list = field(default_factory=list)  # [{t, cmd, output, rc}]

    def log_cmd(self, cmd: str, output: str, rc: int | None) -> None:
        self.console_log.append({"t": time.time(), "cmd": cmd, "output": output[-3000:], "rc": rc})
        if len(self.console_log) > _MAX_CONSOLE_ENTRIES:
            self.console_log = self.console_log[-_MAX_CONSOLE_ENTRIES:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "script_text": self.script_text,
            "workdir": self.workdir,
            "parse_step": self.parse_step.to_dict(),
            "chapters": [c.to_dict() for c in self.chapters],
            "final_step": self.final_step.to_dict(),
            "final_file": self.final_file,
            "console_log": self.console_log,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectState":
        return cls(
            script_text=d.get("script_text", d.get("script_path", "")),
            workdir=d.get("workdir", ""),
            parse_step=StepState.from_dict(d.get("parse_step", {})),
            chapters=[Chapter.from_dict(c) for c in d.get("chapters", [])],
            final_step=StepState.from_dict(d.get("final_step", {})),
            final_file=d.get("final_file"),
            console_log=d.get("console_log", []),
        )

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ProjectState":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"State file not found: {p}")
        return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def global_status(self) -> str:
        """Aggregate status across all steps for the sidebar pipeline view."""
        all_steps: list[StepState] = [self.parse_step]
        for ch in self.chapters:
            for sc in ch.scenes:
                all_steps.extend(sc.steps.values())
            all_steps.append(ch.merge_step)
        all_steps.append(self.final_step)
        statuses = {s.status for s in all_steps}
        if "running" in statuses:
            return "running"
        if "error" in statuses:
            return "error"
        if statuses == {"done"} or (statuses - {"done", "skipped"} == set()):
            return "done"
        if "done" in statuses or "skipped" in statuses:
            return "partial"
        return "pending"

    def global_step_summary(self) -> dict[str, str]:
        """Status per global step name for the sidebar."""
        summary: dict[str, str] = {}

        summary["parse"] = self.parse_step.status

        for gstep, skey in GLOBAL_TO_SCENE_STEP.items():
            scene_statuses = []
            for ch in self.chapters:
                for sc in ch.scenes:
                    scene_statuses.append(sc.steps[skey].status)
            summary[gstep] = _agg_statuses(scene_statuses) if scene_statuses else "pending"

        ch_statuses = [ch.merge_step.status for ch in self.chapters]
        summary["chapter"] = _agg_statuses(ch_statuses) if ch_statuses else "pending"
        summary["final"] = self.final_step.status

        return summary


def _agg_statuses(statuses: list[str]) -> str:
    s = set(statuses)
    if "running" in s:
        return "running"
    if "error" in s:
        return "error"
    if s <= {"done"}:
        return "done"
    if "done" in s:
        return "partial"
    if s <= {"skipped"}:
        return "skipped"
    return "pending"
