"""
KORTEX — Lancer un nouveau cours (double-clic sur lancer_cours.bat)
Aucune connaissance technique requise.
"""
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

def main():
    print("\n" + "="*55)
    print("   KORTEX — Génération d'un nouveau cours")
    print("="*55)
    print("\n Recherche du meilleur sujet en cours...")
    print(" (analyse du marché, tendances, concurrence)\n")

    try:
        from pipeline.scheduler import load_config, pick_next_topic
        proposal = pick_next_topic(load_config())
    except Exception as exc:
        print(f"\n ERREUR lors de la recherche : {exc}")
        input("\nAppuyez sur Entrée pour fermer...")
        return

    if proposal is None:
        print("\n Aucun nouveau sujet disponible pour le moment (tous les sujets")
        print(" des domaines actifs ont déjà un cours). Réessayez plus tard.")
        input("\nAppuyez sur Entrée pour fermer...")
        return

    print("="*55)
    print("   COURS PROPOSÉ")
    print("="*55)
    print(f"\n Domaine     : {proposal.get('domain', '?')}")
    print(f" Sujet       : {proposal.get('topic', proposal.get('course_title', '?'))}")
    print(f" Prix suggéré: ${proposal.get('suggested_price_usd', proposal.get('price_usd', 19))}")
    print(f" Score marché: {proposal.get('score_total', '?')}/30")

    justification = proposal.get('justification', proposal.get('angle', ''))
    if justification:
        print(f"\n Pourquoi ce sujet ?")
        for sentence in justification.replace('. ', '.\n').split('\n'):
            s = sentence.strip()
            if s:
                print(f"   → {s}")

    print("\n" + "-"*55)
    reponse = input("\n Voulez-vous lancer la génération ? (oui / non) : ").strip().lower()

    if reponse not in ('oui', 'o', 'yes', 'y'):
        print("\n Génération annulée. À bientôt !")
        input("\nAppuyez sur Entrée pour fermer...")
        return

    print("\n Lancement en cours...")
    print(" Durée estimée : 1 à 2 heures")
    print(" Ne fermez pas cette fenêtre.\n")
    print("-"*55)

    try:
        from pipeline.run_pipeline import run_pipeline
        result = run_pipeline(
            topic=proposal.get('topic', proposal.get('course_title', '')),
            domain=proposal.get('domain', ''),
            price_usd=float(proposal.get('suggested_price_usd', proposal.get('price_usd', 19))),
            gap_reason=justification,
            dry_run=False,
            interactive=False,
        )
        # Le vrai statut de succès est "completed" (pas "success") — vérifié dans
        # pipeline/run_pipeline.py::run_pipeline avant d'écrire ce script, sinon ce message ne
        # s'affiche JAMAIS même quand tout se passe bien.
        if result.get('status') == 'completed':
            print("\n SUCCÈS ! Cours publié sur KORTEX.")
            # Pas de clé "course_url" dans le résultat réel — construite depuis le slug (la vraie
            # route du site est /cours/<slug>, voir bloc4_publication/app.py::course_landing).
            slug = result.get('slug', '')
            url = f"https://cours.aymen-automation.site/cours/{slug}" if slug else "https://cours.aymen-automation.site"
            print(f" URL : {url}")
        else:
            print(f"\n Résultat : {json.dumps(result, ensure_ascii=False, indent=2)}")
    except Exception as exc:
        print(f"\n ERREUR pendant la génération : {exc}")
        print(" Contactez le support si l'erreur persiste.")

    input("\nAppuyez sur Entrée pour fermer...")

if __name__ == "__main__":
    main()
