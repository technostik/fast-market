from __future__ import annotations

from ..storyboard.models import (
    ProjectState, Chapter, Scene, StepState,
    SCENE_STEPS, GLOBAL_STEPS, GLOBAL_TO_SCENE_STEP,
)

__all__ = [
    "ProjectState", "VoiceboardState", "Chapter", "Scene", "StepState",
    "SCENE_STEPS", "GLOBAL_STEPS", "GLOBAL_TO_SCENE_STEP",
]


class VoiceboardState(ProjectState):
    """Project state for the voiceboard pipeline.

    Extends the shared :class:`ProjectState` with the session-scoped voice
    source so it is not buried in global config (config holds only what does
    not change between sessions). Both fields are optional and mutually
    exclusive: either a source voice file (uploaded/copied into the workdir)
    or an existing segments.json is used.

    These are plain instance attributes (not dataclass fields — the generated
    ``__init__`` only accepts ProjectState's own fields), set after
    construction and persisted through :meth:`to_dict`/:meth:`from_dict`.
    """

    voice_file: str = ""          # absolute path to source voice in the workdir
    segments_json: str = ""       # absolute path to an existing segments.json

    def __post_init__(self):
        super().__post_init__()
        self.voice_file = ""
        self.segments_json = ""

    def to_dict(self):
        d = super().to_dict()
        d["voice_file"] = self.voice_file
        d["segments_json"] = self.segments_json
        return d

    @classmethod
    def from_dict(cls, d):
        state = super().from_dict(d)
        state.voice_file = d.get("voice_file", "")
        state.segments_json = d.get("segments_json", "")
        return state
