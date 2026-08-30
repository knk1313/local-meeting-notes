"""Application settings loaded from the repository's ``.env`` file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = PROJECT_ROOT / ".env"

# Existing process environment variables take precedence over values in .env.
load_dotenv(DOTENV_PATH, override=False)


@dataclass(frozen=True)
class Settings:
    """Configuration shared by the STT, LLM, and output layers."""

    openai_api_key: str | None
    anthropic_api_key: str | None
    notes_dir: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from the current environment."""
        notes_dir = Path(os.getenv("NOTES_DIR", "notes"))
        if not notes_dir.is_absolute():
            notes_dir = PROJECT_ROOT / notes_dir

        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            notes_dir=notes_dir,
        )


settings = Settings.from_environment()
