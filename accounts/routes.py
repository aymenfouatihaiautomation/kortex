"""Comptes — routes Flask : inscription, connexion, déconnexion, réinitialisation de mot de
passe.

PHASE 1 uniquement : email + mot de passe. Google OAuth est Phase 2, pas construit ici.

Réutilise `session["email"]` EXACTEMENT comme le mécanisme d'accès existant
(bloc4_publication/app.py, bloc6_chatbot/course_routes.py) : le tuteur, le correcteur et la porte
d'accès aux chapitres continuent de fonctionner SANS aucun changement de leur côté — ils lisent
`session.get("email")`, peu importe qu'il ait été posé par `/access/<token>` (achat) ou par
`/login` (compte). Le garde-fou de sécurité correspondant (un compte sans achat ne doit jamais
lire le contenu payant) est ajouté séparément dans ces deux fichiers via `access_store.has_access`
— voir leur diff, pas ce module.

Cible de redirection post-connexion/inscription : la page d'accueil (`home`), jamais une URL de
cours — voir `_post_login_redirect_target`. `/course` (le tableau de bord "mes cours") n'est PAS
une cible neutre : c'est du contenu de cours gardé par `_has_paid_access`, un compte sans achat y
serait aussitôt renvoyé plus loin. Un paramètre `next` (validé comme chemin interne relatif —
jamais une URL absolue/externe, pour éviter une redirection ouverte) permet de ramener
l'utilisateur vers la page protégée qu'il visait avant d'atterrir sur /login."""

from urllib.parse import urlparse

from authlib.integrations.base_client.errors import OAuthError
from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from accounts.email_sender import send_password_reset_email
from accounts.oauth import google_oauth_enabled, oauth
from accounts.security import ValidationError
from accounts.service import (
    EmailAlreadyRegisteredError,
    account_exists,
    authenticate_user,
    get_or_create_google_user,
    register_user,
    request_password_reset,
    reset_password,
    resolve_reset_token,
)
from bloc6_chatbot.shared import RateLimiter

accounts_bp = Blueprint("accounts", __name__)

# Limiteurs dédiés (réutilisent la même classe que les chatbots, bloc6_chatbot/shared.py) — la
# connexion est la cible la plus sensible au brute force, donc la plus stricte des trois.
_login_rate_limiter = RateLimiter(max_requests=10, window_seconds=300)
_register_rate_limiter = RateLimiter(max_requests=10, window_seconds=3600)
_reset_rate_limiter = RateLimiter(max_requests=5, window_seconds=3600)

# Même message pour "email inconnu" et "mauvais mot de passe" — pas d'énumération de comptes.
GENERIC_LOGIN_ERROR = "Email ou mot de passe incorrect."
GENERIC_RESET_MESSAGE = "Si un compte existe avec cet email, un lien de réinitialisation vient d'être envoyé."
RATE_LIMIT_ERROR = "Trop de tentatives. Réessaie dans quelques minutes."
GOOGLE_LOGIN_ERROR = "La connexion avec Google a échoué. Réessaie."


def _safe_next_path(candidate: str | None) -> str | None:
    """Retourne `candidate` s'il s'agit d'un chemin interne relatif sûr, sinon None.

    Protection contre une redirection ouverte (open redirect) : un `next` absolu
    (`https://evil.com`), protocole-relatif (`//evil.com` — le navigateur le traite comme externe)
    ou sans `/` initial (`evil.com`) est rejeté. `urlparse` seul ne suffit pas ici : il faut aussi
    le test `startswith("/")` explicite, sinon un chemin sans schéma ni netloc mais sans slash
    initial (ex. "evil.com") passerait le test `scheme`/`netloc` tout en étant potentiellement
    réinterprété comme externe par certains contextes."""
    if not candidate:
        return None
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    return candidate


@accounts_bp.context_processor
def _inject_google_enabled():
    # Injecté automatiquement dans tous les templates rendus par ce blueprint (register.html,
    # login.html — voir leur bouton "Se connecter avec Google" conditionnel) : plus simple et
    # moins sujet à l'oubli que de le repasser à chaque appel `render_template` un par un.
    return {"google_enabled": google_oauth_enabled()}


def _redirect_target_from(candidate: str | None) -> str:
    """Cible de redirection à partir d'un `next` déjà extrait : lui-même s'il est sûr, sinon la
    page d'accueil — JAMAIS une URL de cours (voir le docstring du module). Factorisée à part de
    `_post_login_redirect_target` pour que le callback Google (dont le `next` vient de la
    session, pas de la requête courante — voir `login_google`/`google_callback`) réutilise
    EXACTEMENT la même règle."""
    safe_path = _safe_next_path(candidate)
    return safe_path or url_for("home")


def _post_login_redirect_target() -> str:
    """Cible de redirection après connexion/inscription réussie par email + mot de passe :
    `next` s'il est fourni (formulaire ou query string) et sûr, sinon la page d'accueil."""
    candidate = request.form.get("next") or request.args.get("next")
    return _redirect_target_from(candidate)


@accounts_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        next_value = request.args.get("next", "")
        email = request.args.get("email", "")
        # Client qui vient de payer via l'overlay Paddle.js (voir
        # bloc4_publication/templates/landing.html, successUrl -> /register?email=...) : s'il a
        # DÉJÀ un compte (ex. deuxième achat, ou compte créé avant), on l'envoie directement se
        # connecter plutôt que de le faire remplir un formulaire d'inscription qui échouerait au
        # POST — voir accounts/service.py::account_exists pour la note sur l'exposition
        # d'information (pas nouvelle).
        if email and account_exists(email):
            return redirect(url_for("accounts.login", email=email, next=next_value) if next_value else url_for("accounts.login", email=email))
        return render_template("register.html", next=next_value, email=email)

    next_value = request.form.get("next", "")

    if not _register_rate_limiter.allow(request.remote_addr or "unknown"):
        return render_template("register.html", error=RATE_LIMIT_ERROR, next=next_value), 429

    email = request.form.get("email", "")
    password = request.form.get("password", "")

    try:
        user = register_user(email, password)
    except ValidationError as exc:
        return render_template("register.html", error=str(exc), email=email, next=next_value), 400
    except EmailAlreadyRegisteredError as exc:
        return render_template("register.html", error=str(exc), email=email, next=next_value), 400

    session.clear()
    session["email"] = user.email
    return redirect(_post_login_redirect_target())


