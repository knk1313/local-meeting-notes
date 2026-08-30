"""リポジトリ直下の ``.env`` から読み込むアプリケーション設定。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = PROJECT_ROOT / ".env"

# 既に設定済みの環境変数を .env の値より優先する。
load_dotenv(DOTENV_PATH, override=False)


@dataclass(frozen=True)
class Settings:
    """STT・LLM・出力層で共有する設定。"""

    openai_api_key: str | None
    anthropic_api_key: str | None
    claude_model: str | None
    notes_dir: Path

    @classmethod
    def from_environment(cls) -> "Settings":
        """現在の環境変数から設定を構築する。"""
        notes_dir = Path(os.getenv("NOTES_DIR", "notes"))
        if not notes_dir.is_absolute():
            notes_dir = PROJECT_ROOT / notes_dir

        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            claude_model=os.getenv("CLAUDE_MODEL"),
            notes_dir=notes_dir,
        )


settings = Settings.from_environment()
