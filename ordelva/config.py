"""Paths and settings for ORDELVA-Automation. Everything is relative to the project root."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
MODELS = ROOT / "models"
PROJECTS = ROOT / "projects"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = ROOT / "config.json"

# Secrets (OAuth tokens, API keys) live OUTSIDE the project folder so they never get committed.
if os.name == "nt":
    SECRETS_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ORDELVA"
else:
    SECRETS_DIR = Path.home() / ".config" / "ordelva"

FORMATS = {
    "short": {"w": 1080, "h": 1920, "fps": 30, "min_s": 30, "max_s": 60},
    "long": {"w": 1920, "h": 1080, "fps": 30, "min_s": 360, "max_s": 600},
}

DEFAULTS = {
    "voice": "bm_george",          # Kokoro British male narrator
    "voice_lang": "en-gb",
    "voice_speed": 1.0,
    "llm_backend": "auto",           # auto: GitHub Models when GITHUB_TOKEN is set, else Ollama
    "github_models": ["openai/gpt-4.1-mini", "openai/gpt-4o-mini", "meta/Llama-3.3-70B-Instruct"],
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen2.5:7b",  # set by windows/setup.ps1 from detected hardware
    "pexels_api_key_env": "PEXELS_API_KEY",
    "whisper_model": "base.en",
    "whisper_device": "cpu",
    "target_lufs": -14.0,
    "music_db": -21.0,
    "daily_shorts": 4,
    "weekly_longs": 2,
    "production_enabled": False,   # stays off until quality is approved by the owner
    "default_privacy": "private",  # uploads are private until the owner approves publishing settings
    "allow_public_publish": False,
    "autonomous": False,           # True: strict automatic QA replaces the per-video human review
    "youtube_channel_id": "",
    # ramp-up: shorts/day by phase; next phase only after N clean publishes in a row
    "ramp": [{"shorts": 1, "after_clean": 0}, {"shorts": 2, "after_clean": 7},
             {"shorts": 3, "after_clean": 21}, {"shorts": 4, "after_clean": 42}],
    "longs_enabled": False,        # switched on after one long video passes a full test
    "longs_per_week": [1, 2],      # first 1/week, 2/week after 4 clean long publishes
    "publish_hour_utc": 14,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig")))
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


for _d in (PROJECTS, OUTPUT, LOGS):
    _d.mkdir(parents=True, exist_ok=True)
