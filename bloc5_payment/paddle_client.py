"""Bloc 5 — Client Paddle (Merchant of Record) : création de transaction/checkout, vérification
de signature webhook, extraction de l'email client d'un paiement confirmé.

Toute la forme réelle de l'API Paddle (Billing v2 : /transactions, header Paddle-Signature au
format "ts=...;h1=...", événements transaction.completed/transaction.paid) est respectée même en
mode mock, pour que brancher les vraies clés plus tard ne change que la config, pas le code.
"""

import hashlib
import hmac
import uuid

import requests

from bloc4_publication.content_loader import get_course_by_slug_from_price_id
from bloc5_payment.config import (
    PADDLE_API_BASE,
    PADDLE_API_KEY,
    PADDLE_PRICE_ID,
    PADDLE_PRODUCT_ID,
    PADDLE_WEBHOOK_SECRET,
    is_mock_mode,
)


class PaddleError(RuntimeError):
    """Levée quand un appel réel à l'API Paddle échoue."""


def resolve_price_id(price_id: str | None = None) -> str | None:
    """Résout le price_id Paddle à utiliser : celui passé explicitement (normalement
    `pricing_agent.pricing_state.get_current_price_id()`), sinon le `PADDLE_PRICE_ID` statique
    de `.env`. Partagé par `create_checkout` (transaction serveur, mode mock/API réelle) ET par
    `bloc4_publication/app.py::course_landing` (overlay Paddle.js côté client, mode live) — les
    deux chemins doivent toujours résoudre exactement le même price_id, jamais une logique
    dupliquée qui pourrait diverger."""
    return price_id or PADDLE_PRICE_ID


def create_checkout(email: str, price_id: str | None = None, amount_usd: float | None = None) -> dict:
    """Crée une transaction Paddle et retourne {"checkout_url", "mock", "transaction_id"}.

    `price_id` : voir `resolve_price_id`. `amount_usd` : uniquement pour affichage en mode mock.

    Mode mock (PADDLE_API_KEY absent) : ne fait aucun appel réseau, retourne une URL locale
    simulant la page de paiement — permet de développer/tester tout le flux sans compte Paddle
    réel.

    NOTE (overlay Paddle.js, voir bloc4_publication/templates/landing.html) : en mode live avec
    `PADDLE_CLIENT_TOKEN` configuré, l'achat réel passe désormais par `Paddle.Checkout.open` côté
    client, qui crée sa propre transaction — cette branche réelle ci-dessous n'est alors plus
    appelée par le bouton d'achat. Elle reste utile (API existante, pas de raison de la retirer)
    et continue d'être exercée par le mode mock/tests via `/checkout/start`."""
    if is_mock_mode():
        transaction_id = f"mock_{uuid.uuid4().hex[:12]}"
        checkout_url = f"/checkout/mock/{transaction_id}?email={email}"
        if amount_usd is not None:
            checkout_url += f"&amount_usd={amount_usd}"
        return {"checkout_url": checkout_url, "mock": True, "transaction_id": transaction_id}

    resolved_price_id = resolve_price_id(price_id)
    if not resolved_price_id:
        raise PaddleError(
            "Aucun price_id Paddle actif : exécutez "
            "pricing_agent.launch_pricing.apply_launch_price() après confirmation, ou définissez "
            "PADDLE_PRICE_ID dans .env."
        )

    response = requests.post(
        f"{PADDLE_API_BASE}/transactions",
        headers={"Authorization": f"Bearer {PADDLE_API_KEY}", "Content-Type": "application/json"},
        json={"items": [{"price_id": resolved_price_id, "quantity": 1}], "customer": {"email": email}},
        timeout=30,
    )
    if response.status_code >= 300:
        raise PaddleError(f"Échec création transaction Paddle ({response.status_code}) : {response.text[:500]}")

    data = response.json()["data"]
    return {
        "checkout_url": data.get("checkout", {}).get("url"),
        "mock": False,
        "transaction_id": data["id"],
    }


