"""Vérifie les garde-fous ajoutés pour le déploiement (Render) : disque persistant configurable
pour les stores stateful (accès/pricing), et refus de démarrer en production sans vraie clé Flask.

Les vérifications elles-mêmes sont extraites en fonctions pures (`_resolve_lms_state_dir`,
`_resolve_flask_secret_key`) précisément pour être testables sans réimporter/recharger les modules
de config (qui ont des effets de bord à l'import — mkdir, etc.)."""

from pathlib import Path

import pytest

from bloc4_publication.config import _resolve_flask_secret_key as bloc4_resolve_secret
from bloc4_publication.config import _resolve_lms_state_dir as bloc4_resolve_state_dir
from config import DATA_DIR
from pricing_agent.config import _resolve_lms_state_dir as pricing_resolve_state_dir


def test_bloc4_lms_state_dir_defaults_to_data_dir_when_unset(monkeypatch):
    monkeypatch.delenv("LMS_STATE_DIR", raising=False)
    assert bloc4_resolve_state_dir() == DATA_DIR


def test_bloc4_lms_state_dir_uses_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_STATE_DIR", str(tmp_path))
    assert bloc4_resolve_state_dir() == tmp_path


def test_pricing_agent_lms_state_dir_uses_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LMS_STATE_DIR", str(tmp_path))
    assert pricing_resolve_state_dir() == tmp_path


def test_flask_secret_key_uses_real_value_when_set(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "a-real-secret")
    assert bloc4_resolve_secret() == "a-real-secret"


def test_flask_secret_key_falls_back_to_dev_default_locally(monkeypatch):
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert bloc4_resolve_secret() == "dev-secret-key-not-for-production"


def test_flask_secret_key_raises_in_production_without_real_secret(monkeypatch):
    # Régression : ne jamais démarrer en production (détectée via RENDER, positionnée
    # automatiquement par Render) avec la clé de dev par défaut — risque réel de falsification de
    # session si un vrai déploiement tournait avec une clé connue publiquement.
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.setenv("RENDER", "true")

    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        bloc4_resolve_secret()
