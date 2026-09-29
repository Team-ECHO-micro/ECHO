import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    hindsight_api_key: str = ""
    virtual_now: str = "2026-01-01T09:00:00+00:00"

    groq_primary_model: str = "openai/gpt-oss-20b"
    groq_fallback_model: str = "qwen/qwen3-32b"
    hindsight_base_url: str = "https://api.hindsight.vectorize.io"
    hindsight_timeout_seconds: float = 8.0


settings = Settings()


# ---------------------------------------------------------------------------
# Persisted virtual clock
# ---------------------------------------------------------------------------

_CLOCK_FILE = Path(os.environ.get("ECHO_CLOCK_FILE", "virtual_clock.json"))


class VirtualClock:
    """A virtual clock that persists its state to a JSON file.

    Used during demos to advance time forward so overdue commitments become
    visible without waiting in real time.
    """

    def __init__(self) -> None:
        self._load()

    def _load(self) -> None:
        if _CLOCK_FILE.exists():
            try:
                data = json.loads(_CLOCK_FILE.read_text())
                self._now = datetime.fromisoformat(data["virtual_now"])
                return
            except Exception:
                pass
        self._now = datetime.fromisoformat(settings.virtual_now)

    def _save(self) -> None:
        _CLOCK_FILE.write_text(json.dumps({"virtual_now": self._now.isoformat()}))

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def now_iso(self) -> str:
        return self._now.isoformat()

    def advance(self, days: int) -> str:
        """Advance the virtual clock by *days* and persist. Returns new ISO timestamp."""
        self._now += timedelta(days=days)
        self._save()
        return self.now_iso

    def reset(self) -> str:
        """Reset to the default time from settings."""
        self._now = datetime.fromisoformat(settings.virtual_now)
        if _CLOCK_FILE.exists():
            _CLOCK_FILE.unlink()
        return self.now_iso

    def overdue_commitments(
        self, commitments: list[dict],
    ) -> list[dict]:
        """Return commitments whose due_date is before the virtual now."""
        overdue: list[dict] = []
        for c in commitments:
            due = c.get("due_date", "")
            if not due:
                continue
            try:
                due_dt = datetime.fromisoformat(due)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                if due_dt < self._now:
                    overdue.append({**c, "overdue": True, "days_overdue": (self._now - due_dt).days})
            except (ValueError, TypeError):
                continue
        return overdue


virtual_clock = VirtualClock()
