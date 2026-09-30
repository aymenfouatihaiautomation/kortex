"""Pricing agent — Phase 1 : prix de lancement (une seule fois, avant le tout premier lancement).

Le prix proposé (`config.LAUNCH_PRICE_USD`, floor = target pour ce lancement) est une constante
produit fixée par l'utilisateur, PAS un output du LLM — voir `config.py` pour le raisonnement
business (frais Paddle). `research.py` fournit le contexte marché + un raisonnement qualitatif qui
accompagnent la proposition.

`build_launch_proposal()` n'a AUCUN effet de bord (pas d'appel Paddle) — elle sert à afficher la
recherche et la proposition pour confirmation humaine. `apply_launch_price()` ne doit être appelée
qu'APRÈS cette confirmation explicite : c'est elle qui déclenche l'appel (réel ou mock) à Paddle."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc4_publication.content_loader import load_course
from bloc5_payment.paddle_client import sync_price_to_paddle
from pricing_agent import config as _config
from pricing_agent import pricing_state, research


def build_launch_proposal(demo: bool = False, course: dict | None = None) -> dict:
    course = course or load_course()
    market = research.research_comparable_prices(course, demo=demo)

    video_ready = sum(1 for c in course["chapters"] if c.get("has_video"))
    total_chapters = len(course["chapters"])
    fee = _config.LAUNCH_PRICE_USD * _config.PADDLE_FEE_PCT + _config.PADDLE_FEE_FIXED_USD
    fee_pct_of_price = fee / _config.LAUNCH_PRICE_USD

    rationale = (
        f"Prix de lancement fixé à ${_config.LAUNCH_PRICE_USD:.2f} (floor = target pour ce "
        f"lancement). En dessous de ce seuil, les frais Paddle (estimation ~"
        f"{_config.PADDLE_FEE_PCT * 100:.0f}% + ${_config.PADDLE_FEE_FIXED_USD:.2f}, soit "
        f"${fee:.2f} ici = {fee_pct_of_price * 100:.0f}% du prix) mangeraient une part "
        f"disproportionnée de la marge. La recherche marché montre des cours comparables "
        f"spécialisés dans une fourchette nettement supérieure — la spécialisation du cours (7 "
        f"chapitres sur un seul gap précis) tirerait normalement le prix vers le haut de cette "
        f"fourchette, mais le catalogue vidéo encore incomplet ({video_ready}/{total_chapters} "
        f"chapitres) justifie de démarrer nettement en dessous, le temps de compléter la vidéo."
    )

    return {
        "course_title": course["title"],
        "video_chapters_ready": video_ready,
        "total_chapters": total_chapters,
        "market_research": market,
        "proposed_price_usd": _config.LAUNCH_PRICE_USD,
        "paddle_fee_estimate_usd": round(fee, 2),
        "paddle_fee_pct_of_price": round(fee_pct_of_price, 3),
        "rationale": rationale,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_confirmation",
    }


def save_proposal(proposal: dict) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = _config.PRICING_DIR / f"launch_proposal_{timestamp}.json"
    out_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_proposal(proposal: dict) -> None:
    print(f"\nProposition de prix de lancement — {proposal['course_title']}\n")
    print(f"Vidéo prête : {proposal['video_chapters_ready']}/{proposal['total_chapters']} chapitres\n")
    print("Cours comparables trouvés :")
    for c in proposal["market_research"]["comparable_courses"]:
        print(f"  - {c['title']} ({c['level']}) : ${c['price_usd']:.2f} — {c['source']}")
    rng = proposal["market_research"]["price_range_observed_usd"]
    print(f"\nFourchette observée : ${rng['min']:.2f} – ${rng['max']:.2f} (médiane ${rng['median']:.2f})")
    print(f"\nRaisonnement marché : {proposal['market_research']['reasoning']}")
    print(f"\n>>> Prix proposé : ${proposal['proposed_price_usd']:.2f} <<<")
    print(proposal["rationale"])
    print(
        f"\nFrais Paddle estimés : ${proposal['paddle_fee_estimate_usd']:.2f} "
        f"({proposal['paddle_fee_pct_of_price'] * 100:.1f}% du prix)"
    )
    print("\nEN ATTENTE DE CONFIRMATION EXPLICITE — aucun prix n'a été appliqué sur Paddle.")


def apply_launch_price(proposal: dict) -> dict:
    """N'appeler qu'APRÈS confirmation explicite de l'utilisateur. Crée (ou simule, en mode mock)
    le prix côté Paddle et l'enregistre comme prix actif du cours."""
    price_id = sync_price_to_paddle(proposal["proposed_price_usd"])
    state = pricing_state.load()
    state = pricing_state.record_change(
        state,
        event="launch",
        new_price_usd=proposal["proposed_price_usd"],
        price_id=price_id,
        signal="Prix de lancement — recherche marché + confirmation explicite de l'utilisateur",
    )
    pricing_state.save(state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="Pricing agent — Phase 1 : prix de lancement")
    parser.add_argument("--demo", action="store_true", help="Mode démo : recherche stub, aucun appel réseau")
    args = parser.parse_args()

    proposal = build_launch_proposal(demo=args.demo)
    print_proposal(proposal)
    out_path = save_proposal(proposal)
    print(f"\nProposition sauvegardée : {out_path}")


if __name__ == "__main__":
    main()
