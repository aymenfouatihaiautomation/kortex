"""Bloc 6 — Construction du contexte catalogue injecté dans le prompt système du chatbot général
(context-stuffing : le catalogue est petit, pas besoin de ChromaDB/RAG — voir passation §8).

Ne jamais inclure le contenu payant (leçons, exercices) : uniquement les métadonnées publiques
déjà affichées sur les pages marketing (`catalog.html`, `landing.html`) — slug, titre,
description, niveau, prérequis, et la LISTE DES TITRES de chapitres."""


def build_catalog_context(courses: list[dict]) -> str:
    """Un bloc de texte par cours de `courses` (structure produite par
    `bloc4_publication.content_loader.load_course`). Ne contient jamais le prix — voir
    `build_price_context`, tenu séparé pour rester en dehors du bloc mis en cache (le prix peut
    changer dynamiquement via pricing_agent, le reste du catalogue non)."""
    if not courses:
        return "Aucun cours n'est actuellement au catalogue."

    parts = []
    for course in courses:
        chapter_titles = "\n".join(f"  {c['number']}. {c['title']}" for c in course["chapters"])
        parts.append(
            f"### {course['title']}\n"
            f"- Slug (URL du cours, sur /cours/<slug>) : {course['slug']}\n"
            f"- Niveau : {course['level']}\n"
            f"- Prérequis : {course['prerequisites']}\n"
            f"- Description : {course['description']}\n"
            f"- Chapitres :\n{chapter_titles}"
        )
    return "\n\n".join(parts)


def build_price_context(courses: list[dict], price_usd: float) -> str:
    """Bloc de prix séparé du reste du catalogue (voir `build_catalog_context`) — un seul prix
    global aujourd'hui (`pricing_agent.get_current_price_usd`, un seul cours en vente), appliqué à
    chaque cours listé, cohérent avec le reste du LMS (`bloc4_publication/app.py`)."""
    if not courses:
        return ""
    lines = "\n".join(f"- {c['title']} : ${price_usd:.2f} (achat unique, accès à vie)" for c in courses)
    return f"Prix actuels :\n{lines}"
