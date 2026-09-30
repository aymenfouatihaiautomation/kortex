"""Journal des ventes confirmées — alimenté par le Bloc 5 (paiement mock ou webhook réel), lu par
la Phase 2 du pricing agent comme signal de demande.

Le montant enregistré est le prix actif au moment de la vente (`pricing_state.get_current_price_usd()`),
pas un montant reparsé depuis le payload Paddle — exact tant qu'un seul cours/un seul prix est actif
à la fois (pas de promotions concurrentes)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pricing_agent import config as _config


def _load(store_path: Path) -> dict:
    if not store_path.exists():
        return {"sales": []}
    with store_path.open(encoding="utf-8") as f:
        return json.load(f)


def _save(store_path: Path, data: dict) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_sale(email: str, amount_usd: float, source: str, store_path: Path | None = None) -> None:
    store_path = store_path or _config.SALES_LOG_FILE
    data = _load(store_path)
    data["sales"].append(
        {
            "email": email,
            "amount_usd": amount_usd,
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save(store_path, data)


def sales_in_window(days: int, now: datetime | None = None, store_path: Path | None = None) -> int:
    store_path = store_path or _config.SALES_LOG_FILE
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    data = _load(store_path)
    return sum(1 for sale in data["sales"] if window_start <= datetime.fromisoformat(sale["at"]) <= now)
