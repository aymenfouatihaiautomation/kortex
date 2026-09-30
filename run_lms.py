"""Bloc 4/5 — Lance le serveur LMS local (Flask, dev server)."""

from accounts.db import DATABASE_URL, init_db
from bloc4_publication.app import create_app
from bloc5_payment.config import is_mock_mode
from pricing_agent.pricing_state import get_current_price_id, get_current_price_usd

if __name__ == "__main__":
    # Crée les tables comptes si elles n'existent pas encore (idempotent) — voir accounts/db.py
    # pour pourquoi ce n'est PAS fait dans create_app() lui-même.
    init_db()
    print(f"[accounts] Base initialisée : {DATABASE_URL}")

    if is_mock_mode():
        print(
            "[bloc5_payment] Mode MOCK : PADDLE_API_KEY absent de .env — "
            "checkout simulé localement, aucun paiement réel possible. "
            "Ajoute PADDLE_API_KEY (+ PADDLE_PRODUCT_ID + PADDLE_WEBHOOK_SECRET) pour passer en mode réel."
        )
    price_id = get_current_price_id()
    print(
        f"[pricing_agent] Prix actif : ${get_current_price_usd():.2f} "
        f"({'prix par défaut, Phase 1 pas encore appliquée' if price_id is None else f'price_id={price_id}'})"
    )
    app = create_app()
    app.run(host="127.0.0.1", port=5050, debug=True)
