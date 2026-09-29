"""Central settings. Every value can be overridden with an environment variable (or .env)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

def _project_root() -> Path:
    """The FairSend project folder (holds data/, reports/, .env).

    FAIRSEND_HOME wins if set. In a source checkout it's the folder above this package. When FairSend is
    installed as a regular package (e.g. by a hosting service), the package lives in site-packages, so the
    folder the app is run from is used instead.
    """
    if os.getenv("FAIRSEND_HOME"):
        return Path(os.environ["FAIRSEND_HOME"]).resolve()
    checkout = Path(__file__).resolve().parent.parent
    if (checkout / "pyproject.toml").exists():
        return checkout
    return Path.cwd().resolve()


ROOT = _project_root()
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REFERENCE_DIR = DATA_DIR / "reference"
CACHE_DIR = DATA_DIR / "cache"
INDEX_DIR = DATA_DIR / "index"
OUTBOX_DIR = DATA_DIR / "outbox"
REPORTS_DIR = ROOT / "reports"
CORPUS_DIR = Path(__file__).resolve().parent / "explainer" / "corpus"


def _path(env: str, default: Path) -> Path:
    value = os.getenv(env)
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else ROOT / p


def latest_rpw_file() -> Path | None:
    explicit = os.getenv("FAIRSEND_RPW_FILE")
    if explicit:
        return _path("FAIRSEND_RPW_FILE", RAW_DIR / explicit)
    files = sorted(RAW_DIR.glob("rpw_dataset_*.xlsx"))
    return files[-1] if files else None


def tesseract_cmd() -> str | None:
    explicit = os.getenv("TESSERACT_CMD")
    if explicit:
        return explicit
    local = ROOT / ".tools" / "tesseract" / "bin" / "tesseract"
    if local.exists():
        return str(local)
    return shutil.which("tesseract")


@dataclass(frozen=True)
class Settings:
    db_path: Path = _path("FAIRSEND_DB", DATA_DIR / "fairsend.db")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    llm_model: str = os.getenv("FAIRSEND_LLM_MODEL", "qwen3.5:4b")
    llm_keep_alive: str = os.getenv("FAIRSEND_LLM_KEEP_ALIVE", "1h")
    embed_model: str = os.getenv("FAIRSEND_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    app_url: str = os.getenv("FAIRSEND_APP_URL", "http://localhost:8501")
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587") or 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")


settings = Settings()
