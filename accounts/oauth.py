"""Comptes — connexion Google (OAuth 2.0 / OpenID Connect), PHASE 2.

Le login email + mot de passe (Phase 1, voir accounts/routes.py) reste inchangé et fonctionne
indépendamment de ce module.

Client Authlib enregistré UNIQUEMENT si `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` sont tous
les deux présents dans l'environnement — jamais en dur dans le code ni dans un fichier commité
(ils vivent dans `.env`, gitignored, exactement comme `PADDLE_API_KEY`). Si absents,
`google_oauth_enabled()` renvoie False et les routes `/login/google[/callback]`
(accounts/routes.py) répondent 404 proprement plutôt que de planter ; le bouton "Se connecter
avec Google" est alors simplement masqué côté template (login.html/register.html).

Scopes demandés : `openid email profile` — les trois scopes non sensibles minimaux pour
identifier l'utilisateur (email vérifié + nom), rien de plus (pas d'accès Drive/Calendar/etc.).

Lecture de `os.environ` À CHAQUE APPEL (pas de constante capturée une fois à l'import) : c'est ce
qui permet aux tests de activer/désactiver la fonctionnalité via `monkeypatch.setenv` sans jouer
avec l'ordre d'import des modules."""

import os

from authlib.integrations.flask_client import OAuth

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Instance unique, partagée par toute l'app — voir `init_oauth`, appelée une fois depuis
# `bloc4_publication.app.create_app()`. Les routes (accounts/routes.py) importent CET objet
# (`from accounts.oauth import oauth`), pas un client déjà résolu : `oauth.google` est un
# attribut posé dynamiquement par `oauth.register(...)` ci-dessous, donc les tests peuvent le
# remplacer par un mock après coup (voir tests/test_accounts_google_oauth.py).
oauth = OAuth()


def google_oauth_enabled() -> bool:
    """Les deux variables d'environnement sont-elles présentes — pas de bouton/route Google sans
    elles, jamais une moitié de configuration silencieusement cassée."""
    return bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(os.environ.get("GOOGLE_CLIENT_SECRET"))


def init_oauth(app) -> None:
    """Appelé une fois depuis `bloc4_publication.app.create_app()`, après `app.secret_key`
    (Authlib s'appuie sur la session Flask pour le `state` anti-CSRF). N'enregistre le client
    Google que si les identifiants sont configurés — voir `google_oauth_enabled`."""
    oauth.init_app(app)
    if google_oauth_enabled():
        oauth.register(
            name="google",
            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            server_metadata_url=GOOGLE_DISCOVERY_URL,
            client_kwargs={"scope": "openid email profile"},
        )
