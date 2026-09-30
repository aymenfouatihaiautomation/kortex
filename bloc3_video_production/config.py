"""Configuration partagée pour le Bloc 3 (production vidéo)."""

import os
from pathlib import Path

from dotenv import load_dotenv

from config import DATA_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"

# Voix unique, cohérente sur les 7 vidéos (choisie parmi les voix premade du compte : "Alice",
# taguée "Clear, Engaging Educator" — la plus adaptée à un cours, testée en français avec succès).
VOICE_ID = "Xb7hH8MSUJpSbSDYk0k2"
VOICE_NAME = "Alice (Clear, Engaging Educator)"

FPS = 30
WIDTH = 1920
HEIGHT = 1080

REMOTION_DIR = PROJECT_ROOT / "remotion"
REMOTION_PUBLIC_AUDIO_DIR = REMOTION_DIR / "public" / "audio"
REMOTION_ENTRY = "src/index.ts"
REMOTION_COMPOSITION_ID = "ChapterVideo"

VIDEO_OUTPUT_DIR = DATA_DIR / "bloc3_video"
VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONTENT_FILE = DATA_DIR / "bloc2_content_final.json"

# Vitesse de lecture utilisée uniquement en mode démo pour estimer une durée sans appeler l'API.
DEMO_WORDS_PER_SECOND = 2.3
