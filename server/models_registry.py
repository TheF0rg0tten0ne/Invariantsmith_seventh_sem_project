"""
Tracks which local GGUF model files are available under models/, so the
API can report status and (later) let users switch between a fast/small
model and a slower/more-accurate one without restarting the server.
"""
from dataclasses import dataclass

from . import config


@dataclass
class ModelInfo:
    filename: str
    size_bytes: int
    active: bool


def list_models() -> list[ModelInfo]:
    models = []
    if not config.MODELS_DIR.exists():
        return models
    for f in config.MODELS_DIR.glob("*.gguf"):
        models.append(ModelInfo(
            filename=f.name,
            size_bytes=f.stat().st_size,
            active=(f.name == config.MODEL_FILENAME),
        ))
    return models


def active_model() -> ModelInfo | None:
    for m in list_models():
        if m.active:
            return m
    return None
