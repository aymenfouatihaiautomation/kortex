"""Pipeline — Module 4 : interface de validation rapide des cours en attente.

Lit `pending_validation.json` (rempli par `run_pipeline.py`/`scheduler.py` quand un cours part en
'attente' — pas de prompt interactif dans le scheduler, qui n'a pas de terminal) et propose, pour
chacun, le même choix oui/non/attente — mais SANS timeout ici : cet outil est lancé exprès par un
humain présent pour trancher tout de suite, contrairement à `run_pipeline.py::prompt_validation`
qui doit rester non-bloquant dans un run automatisé."""

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run_pipeline import (
    REPORTS_DIR,
    apply_validation_decision,
    load_pending_validation,
    remove_pending_validation,
)


def _report_price(slug: str) -> float | None:
    path = REPORTS_DIR / f"{slug}_report.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("prix_suggere_usd")


def _print_short_report(entry: dict) -> None:
    print(f"\n--- {entry['slug']} ---")
    print(f"Domaine : {entry['domain']} | Sujet : {entry['topic']}")
    report_txt_path = Path(entry["report_path"])
    if report_txt_path.exists():
        print(report_txt_path.read_text(encoding="utf-8"))
    else:
        print(f"(rapport introuvable : {report_txt_path})")


def _ask_decision(slug: str) -> str:
    while True:
        answer = input(f"[{slug}] Tapez 'oui', 'non' ou 'attente' : ").strip().lower()
        if answer in ("oui", "non", "attente"):
            return answer
        print("Reponse non reconnue, reessayez ('oui'/'non'/'attente').")


def validate_one(entry: dict) -> str:
    """Affiche le rapport court d'UNE entrée en attente, demande une décision, l'applique.
    Retourne la décision prise ('oui'/'non'/'attente')."""
    _print_short_report(entry)
    decision = _ask_decision(entry["slug"])

    if decision == "oui":
        price = _report_price(entry["slug"])
        path = apply_validation_decision(entry["slug"], "oui", price_usd=price)
        remove_pending_validation(entry["slug"])
        print(f"Valide -> {path}")
    elif decision == "non":
        reason = input("Raison du rejet (optionnel) : ").strip() or "rejete via pipeline/validate.py"
        path = apply_validation_decision(entry["slug"], "non", reason=reason)
        remove_pending_validation(entry["slug"])
        print(f"Rejete -> {path}")
    else:
        print("Laisse en attente.")

    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline — Validation des cours en attente")
    parser.add_argument("--slug", type=str, default=None, help="Ne valider qu'un seul cours (par son slug)")
    args = parser.parse_args()

    pending = load_pending_validation()
    if args.slug:
        pending = [p for p in pending if p["slug"] == args.slug]
        if not pending:
            print(f"Aucun cours en attente avec le slug {args.slug!r}.")
            return

    if not pending:
        print("Aucun cours en attente de validation.")
        return

    for entry in pending:
        validate_one(entry)


if __name__ == "__main__":
    main()
