import json

from bloc4_publication.access_store import SLUG_COURS_1, grant_access, has_access, resolve_token

SLUG_A = "cours-a"
SLUG_B = "cours-b"


def test_grant_access_then_resolve_token(tmp_path):
    store = tmp_path / "access.json"
    token = grant_access("client@example.com", SLUG_A, store_path=store)

    assert resolve_token(token, store_path=store) == ("client@example.com", SLUG_A)


def test_resolve_token_returns_none_for_unknown_token(tmp_path):
    store = tmp_path / "access.json"
    assert resolve_token("not-a-real-token", store_path=store) is None


def test_has_access_true_after_grant(tmp_path):
    store = tmp_path / "access.json"
    grant_access("client@example.com", SLUG_A, store_path=store)
    assert has_access("client@example.com", SLUG_A, store_path=store) is True
    assert has_access("other@example.com", SLUG_A, store_path=store) is False


def test_each_grant_produces_a_distinct_token(tmp_path):
    store = tmp_path / "access.json"
    token1 = grant_access("client@example.com", SLUG_A, store_path=store)
    token2 = grant_access("client@example.com", SLUG_A, store_path=store)
    assert token1 != token2
    assert resolve_token(token1, store_path=store) == ("client@example.com", SLUG_A)
    assert resolve_token(token2, store_path=store) == ("client@example.com", SLUG_A)


def test_store_persists_across_calls(tmp_path):
    store = tmp_path / "access.json"
    token = grant_access("a@example.com", SLUG_A, store_path=store)
    # simule un nouvel appel (ex. une autre requête HTTP) relisant le fichier depuis le disque
    assert resolve_token(token, store_path=store) == ("a@example.com", SLUG_A)
    assert store.exists()


# --- normalisation de la casse (réconciliation Paddle : achat et connexion peuvent différer) ---


def test_grant_access_normalizes_email_case_and_whitespace(tmp_path):
    store = tmp_path / "access.json"
    token = grant_access("  Client@Example.COM  ", SLUG_A, store_path=store)
    assert resolve_token(token, store_path=store) == ("client@example.com", SLUG_A)


def test_has_access_matches_regardless_of_case(tmp_path):
    store = tmp_path / "access.json"
    grant_access("Client@Example.com", SLUG_A, store_path=store)
    assert has_access("client@example.com", SLUG_A, store_path=store) is True
    assert has_access("CLIENT@EXAMPLE.COM", SLUG_A, store_path=store) is True


def test_has_access_matches_regardless_of_surrounding_whitespace(tmp_path):
    store = tmp_path / "access.json"
    grant_access("client@example.com", SLUG_A, store_path=store)
    assert has_access("  client@example.com  ", SLUG_A, store_path=store) is True


# --- multi-cours (Changement 4, Étape A) : accès scopé par slug -------------------------------


def test_has_access_is_scoped_per_course_not_global(tmp_path):
    store = tmp_path / "access.json"
    grant_access("client@example.com", SLUG_A, store_path=store)

    assert has_access("client@example.com", SLUG_A, store_path=store) is True
    assert has_access("client@example.com", SLUG_B, store_path=store) is False


def test_buying_both_courses_grants_access_to_both_independently(tmp_path):
    store = tmp_path / "access.json"
    grant_access("client@example.com", SLUG_A, store_path=store)
    grant_access("client@example.com", SLUG_B, store_path=store)

    assert has_access("client@example.com", SLUG_A, store_path=store) is True
    assert has_access("client@example.com", SLUG_B, store_path=store) is True


def test_resolve_token_returns_the_slug_of_that_specific_purchase(tmp_path):
    store = tmp_path / "access.json"
    token_a = grant_access("client@example.com", SLUG_A, store_path=store)
    token_b = grant_access("client@example.com", SLUG_B, store_path=store)

    assert resolve_token(token_a, store_path=store) == ("client@example.com", SLUG_A)
    assert resolve_token(token_b, store_path=store) == ("client@example.com", SLUG_B)


# --- fallback critique : grants enregistrés AVANT l'ajout du champ "slug" ---------------------


def _write_legacy_grant(store_path, token, email):
    """Simule un grant tel qu'il existait avant le Changement 4 : pas de champ "slug" du tout."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps({token: {"email": email, "granted_at": "2026-01-01T00:00:00+00:00"}}), encoding="utf-8"
    )


def test_has_access_falls_back_to_course_1_for_legacy_grant_without_slug(tmp_path):
    store = tmp_path / "access.json"
    _write_legacy_grant(store, "legacy-token", "ancien-client@example.com")

    assert has_access("ancien-client@example.com", SLUG_COURS_1, store_path=store) is True
    assert has_access("ancien-client@example.com", SLUG_B, store_path=store) is False


def test_resolve_token_falls_back_to_course_1_for_legacy_grant_without_slug(tmp_path):
    store = tmp_path / "access.json"
    _write_legacy_grant(store, "legacy-token", "ancien-client@example.com")

    assert resolve_token("legacy-token", store_path=store) == ("ancien-client@example.com", SLUG_COURS_1)
