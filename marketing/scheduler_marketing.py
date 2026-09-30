"""Marketing KORTEX — Planificateur.

Déclenche `agent5_supervisor.py::run_pipeline` tous les jours à 08:00 heure locale de la machine
qui exécute ce script. Utilise `schedule` (bloquant, boucle `while True` + `sleep`) plutôt
qu'APScheduler : un seul job quotidien fixe ne justifie pas la complexité (jobstore, executors)
d'APScheduler — cohérent avec la philosophie "pas d'abstraction non nécessaire" du reste du dépôt.

Point d'entrée : `python marketing/scheduler_marketing.py`."""

import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schedule

from marketing.agent5_supervisor import _log, run_pipeline

DAILY_RUN_TIME = "08:00"


def _run_daily_job() -> None:
    _log(f"Déclenchement planifié ({DAILY_RUN_TIME} local)")
    try:
        run_pipeline(demo=False)
    except Exception as exc:
        _log(f"Erreur non interceptée dans run_pipeline : {exc}")


def main() -> None:
    schedule.every().day.at(DAILY_RUN_TIME).do(_run_daily_job)
    _log(f"Planificateur marketing KORTEX démarré — run quotidien à {DAILY_RUN_TIME} (heure locale)")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