@accounts_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template(
            "login.html", next=request.args.get("next", ""), email=request.args.get("email", "")
        )

    next_value = request.form.get("next", "")

    if not _login_rate_limiter.allow(request.remote_addr or "unknown"):
        return render_template("login.html", error=RATE_LIMIT_ERROR, next=next_value), 429

    email = request.form.get("email", "")
    password = request.form.get("password", "")

    user = authenticate_user(email, password)
    if not user:
        return render_template("login.html", error=GENERIC_LOGIN_ERROR, email=email, next=next_value), 400

    session.clear()
    session["email"] = user.email
    return redirect(_post_login_redirect_target())


@accounts_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


@accounts_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password_request():
    if request.method == "GET":
        return render_template("reset_request.html")

    if not _reset_rate_limiter.allow(request.remote_addr or "unknown"):
        return render_template("reset_request.html", error=RATE_LIMIT_ERROR), 429

    email = request.form.get("email", "")
    token = request_password_reset(email)
    if token:
        reset_url = url_for("accounts.reset_password_confirm", token=token, _external=True)
        send_password_reset_email(email, reset_url)

    # Même message que l'email existe ou non — voir GENERIC_RESET_MESSAGE.
    return render_template("reset_request.html", message=GENERIC_RESET_MESSAGE)


@accounts_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password_confirm(token):
    user = resolve_reset_token(token)
    if not user:
        return render_template("reset_confirm.html", invalid=True), 400

    if request.method == "GET":
        return render_template("reset_confirm.html", invalid=False)

    new_password = request.form.get("password", "")
    try:
        ok = reset_password(token, new_password)
    except ValidationError as exc:
        return render_template("reset_confirm.html", invalid=False, error=str(exc)), 400

    if not ok:
        return render_template("reset_confirm.html", invalid=True), 400

    return redirect(url_for("accounts.login", reset="1"))


# --- Connexion Google (PHASE 2) -----------------------------------------------------------------
#
# Le login email + mot de passe ci-dessus n'est pas modifié par ce qui suit. Les deux routes
# répondent 404 si GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET ne sont pas configurés (voir
# accounts/oauth.py::google_oauth_enabled) — jamais une exception non rattrapée si le bouton est
# cliqué (ou l'URL visitée directement) alors que Google n'est pas activé sur ce déploiement.


@accounts_bp.route("/login/google")
def login_google():
    if not google_oauth_enabled():
        abort(404)

    # `next` traverse l'aller-retour vers Google via la SESSION, jamais via l'URI de redirection
    # elle-même : cette URI doit correspondre EXACTEMENT à celle déclarée dans Google Cloud
    # Console (http://localhost:5050/login/google/callback en local,
    # https://cours.aymen-automation.site/login/google/callback en prod) — lui ajouter un
    # paramètre supplémentaire risquerait un redirect_uri_mismatch selon la configuration exacte
    # côté Google.
    session["oauth_next"] = _safe_next_path(request.args.get("next")) or ""

    # `_external=True` : Authlib doit recevoir l'URL absolue. Le schéma (http/https) est dérivé
    # de `request.scheme`, correct en local ET en production grâce à ProxyFix (voir
    # bloc4_publication/app.py::create_app — sans lui, ce serait "http://" même derrière le proxy
    # HTTPS de Render, et Google rejetterait l'URI avec redirect_uri_mismatch).
    redirect_uri = url_for("accounts.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@accounts_bp.route("/login/google/callback")
def google_callback():
    if not google_oauth_enabled():
        abort(404)

    next_value = session.pop("oauth_next", "")

    try:
        # Valide le `state` anti-CSRF automatiquement (Authlib le compare à celui posé en
        # session par authorize_redirect ci-dessus) — lève OAuthError (MismatchingStateError) si
        # absent/différent, avant même d'échanger le code contre un token.
        token = oauth.google.authorize_access_token()
    except OAuthError:
        return render_template("login.html", error=GOOGLE_LOGIN_ERROR, next=next_value), 400

    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email")
    # N'accepte QUE les emails que Google a lui-même vérifiés — jamais un email non confirmé
    # comme clé d'identité (voir accounts/service.py::get_or_create_google_user, qui réconcilie
    # par email).
    if not email or not userinfo.get("email_verified"):
        return render_template("login.html", error=GOOGLE_LOGIN_ERROR, next=next_value), 400

    user = get_or_create_google_user(email, google_sub=userinfo.get("sub"))

    session.clear()
    session["email"] = user.email
    # Le nom Google (disponible grâce au scope "profile", jamais stocké en base — pas de colonne
    # `name` sur User) n'est posé qu'en SESSION, pour préremplir le champ nom de l'attestation
    # (accounts/certificate_routes.py::generate) sans jamais persister de donnée profil
    # supplémentaire. Un compte email/mot de passe n'a jamais cette clé (session.clear() ci-
    # dessus l'efface de toute façon à chaque connexion) — le champ reste alors vide, comme prévu.
    name = userinfo.get("name") or userinfo.get("given_name")
    if name:
        session["google_name"] = name
    return redirect(_redirect_target_from(next_value))