def sync_price_to_paddle(amount_usd: float) -> str:
    """Crée un nouveau Price Paddle pour ce montant et retourne son identifiant.

    Paddle Billing : les Price sont immuables une fois créés — changer le prix crée un NOUVEAU
    Price rattaché au même Product, jamais une modification en place. Utilisé par les deux phases
    du pricing agent (prix de lancement, ajustements à la demande).

    Mode mock (PADDLE_API_KEY absent) : ne fait aucun appel réseau, retourne un identifiant local
    simulé."""
    if is_mock_mode():
        return f"mock_price_{uuid.uuid4().hex[:10]}"

    if not PADDLE_PRODUCT_ID:
        raise PaddleError(
            "PADDLE_PRODUCT_ID manquant dans .env : requis pour créer un nouveau prix Paddle "
            "(le Product doit déjà exister côté dashboard Paddle)."
        )

    response = requests.post(
        f"{PADDLE_API_BASE}/prices",
        headers={"Authorization": f"Bearer {PADDLE_API_KEY}", "Content-Type": "application/json"},
        json={
            "product_id": PADDLE_PRODUCT_ID,
            "description": f"AI Edu Platform — {amount_usd:.2f} USD",
            "unit_price": {"amount": str(round(amount_usd * 100)), "currency_code": "USD"},
        },
        timeout=30,
    )
    if response.status_code >= 300:
        raise PaddleError(f"Échec création prix Paddle ({response.status_code}) : {response.text[:500]}")

    return response.json()["data"]["id"]


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Vérifie la signature HMAC-SHA256 du header `Paddle-Signature` (format "ts=...;h1=...").

    Implémentation manuelle (le SDK officiel `paddle-python-sdk` a été retiré : en local, avec un
    secret et un corps identiques, il retournait `False` là où ce calcul manuel retourne `True` —
    cause exacte non élucidée, mais le SDK n'apporte rien que ce calcul ne fasse déjà).

    Mode mock (PADDLE_WEBHOOK_SECRET absent) : retourne toujours True — le webhook reste
    testable localement sans secret réel, mais `bloc5_payment.routes` logge explicitement quand
    la vérification est court-circuitée."""
    if not PADDLE_WEBHOOK_SECRET:
        return True
    if not signature_header:
        return False

    # .strip() sur chaque partie : résiste à un en-tête du type "ts=123; h1=abc" (espace après le
    # ";") — sans lui, la clé extraite serait " h1" (avec l'espace) et jamais trouvée par
    # parts.get("h1"), faisant échouer la vérification avant même de calculer le HMAC.
    parts = dict(p.strip().split("=", 1) for p in signature_header.split(";") if "=" in p)
    ts = parts.get("ts")
    h1 = parts.get("h1")
    if not ts or not h1:
        return False

    secret = PADDLE_WEBHOOK_SECRET.strip()
    signed_payload = f"{ts}:{raw_body.decode('utf-8')}"
    expected = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, h1)


def _fetch_customer_email(customer_id: str) -> str | None:
    """Récupère l'email d'un client Paddle via `GET /customers/{customer_id}` — nécessaire car un
    vrai webhook `transaction.completed` (Paddle Billing) n'embarque PAS d'objet `customer` avec
    email, seulement une référence `customer_id` (constaté sur un paiement réel, absent de la doc
    utilisée jusqu'ici). Mode mock (PADDLE_API_KEY absent) : ne fait aucun appel réseau, retourne
    None — jamais d'exception ici, ce chemin ne doit jamais faire planter le webhook. Toute erreur
    réseau/HTTP (timeout, 4xx/5xx) est loguée puis traduite en None, même logique fail-safe que le
    reste de ce module."""
    if not PADDLE_API_KEY:
        return None
    try:
        response = requests.get(
            f"{PADDLE_API_BASE}/customers/{customer_id}",
            headers={"Authorization": f"Bearer {PADDLE_API_KEY}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("data", {}).get("email")
    except requests.RequestException as exc:
        print(f"[bloc5_payment][webhook] Échec récupération email customer {customer_id} : {exc}")
        return None


def _extract_price_id(data: dict) -> str | None:
    """`price_id` du premier item de la transaction — `data.items[0].price.id`, PAS un
    `items[0].price_id` à plat (structure confirmée contre la documentation officielle Paddle
    Billing du Transaction object, pas devinée). Défensif à chaque niveau : `items` absent/vide,
    ou `price` absent, retourne `None` plutôt que de lever — laisse
    `get_course_by_slug_from_price_id` retomber sur `SLUG_COURS_1`."""
    items = data.get("items") or []
    if not items:
        return None
    return (items[0].get("price") or {}).get("id")


def parse_completed_transaction(payload: dict) -> tuple[str, str] | None:
    """Extrait `(email, slug)` d'un événement webhook Paddle de paiement confirmé. Retourne None
    si l'événement n'est pas `transaction.completed`/`transaction.paid`, ou si aucun email n'a pu
    être déterminé.

    Email — ordre de résolution inchangé (Changement 4 ne touche que la résolution du slug) :
    (1) `data.customer.email` inline, si un jour Paddle l'ajoute ; (2) `data.customer_email`
    (fallback historique) ; (3) appel API via `data.customer_id` (voir `_fetch_customer_email`).

    Slug — résolu depuis le `price_id` de la transaction (voir `_extract_price_id`) via
    `content_loader.get_course_by_slug_from_price_id` : retombe sur `SLUG_COURS_1` si le
    `price_id` est absent ou ne correspond à aucun cours publié — comportement d'AVANT le
    Changement 4 (tout achat allait au cours 1), préservé à l'identique pour ce cas."""
    if payload.get("event_type") not in ("transaction.completed", "transaction.paid"):
        return None
    data = payload.get("data", {}) or {}
    customer = data.get("customer") or {}

    email = customer.get("email") or data.get("customer_email")
    if not email:
        customer_id = data.get("customer_id")
        if not customer_id:
            return None
        email = _fetch_customer_email(customer_id)

    if not email:
        return None

    slug = get_course_by_slug_from_price_id(_extract_price_id(data))
    return email, slug
