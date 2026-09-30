"""Comptes — connexion à la base (SQLAlchemy), swappable via `DATABASE_URL` sans changer de code.

Défaut (variable absente) : SQLite local, sous `LMS_STATE_DIR` (le même répertoire que
`access_grants.json`, voir bloc4_publication/config.py) — sur Render, ce répertoire est le disque
persistant monté (`/var/data`), donc le fichier SQLite survit aux redéploiements SANS
configuration supplémentaire, à condition que le plan Render reste payant avec disque (voir
docs/DEPLOYMENT.md). Pour passer à Postgres externe (Neon, Supabase, RDS...) : définir
`DATABASE_URL` dans l'environnement (ex. `postgresql+psycopg2://user:pass@host/db`) — c'est la
SEULE chose à changer, aucune ligne de code. Le driver correspondant (ex. `psycopg2-binary`)
n'est PAS dans requirements.txt : SQLAlchemy ne l'embarque pas, il faudra l'ajouter au moment de
basculer sur Postgres.

`engine`/`SessionLocal` sont des attributs de MODULE (pas des constantes capturées ailleurs) —
c'est ce qui permet aux tests de les remplacer via `unittest.mock.patch("accounts.db.SessionLocal",
...)` pour utiliser une base temporaire isolée, exactement comme les autres fichiers de ce projet
patchent `bloc4_publication.config.ACCESS_STORE_FILE`. Voir `accounts/service.py`, qui appelle
`db.SessionLocal()` via `from accounts import db` (pas `from accounts.db import SessionLocal`),
précisément pour que ce remplacement soit visible."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from bloc4_publication.config import LMS_STATE_DIR


def _default_sqlite_url() -> str:
    db_path = LMS_STATE_DIR / "accounts.db"
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = os.environ.get("DATABASE_URL") or _default_sqlite_url()

# `check_same_thread=False` : gunicorn/Flask peuvent traiter une requête sur un thread différent
# de celui qui a créé l'engine — sans cette option, sqlite3 refuse l'accès cross-thread. Sans
# incidence sur Postgres (l'option n'est passée que pour le driver sqlite).
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Crée les tables manquantes (idempotent — ne touche jamais aux tables déjà là).

    PAS appelé automatiquement par `bloc4_publication.app.create_app()` : ça éviterait de devoir
    patcher `engine`/`SessionLocal` dans TOUS les tests Flask existants qui n'ont rien à voir avec
    les comptes. Les deux vrais points d'entrée du serveur l'appellent explicitement à la place :
    `run_lms.py` (dev local) et `wsgi.py` (production, Render/gunicorn). En local, pour créer les
    tables sans lancer le serveur : `python -m accounts.db`.

    Pas de migrations (Alembic) à ce stade — si le schéma de `accounts/models.py` change plus
    tard, il faudra soit ajouter Alembic, soit migrer la base à la main."""
    from accounts import models  # noqa: F401 — enregistre les tables sur Base.metadata avant create_all

    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print(f"[accounts] Tables créées (ou déjà présentes) sur {DATABASE_URL}")
