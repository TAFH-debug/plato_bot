"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _data_dir() -> Path:
    # Persistent state (SQLite DB, .secret.key). On Railway the attached
    # volume's mount path is exported as RAILWAY_VOLUME_MOUNT_PATH.
    raw = os.getenv("DATA_DIR", "").strip() or os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    d = Path(raw) if raw else ROOT
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA_DIR = _data_dir()


def _leads(raw: str) -> list[int]:
    out = {int(x) for x in raw.replace(" ", "").split(",") if x}
    return sorted(out, reverse=True)


@dataclass(frozen=True)
class Config:
    bot_token: str
    plato_url: str
    fernet_key: str
    db_path: Path
    tz: ZoneInfo
    default_leads: list[int] = field(default_factory=lambda: [1440, 180, 60])
    check_interval_min: int = 10

    @classmethod
    def load(cls) -> "Config":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit("BOT_TOKEN is missing. Copy .env.example to .env and fill it in.")
        db = Path(os.getenv("DB_PATH", "plato_bot.sqlite3"))
        if not db.is_absolute():
            db = DATA_DIR / db
        return cls(
            bot_token=token,
            plato_url=os.getenv("PLATO_URL", "https://plato.pusan.ac.kr").rstrip("/"),
            fernet_key=os.getenv("FERNET_KEY", "").strip(),
            db_path=db,
            tz=ZoneInfo(os.getenv("TIMEZONE", "Asia/Seoul")),
            default_leads=_leads(os.getenv("DEFAULT_LEADS", "1440,180,60")),
            check_interval_min=int(os.getenv("CHECK_INTERVAL_MIN", "10")),
        )


LEAD_CHOICES = [10080, 4320, 1440, 720, 360, 180, 60, 30]
