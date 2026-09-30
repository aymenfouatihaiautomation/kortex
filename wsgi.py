"""Point d'entrée WSGI pour la production (Render, via gunicorn).

Ne pas utiliser en local — `python run_lms.py` reste l'entrypoint de développement (Flask dev
server, rechargement automatique). `gunicorn wsgi:app` sert cet `app` en production."""

from accounts.db import init_db
from bloc4_publication.app import create_app

# Crée les tables comptes si elles n'existent pas encore (idempotent) — voir accounts/db.py pour
# pourquoi ce n'est PAS fait dans create_app() lui-même (isolation des tests).
init_db()

app = create_app()
