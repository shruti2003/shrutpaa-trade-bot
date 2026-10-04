import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load KEY=VALUE pairs from ./.env (git-ignored) without overriding variables already set in the shell.
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _key, _sep, _value = _line.partition("=")
        if _sep and not _line.lstrip().startswith("#"):
            os.environ.setdefault(_key.strip(), _value.strip())
DATA_DIR = Path(os.environ.get("PAPER_TRADER_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "paper_trader.db"
CHROMA_DIR = DATA_DIR / "chroma"
KNOWLEDGE_DIR = ROOT / "knowledge"

STARTING_CASH = 100_000.0
CONTRACT_SIZE = 100
OPTION_COMMISSION = 0.65  # per contract, like most retail brokers
RISK_FREE_RATE = 0.04

MODEL = os.environ.get("PAPER_TRADER_MODEL", "claude-opus-5-5")
# SEC asks automated clients to identify themselves: https://www.sec.gov/os/accessing-edgar-data
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "PaperTraderAI research@example.com")
