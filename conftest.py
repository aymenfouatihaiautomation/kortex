"""Assure que la racine du projet est importable, quel que soit le répertoire d'invocation de pytest."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
