"""Bloc 4 — Assemble le contenu du cours (Bloc 1 + Bloc 2/3.5) pour l'affichage LMS.

Lecture seule : ne modifie jamais le texte déjà validé, se contente de le charger et de le
structurer pour le rendu (découpage en paragraphes, fusion curriculum + contenu final).
"""

import json
import re
import unicodedata
from pathlib import Path

from markupsafe import Markup, escape

from bloc4_publication.access_store import SLUG_COURS_1
from bloc4_publication.config import DEFAULT_CONTENT_FILE, DEFAULT_CURRICULUM_FILE
from config import DATA_DIR

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _load_json(path: Path | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def slugify(text: str) -> str:
    """Dérive une URL lisible à partir d'un titre (ex. pour /cours/<slug>) — déterministe, pas de
    champ à maintenir séparément. Nécessaire pour que la structure du catalogue supporte plusieurs
    cours (un slug par titre), même si un seul cours existe aujourd'hui."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()


def load_course(
    curriculum_file: Path | str = DEFAULT_CURRICULUM_FILE,
    content_file: Path | str = DEFAULT_CONTENT_FILE,
) -> dict:
    """Fusionne le curriculum (Bloc 1 : titre/objectifs/points clés) et le contenu final
    (Bloc 2/3.5 : lesson_script/exercices/projet final) en une structure unique pour le LMS."""
    curriculum = _load_json(curriculum_file)
    content = _load_json(content_file)

    content_by_number = {c["chapter_number"]: c for c in content["chapters_content"]}
    total_chapters = len(curriculum["chapters"])

    chapters = []
    for chap in curriculum["chapters"]:
        number = chap["number"]
        chapter_content = content_by_number[number]
        chapters.append(
            {
                "number": number,
                "title": chap["title"],
                "learning_objectives": chap["learning_objectives"],
                "key_points": chap["key_points"],
                # Format décidé par le Bloc 1 (voir FORMAT_ENUM) — absent sur un curriculum généré
                # avant cette fonctionnalité (cours 1) : "text" par défaut, comportement inchangé.
                "format": chap.get("format", "text"),
                # lesson_script est absent pour un chapitre "video" pur (voir write_content.py) —
                # .get() partout ci-dessous, jamais un accès direct qui ferait KeyError.
                "lesson_script": chapter_content.get("lesson_script"),
                "video_script": chapter_content.get("video_script"),
                "written_complement": chapter_content.get("written_complement"),
                "content_blocks": chapter_content.get("content_blocks"),
                "comprehension_exercises": chapter_content["comprehension_exercises"],
                "practical_exercise": chapter_content["practical_exercise"],
                "is_final_project": number == total_chapters,
                "has_video": number == 1,
            }
        )

    # Tronquée à 200 caractères : gap_reason (justification marché du sujet, voir
    # pipeline/run_pipeline.py) peut être un paragraphe entier (plusieurs phrases), pas pensé à
    # l'origine pour tenir dans une meta-description/carte de catalogue.
    description = curriculum["source_topic"]["gap_reason"]
    if len(description) > 200:
        description = description[:200] + "..."

    return {
        "title": curriculum["title"],
        "slug": slugify(curriculum["title"]),
        "niche": curriculum["niche"],
        "level": curriculum["level"],
        "prerequisites": curriculum["prerequisites"],
        "description": description,
        "running_example": content.get("running_example"),
        "chapters": chapters,
    }


def _published_courses_path() -> Path:
    return DATA_DIR / "published_courses.json"


def _normalize_published_entry(entry: dict) -> dict:
    """Réconcilie l'écart de nom entre `paddle_price_id` (nom attendu par les consommateurs de ce
    catalogue) et l'ancien `price_id` (nom utilisé par des fichiers `published_courses.json` déjà
    écrits avant le renommage de `pipeline/auto_publish.py`) : `paddle_price_id` fait foi s'il est
    présent, sinon `price_id` — pour qu'un fichier déjà écrit avec l'ancien nom continue de
    fonctionner sans migration manuelle."""
    normalized = dict(entry)
    normalized["paddle_price_id"] = entry.get("paddle_price_id") or entry.get("price_id")
    return normalized


def load_published_courses() -> list[dict]:
    """Charge le catalogue multi-cours (`data/published_courses.json`, écrit par
    `pipeline/auto_publish.py` après feu vert). Chaque entrée a au moins
    `slug`/`title`/`domain`/`price_usd`/`paddle_price_id` (voir `_normalize_published_entry` pour
    la réconciliation avec l'ancien nom `price_id`).

    FALLBACK GARANTI vers `[load_course()]` (le cours 1, comportement inchangé) si le fichier est
    absent, vide, JSON invalide, ou dans une forme inattendue (JSON valide mais pas
    `{"courses": [...]}`) — cette fonction ne lève JAMAIS : le cours 1 doit rester accessible quoi
    qu'il arrive à ce fichier.

    Si le fichier contient N cours valides, retourne exactement ces N entrées (normalisées) —
    pas de fusion avec le cours 1 : s'il doit y figurer, c'est à `published_courses.json` de
    l'inclure explicitement."""
    path = _published_courses_path()
    try:
        if not path.exists():
            return [load_course()]
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return [load_course()]

    courses = raw.get("courses") if isinstance(raw, dict) else None
    if not courses:
        return [load_course()]
    return [_normalize_published_entry(c) for c in courses]


def get_course_by_slug(slug: str) -> dict | None:
    """Cherche `slug` dans le catalogue (voir `load_published_courses`) — `None` si absent,
    jamais d'exception."""
    return next((c for c in load_published_courses() if c.get("slug") == slug), None)


def get_course_by_slug_from_price_id(price_id: str | None) -> str:
    """Résout un `price_id` Paddle vers le SLUG du cours correspondant — cherche la première
    entrée de `load_published_courses()` dont `paddle_price_id == price_id` (nom conservé tel que
    demandé, même si la valeur retournée est un slug, pas un cours).

    FALLBACK GARANTI sur `SLUG_COURS_1` si `price_id` est absent/`None` ou ne correspond à aucun
    cours publié — jamais d'exception : c'est exactement le comportement d'avant le Changement 4
    (tout achat allait au cours 1), préservé pour un webhook qui n'a pas encore de price_id
    reconnaissable (voir bloc5_payment/paddle_client.py::parse_completed_transaction)."""
    if price_id:
        for entry in load_published_courses():
            if entry.get("paddle_price_id") == price_id:
                return entry["slug"]
    return SLUG_COURS_1


def resolve_full_course(entry: dict) -> dict:
    """Retourne un cours COMPLET (avec `chapters`) à partir d'une entrée du catalogue
    (`load_published_courses`/`get_course_by_slug`).

    Le cours 1 en mode fallback EST déjà un `load_course()` complet (retourné tel quel) ; une
    vraie entrée de `published_courses.json` est légère (`slug`/`title`/`domain`/`price_usd`/
    `paddle_price_id`/`curriculum_file`/`content_file`, sans `chapters`) — dans ce cas, charge le
    contenu complet via `load_course(curriculum_file=, content_file=)` (mêmes chemins que
    `pipeline/auto_publish.py::publish_course_files` y a copiés) et y superpose les métadonnées
    catalogue (`domain`/`price_usd`/`paddle_price_id`) que `load_course()` seul ne produit pas."""
    if "chapters" in entry:
        return entry
    course = load_course(curriculum_file=entry["curriculum_file"], content_file=entry["content_file"])
    # "slug" du catalogue, PAS celui que load_course() vient de recalculer via
    # slugify(curriculum["title"]) : ce titre peut avoir changé depuis la découverte du sujet
    # (cas réel, cours 2 — "Sécurisation des systèmes et agents IA..." devenu "Sécuriser les
    # systèmes et agents IA en entreprise..." après Bloc 1), ce qui produirait un slug différent de
    # celui utilisé dans l'URL /cours/<slug> et published_courses.json. course["slug"] est lu par
    # has_access/record_chapter_visit/mark_chapter_complete/le garde-fou anti-cross-course
    # (app.py:265) — un mauvais slug ici bloquerait l'accès d'un acheteur réel à son propre cours.
    course["slug"] = entry.get("slug", course["slug"])
    course["domain"] = entry.get("domain")
    course["price_usd"] = entry.get("price_usd")
    course["paddle_price_id"] = entry.get("paddle_price_id") or entry.get("price_id")
    return course


def get_chapter(course: dict, number: int) -> dict | None:
    return next((c for c in course["chapters"] if c["number"] == number), None)


def _exam_questions_path(course_slug: str) -> Path:
    return DATA_DIR / course_slug / "exam_questions.json"


def exam_bank_available(course_slug: str) -> bool:
    """Vrai si une banque de questions d'examen VÉRIFIÉE existe pour ce cours
    (bloc7_exam_generation) — vérifie seulement la présence du fichier, sans le charger/parser.
    Utilisée pour décider s'il faut PROPOSER l'examen (lien sur le tableau de bord, accès à la
    route /course/<slug>/exam) — voir accounts/exam_routes.py et
    bloc4_publication/app.py::course_home."""
    return _exam_questions_path(course_slug).exists()


def load_exam_questions(course_slug: str) -> list[dict] | None:
    """Charge la banque de questions d'examen VÉRIFIÉES (bloc7_exam_generation, Phase 2 Étape 1) —
    lecture seule, jamais régénérée ici. Chemin identique à celui écrit par
    bloc7_exam_generation.build_exam_bank::save_result (`data/<slug>/exam_questions.json`).

    Retourne None si la banque n'existe pas pour ce cours — JAMAIS une exception : un cours sans
    banque (pas encore générée, ou fichier manquant en production suite à un oubli de
    déploiement) ne doit jamais faire planter la route appelante en 500, voir
    accounts/exam_routes.py, qui affiche alors un message propre."""
    path = _exam_questions_path(course_slug)
    if not path.exists():
        return None
    return _load_json(path)


def lesson_paragraphs(lesson_script: str) -> list[str]:
    """Découpe un lesson_script en paragraphes pour l'affichage (ne modifie pas le texte)."""
    return [p.strip() for p in lesson_script.split("\n\n") if p.strip()]


def render_inline_emphasis(text: str) -> Markup:
    """Filtre Jinja pour le contenu enrichi (Bloc 2, `content_blocks`) : convertit la syntaxe
    `**terme**` en `<strong>terme</strong>`. Échappe d'abord tout le texte (HTML-safe même si le
    LLM produit un jour un caractère `<`/`>` par erreur), puis n'introduit QUE les balises
    `<strong>` construites ici — jamais de HTML provenant directement du LLM."""
    escaped = str(escape(text))
    return Markup(_BOLD_RE.sub(r"<strong>\1</strong>", escaped))
