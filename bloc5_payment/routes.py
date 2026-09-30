"""Bloc 5 — Routes Flask : démarrage du paiement, page de paiement simulée (mode mock), et
webhook Paddle qui accorde l'accès au LMS (Bloc 4) après confirmation."""

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from bloc4_publication.access_store import SLUG_COURS_1, grant_access
from bloc4_publication.content_loader import get_course_by_slug
from bloc5_payment.config import is_mock_mode
from bloc5_payment.paddle_client import (
    create_checkout,
    parse_completed_transaction,
    verify_webhook_signature,
)
from pricing_agent import pricing_state, sales_log

bloc5_bp = Blueprint("bloc5_payment", __name__)

# Associe transaction_id -> email pour la page de paiement simulée. En mémoire (process),
# suffisant pour du développement local — pas un stockage persistant de commandes réelles.
_MOCK_TRANSACTIONS: dict[str, str] = {}


@bloc5_bp.route("/checkout/start")
def checkout_start():
    email = request.args.get("email", "").strip()
    if not email:
        abort(400, "email requis")

    # `slug` optionnel (Changement 4, Étape D) : le cours 1 (absent, ou explicitement
    # SLUG_COURS_1 — la landing du cours 1 passe désormais toujours son propre slug, voir
    # landing.html) garde TOUJOURS le prix dynamique de pricing_agent, jamais un price_id figé du
    # catalogue — comportement identique à avant ce changement, jamais cassé pour le cours 1.
    slug = request.args.get("slug", "").strip()
    entry = get_course_by_slug(slug) if slug and slug != SLUG_COURS_1 else None

    if entry and entry.get("paddle_price_id"):
        amount_usd = entry.get("price_usd")
        price_id = entry["paddle_price_id"]
    else:
        amount_usd = pricing_state.get_current_price_usd()
        price_id = pricing_state.get_current_price_id()

    result = create_checkout(email, price_id=price_id, amount_usd=amount_usd)
    if result["mock"]:
        _MOCK_TRANSACTIONS[result["transaction_id"]] = email
    return redirect(result["checkout_url"])


@bloc5_bp.route("/checkout/mock/<transaction_id>")
def checkout_mock_page(transaction_id):
    email = request.args.get("email") or _MOCK_TRANSACTIONS.get(transaction_id, "")
    amount_usd = request.args.get("amount_usd", type=float)
    return render_template(
        "checkout_mock.html", transaction_id=transaction_id, email=email, amount_usd=amount_usd
    )


@bloc5_bp.route("/checkout/mock/<transaction_id>/complete", methods=["POST"])
def checkout_mock_complete(transaction_id):
    email = request.form.get("email") or _MOCK_TRANSACTIONS.get(transaction_id)
    if not email:
        abort(400, "email introuvable pour cette transaction simulée")

    amount_usd = pricing_state.get_current_price_usd()
    # SLUG_COURS_1 en dur, volontairement (hors périmètre de l'Étape D) : cette page simule le
    # paiement en mode démo (aucune vraie transaction Paddle, donc aucun price_id réel à
    # résoudre) — la résolution price_id -> slug (Étape D) ne concerne que le webhook réel, voir
    # paddle_client.parse_completed_transaction.
    token = grant_access(email, SLUG_COURS_1)
    sales_log.record_sale(email, amount_usd, source="mock_checkout")
    access_url = url_for("access", token=token, _external=True)
    print(f"[bloc5_payment][mock] Accès accordé à {email} — {access_url}")
    return render_template(
        "checkout_success.html", email=email, access_url=access_url, amount_usd=amount_usd
    )


@bloc5_bp.route("/webhook/paddle", methods=["POST"])
def paddle_webhook():
    if is_mock_mode():
        print("[bloc5_payment][webhook] Mode mock : PADDLE_WEBHOOK_SECRET absent, "
              "vérification de signature court-circuitée.")

    raw_body = request.get_data()
    sig_header = request.headers.get("Paddle-Signature", "")

    if not verify_webhook_signature(raw_body, sig_header):
        abort(403)

    payload = request.get_json(silent=True) or {}
    result = parse_completed_transaction(payload)
    if not result:
        return jsonify({"status": "ignored"}), 200
    email, slug = result

    token = grant_access(email, slug)
    # LIMITE CONNUE (hors périmètre de l'Étape D, non demandée) : ce montant reste celui du
    # pricing_agent (cours 1) même pour un achat d'un AUTRE cours — l'accès (grant_access) est
    # correctement scopé par `slug`, seul ce compteur analytique serait à corriger séparément.
    sales_log.record_sale(email, pricing_state.get_current_price_usd(), source="webhook")
    print(f"[bloc5_payment][webhook] Paiement confirmé pour {email} — lien d'accès : /access/{token}")
    return jsonify({"status": "ok"}), 200
