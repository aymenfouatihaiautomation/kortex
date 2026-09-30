"""Pricing agent — Phase 2 : ajustement du prix selon la demande, en continu après le lancement.

Vérification PÉRIODIQUE (pas en temps réel après chaque vente individuelle) : `evaluate_and_apply`
ne relance une évaluation que si `REVIEW_WINDOW_DAYS` se sont écoulés depuis la dernière — idempotent
si appelé plusieurs fois dans la même fenêtre (pensé pour être invoqué par une tâche planifiée
externe, ex. hebdomadaire — aucune infrastructure de scheduling n'est construite ici, hors périmètre
de ce sprint).

Plafond dur à `PRICE_CEILING_USD` : jamais dépassé sans nouvelle validation explicite de
l'utilisateur. Chaque décision (changement ou non) est journalisée dans `pricing_state.json` via
`pricing_state.record_change` — jamais de changement silencieux."""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc5_payment.paddle_client import sync_price_to_paddle
from pricing_agent import config as _config
from pricing_agent import pricing_state, sales_log


def _due_for_review(state: dict, now: datetime) -> bool:
    last = state.get("last_reviewed_at")
    if not last:
        return True
    return now - datetime.fromisoformat(last) >= timedelta(days=_config.REVIEW_WINDOW_DAYS)


def evaluate_and_apply(
    now: datetime | None = None,
    state_path: Path | None = None,
    sales_path: Path | None = None,
) -> dict:
    """Un cycle de revue périodique. Retourne un résumé de la décision prise."""
    now = now or datetime.now(timezone.utc)
    state = pricing_state.load(state_path)

    if not _due_for_review(state, now):
        return {"action": "skipped_not_due", "current_price_usd": state["current_price_usd"]}

    count = sales_log.sales_in_window(_config.REVIEW_WINDOW_DAYS, now=now, store_path=sales_path)
    current_price = state["current_price_usd"]
    common = {
        "sales_observed": count,
        "threshold": _config.SALES_THRESHOLD_PER_WINDOW,
        "window_days": _config.REVIEW_WINDOW_DAYS,
    }

    if count < _config.SALES_THRESHOLD_PER_WINDOW:
        state = pricing_state.record_change(state, event="demand_no_change", **common)
        result = {"action": "no_change", "current_price_usd": current_price, **common}
    elif current_price >= _config.PRICE_CEILING_USD:
        state = pricing_state.record_change(state, event="demand_ceiling_reached", **common)
        result = {"action": "ceiling_reached", "current_price_usd": current_price, **common}
    else:
        candidate = round(current_price * (1 + _config.DEMAND_INCREASE_PCT), 2)
        new_price = min(candidate, _config.PRICE_CEILING_USD)
        price_id = sync_price_to_paddle(new_price)
        state = pricing_state.record_change(
            state,
            event="demand_increase",
            new_price_usd=new_price,
            price_id=price_id,
            capped=(new_price < candidate),
            **common,
        )
        result = {
            "action": "increased",
            "old_price_usd": current_price,
            "new_price_usd": new_price,
            **common,
        }

    state["last_reviewed_at"] = now.isoformat()
    pricing_state.save(state, state_path)
    return result


def _seed_demo_sales(sales_path: Path, count: int, now: datetime) -> None:
    for i in range(count):
        sales_log.record_sale(
            email=f"demo{i}@example.com",
            amount_usd=_config.LAUNCH_PRICE_USD,
            source="demo",
            store_path=sales_path,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Pricing agent — Phase 2 : ajustement selon la demande")
    parser.add_argument(
        "--demo", action="store_true", help="Mode démo : ventes synthétiques, fichiers isolés (ne touche pas l'état réel)"
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    if args.demo:
        state_path = _config.PRICING_DIR / "demo_pricing_state.json"
        sales_path = _config.PRICING_DIR / "demo_sales_log.json"
        demo_state = pricing_state.record_change(
            pricing_state.load(state_path),
            event="launch",
            new_price_usd=_config.LAUNCH_PRICE_USD,
            price_id="mock_price_demo",
            signal="démo",
        )
        pricing_state.save(demo_state, state_path)
        seeded = _config.SALES_THRESHOLD_PER_WINDOW + 2
        _seed_demo_sales(sales_path, seeded, now)
        print(f"[démo] {seeded} ventes synthétiques générées (fichiers isolés dans data/pricing/demo_*).")
    else:
        state_path = None
        sales_path = None

    result = evaluate_and_apply(now=now, state_path=state_path, sales_path=sales_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
