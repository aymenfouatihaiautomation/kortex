"""Configuration partagée pour le Sprint 1 (Bloc 0 + Bloc 1)."""

from pathlib import Path

NICHE = "AI Automation"

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

DEFAULT_MODEL = None  # None = modèle par défaut du CLI Claude Code

DATA_DIR.mkdir(exist_ok=True)
