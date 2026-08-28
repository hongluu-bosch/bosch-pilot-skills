"""Version single source of truth."""

import pathlib

_SKILL_VERSION_PATH = pathlib.Path(__file__).resolve().parent.parent / "VERSION"


def get_version() -> str:
    if _SKILL_VERSION_PATH.exists():
        return _SKILL_VERSION_PATH.read_text(encoding="utf-8").strip()
    return "0.0.0"
