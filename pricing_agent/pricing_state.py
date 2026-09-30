"""État du prix actif du cours — stockage JSON plat (cohérent avec `access_store.py` au Bloc 4,
pas de base de données pour un seul cours/un seul prix actif à la fois).

Avant toute action de la Phase 1 (`launch_pricing.apply_launch_price`), aucun fichier n'existe
encore : `load()` retourne alors un état par défaut dont le prix est la constante business
`LAUNCH_PRICE_USD` (déjà décidée), mais SANS `paddle_price_id` ni entrée d'historique — ce qui
distingue "prix par défaut pas encore confirmé" de "prix de lancement officiellement appliqué".
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from pricing_agent import config as _config


def _default_state() -> dict:
    return {
        "current_price_usd": _config.LAUNCH_PRICE_USD,
        "paddle_price_id": None,
        "last_reviewed_at": None,
        "history": [],
    }


def load(store_path: Path | None = None) -> dict:
    store_path = store_path or _config.PRICING_STATE_FILE
    if not store_path.exists():
        return _default_state()
    with store_path.open(encoding="utf-8") as f:
        return json.load(f)


def save(state: dict, store_path: Path | None = None) -> None:
    store_path = store_path or _config.PRICING_STATE_FILE
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_current_price_usd(store_path: Path | None = None) -> float:
    return load(store_path)["current_price_usd"]


def get_current_price_id(store_path: Path | None = None) -> str | None:
    return load(store_path)["paddle_price_id"]


def record_change(state: dict, event: str, new_price_usd: float | None = None, price_id: str | None = None, **details) -> dict:
    """Journalise un changement (ou une revue sans changement) dans `state["history"]`, met à jour
    `current_price_usd`/`paddle_price_id` si fournis. Ne sauvegarde pas — l'appelant fait `save()`."""
    entry = {
        "event": event,
        "old_price_usd": state["current_price_usd"],
        "new_price_usd": new_price_usd if new_price_usd is not None else state["current_price_usd"],
        "at": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    state["history"].append(entry)
    if new_price_usd is not None:
        state["current_price_usd"] = new_price_usd
    if price_id is not None:
        state["paddle_price_id"] = price_id
    return state
