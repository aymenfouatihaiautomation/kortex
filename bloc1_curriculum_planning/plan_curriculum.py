"""Bloc 1 — Planification du programme à partir d'un sujet sélectionné (Bloc 0).

Voir docs/BLOC1_CURRICULUM_PLANNING.md pour la spec complète.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json
from config import DATA_DIR, NICHE

MODEL = "claude-sonnet-5"  # structure fondatrice du cours entier, cf. mapping bloc->modèle validé

SYSTEM_PROMPT = (
    "Tu es un concepteur pédagogique expert en formation professionnelle. "
    "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, "
    "sans bloc de code markdown. "
    "IMPORTANT : tous les guillemets doubles à l'intérieur d'une valeur JSON DOIVENT être échappés "
    "avec un backslash. Exemple : un titre contenant \"Zero Trust\" doit s'écrire "
    '\\"Zero Trust\\" dans la valeur JSON, jamais "Zero Trust" tel quel (cela casserait le parsing).'
)

# Bug réel trouvé sur le 2ème cours (2026-07-31) : LEVEL/PREREQUISITES étaient des constantes
# fixées une fois pour le sujet du Sprint 1 ("fiabiliser des agents en production") et appliquées
# EN DUR à tout curriculum généré, y compris pour un sujet totalement différent (ex. "lancer une
# agence d'automatisation IA") — ne généralise pas dès qu'un 2ème cours existe. Level/prerequisites
# sont désormais dérivés par le LLM à partir du sujet précis (mais bornés : `level` contre un enum
# fermé, `prerequisites` validé structurellement) plutôt que fixés globalement — voir
# `LEVEL_ENUM`/`_validate_level_and_prerequisites`.
LEVEL_ENUM = {"débutant", "intermédiaire", "avancé"}

# Format du contenu principal, décidé PAR CHAPITRE (pas imposé globalement) — ajouté 2026-08-07.
# Absent d'un chapitre = "text" par défaut (voir `chapter.get("format", "text")` partout en aval) :
# permet au cours 1 (déjà en ligne, généré avant cette fonctionnalité) de continuer à s'afficher à
# l'identique sans migration de ses données.
FORMAT_ENUM = {"text", "video", "mix"}

# Critères de décision partagés entre PROMPT_TEMPLATE (nouveau cours) et DECIDE_FORMAT_PROMPT_TEMPLATE
# (rétrofit d'un chapitre déjà écrit) — un seul endroit à ajuster pour ne pas les faire diverger.
# Resserré 2026-08-08 : la première version penchait vers "mix" par défaut dès que le contenu était
# technique (constaté en réel sur le cours 1 : 6 chapitres sur 7 en "mix", aucune variété) — "mix"
# doit rester l'exception (deux couches VRAIMENT distinctes), pas le choix de sécurité en cas
# d'hésitation entre les deux formats simples.
FORMAT_DECISION_CRITERIA = """\
- "video" : l'essentiel est un GESTE, une démo, une manipulation d'interface, un flux visuel à
  suivre — quelque chose qui se comprend mieux en REGARDANT qu'en lisant. Un texte n'apporterait
  pas grand-chose de plus.
- "text" : l'essentiel est une RÉFÉRENCE, une explication conceptuelle, du code à copier, des
  définitions, un raisonnement à relire — quelque chose qu'on consulte et relit, où une vidéo
  obligerait à la rejouer pour retrouver une information précise.
- "mix" : réservé aux chapitres où il y a VRAIMENT deux couches distinctes et complémentaires (un
  geste à montrer ET une référence séparée à garder) — jamais le choix par défaut quand tu hésites.

RÈGLE EXPLICITE : "mix" n'est PAS un choix de sécurité. En cas d'hésitation entre "text" et "mix",
ou entre "video" et "mix", préfère le format simple ("text" ou "video") SAUF s'il y a réellement
deux contenus distincts qui méritent chacun leur propre support. Ne force AUCUNE répartition
artificielle entre les 3 formats : chaque chapitre reçoit le format que SON contenu justifie, même
si cela donne un cours majoritairement — voire entièrement — d'un seul format.\
"""

PROMPT_TEMPLATE = """\
Niche : "{niche}".
Sujet de cours sélectionné : "{topic_title}".
Raison de la sélection de ce sujet : {gap_reason}

Construis la structure complète de ce cours : un titre final, un niveau, les prérequis, et une
séquence de chapitres.

- level : détermine, à partir de la complexité RÉELLE de ce sujet précis (pas une valeur par
  défaut), un niveau parmi EXACTEMENT "débutant", "intermédiaire" ou "avancé".
- prerequisites : une phrase précise décrivant ce que l'apprenant doit déjà savoir/avoir AVANT de
  suivre CE cours précis (jamais un texte générique copié d'un autre sujet) ; si aucun prérequis
  particulier n'est nécessaire, dis-le explicitement plutôt que d'inventer un prérequis qui ne
  correspond pas au sujet.

Chaque chapitre doit obligatoirement inclure :
- number : numéro du chapitre (entier, commence à 1, sans trou dans la séquence)
- title : titre du chapitre
- learning_objectives : liste d'au moins 2 objectifs pédagogiques concrets (ce que l'apprenant sait
  faire à la fin du chapitre)
- key_points : liste d'au moins 3 points clés/notions couverts dans le chapitre
- builds_on_previous : explique en une phrase comment ce chapitre s'appuie sur le chapitre
  précédent (pour le chapitre 1, écris exactement "N/A - premier chapitre")
- format : le format de contenu PRINCIPAL le plus adapté à CE chapitre précis, choisi parmi
  EXACTEMENT "text", "video" ou "mix" — un vrai choix par chapitre, jamais le même partout par
  défaut :
{format_decision_criteria}
- format_reasoning : 1-2 phrases qui justifient CE choix pour CE chapitre précis (pas une
  justification générique interchangeable d'un chapitre à l'autre).

Le cours doit obligatoirement viser un niveau pratique réel (pas seulement théorique) : la séquence
de chapitres doit converger vers un projet final applicable. Prévois entre 5 et 8 chapitres, le
dernier chapitre étant explicitement le projet final intégrateur.

Réponds avec EXACTEMENT ce format JSON :
{{
  "title": "...",
  "niche": "{niche}",
  "level": "...",
  "prerequisites": "...",
  "source_topic": {{"title": "{topic_title}", "gap_reason": "{gap_reason}"}},
  "chapters": [
    {{
      "number": 1,
      "title": "...",
      "learning_objectives": ["...", "..."],
      "key_points": ["...", "...", "..."],
      "builds_on_previous": "N/A - premier chapitre",
      "format": "text",
      "format_reasoning": "..."
    }}
  ]
}}
"""

REGENERATE_LEVEL_PROMPT_TEMPLATE = """\
Niche : "{niche}".
Cours déjà structuré, chapitres FIXES (ne les invente pas différemment, sers-t-en uniquement pour
juger la complexité réelle du cours) :
Titre : "{course_title}"
{chapters_summary}

Détermine, à partir de CE cours précis (pas d'un autre sujet) :
- level : un niveau parmi EXACTEMENT "débutant", "intermédiaire" ou "avancé", cohérent avec la
  complexité réelle du contenu ci-dessus.
- prerequisites : une phrase précise décrivant ce que l'apprenant doit déjà savoir/avoir AVANT de
  suivre CE cours (jamais un texte générique copié d'un autre sujet) ; si aucun prérequis
  particulier n'est nécessaire, dis-le explicitement.

Réponds avec EXACTEMENT ce format JSON :
{{
  "level": "...",
  "prerequisites": "..."
}}
"""

RETRY_SUFFIX = """

ATTENTION : ta réponse précédente était invalide pour la raison suivante :
{errors}
Corrige ces problèmes et renvoie un JSON complet et valide respectant strictement le format demandé.
"""

DEMO_LEVEL = "intermédiaire"
DEMO_PREREQUISITES = (
    "L'apprenant doit être à l'aise avec les bases du no-code/automatisation (créer un compte, "
    "utiliser une API simple) — ce cours structure un apprentissage progressif à partir de ces bases."
)

DEMO_CURRICULUM_CHAPTERS = [
    {
        "number": 1,
        "title": "Comprendre l'automatisation IA et poser les bases avec n8n",
        "learning_objectives": [
            "Expliquer ce qu'est un workflow d'automatisation et où l'IA apporte de la valeur",
            "Installer et prendre en main l'interface n8n",
        ],
        "key_points": [
            "Différence automatisation classique vs automatisation pilotée par IA",
            "Notions de trigger, node, workflow",
            "Premier workflow simple (webhook -> action)",
        ],
        "builds_on_previous": "N/A - premier chapitre",
        "format": "mix",
        "format_reasoning": (
            "[DEMO] La prise en main de l'interface n8n se montre mieux en vidéo (clics, glisser-"
            "déposer des nodes) ; les définitions (trigger/node/workflow, automatisation classique "
            "vs pilotée par IA) sont une référence à relire, mieux servie par du texte — les deux "
            "sont complémentaires, pas redondants."
        ),
    },
    {
        "number": 2,
        "title": "Connecter n8n à une IA générative",
        "learning_objectives": [
            "Intégrer un appel à un modèle de langage dans un workflow n8n",
            "Structurer un prompt pour obtenir une sortie exploitable par le workflow",
        ],
        "key_points": [
            "Node HTTP Request vs node IA dédié",
            "Gestion des clés API et des credentials dans n8n",
            "Parsing d'une réponse JSON dans un workflow",
        ],
        "builds_on_previous": "S'appuie sur le workflow de base du chapitre 1 en y ajoutant un appel IA.",
        "format": "video",
        "format_reasoning": (
            "[DEMO] Ce chapitre est fondamentalement une démonstration : configurer un node, entrer "
            "une clé API, brancher un prompt, observer le JSON de sortie — un flux d'actions à "
            "l'écran qu'un texte décrirait moins bien qu'une vidéo, sans dupliquer d'explication "
            "longue à côté."
        ),
    },
    {
        "number": 3,
        "title": "Projet final : automatiser un processus métier réel de bout en bout",
        "learning_objectives": [
            "Concevoir un workflow complet résolvant un vrai problème métier",
            "Déployer et tester le workflow en conditions réelles",
        ],
        "key_points": [
            "Choix d'un cas d'usage métier concret",
            "Gestion des erreurs et des cas limites dans un workflow",
            "Documentation et remise du projet",
        ],
        "builds_on_previous": "Combine les briques des chapitres 1 et 2 (workflow + appel IA) dans un projet complet.",
        "format": "text",
        "format_reasoning": (
            "[DEMO] Le projet final est une référence de méthode (choix du cas d'usage, gestion "
            "d'erreurs, documentation) que l'apprenant consulte et suit à son rythme sur plusieurs "
            "séances — un texte structuré sert mieux ce usage qu'une vidéo qu'il faudrait rejouer "
            "pour retrouver un détail précis."
        ),
    },
]


def build_prompt(topic_title: str, gap_reason: str, error_feedback: str | None = None) -> str:
    prompt = PROMPT_TEMPLATE.format(
        niche=NICHE,
        topic_title=topic_title,
        gap_reason=gap_reason,
        format_decision_criteria=FORMAT_DECISION_CRITERIA,
    )
    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def build_regenerate_level_prompt(curriculum: dict, error_feedback: str | None = None) -> str:
    chapters_summary = "\n".join(f"- Chapitre {c['number']} : {c['title']}" for c in curriculum["chapters"])
    prompt = REGENERATE_LEVEL_PROMPT_TEMPLATE.format(
        niche=curriculum.get("niche", NICHE),
        course_title=curriculum["title"],
        chapters_summary=chapters_summary,
    )
    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def _validate_level_and_prerequisites(data: dict) -> list[str]:
    errors: list[str] = []

    level = data.get("level")
    if level not in LEVEL_ENUM:
        errors.append(f"level invalide : {level!r}, attendu l'un de {sorted(LEVEL_ENUM)}.")

    prerequisites = data.get("prerequisites")
    if not isinstance(prerequisites, str) or len(prerequisites.strip()) < 10:
        errors.append("prerequisites manquant, vide ou trop court (description spécifique attendue).")

    return errors


def validate_curriculum(curriculum: dict) -> list[str]:
    """Retourne la liste des erreurs de validation (vide = valide)."""
    errors: list[str] = list(_validate_level_and_prerequisites(curriculum))
    chapters = curriculum.get("chapters")

    if not chapters or not isinstance(chapters, list):
        return errors + ["Le champ 'chapters' est manquant ou vide."]

    numbers = [c.get("number") for c in chapters]
    expected = list(range(1, len(chapters) + 1))
    if numbers != expected:
        errors.append(f"Numérotation des chapitres invalide : {numbers}, attendu {expected}.")

    for c in chapters:
        num = c.get("number", "?")
        if not c.get("learning_objectives"):
            errors.append(f"Chapitre {num} : learning_objectives vide.")
        if not c.get("key_points"):
            errors.append(f"Chapitre {num} : key_points vide.")
        builds_on = c.get("builds_on_previous", "")
        if num == 1:
            if builds_on != "N/A - premier chapitre":
                errors.append(f"Chapitre 1 : builds_on_previous doit être 'N/A - premier chapitre'.")
        elif not builds_on or not builds_on.strip():
            errors.append(f"Chapitre {num} : builds_on_previous vide (séquence logique non justifiée).")

        chapter_format = c.get("format")
        if chapter_format not in FORMAT_ENUM:
            errors.append(f"Chapitre {num} : format invalide {chapter_format!r}, attendu l'un de {sorted(FORMAT_ENUM)}.")
        if not (c.get("format_reasoning") or "").strip():
            errors.append(f"Chapitre {num} : format_reasoning manquant ou vide (le choix de format doit être justifié).")

    return errors


def plan_curriculum(topic: dict, demo: bool = False) -> dict:
    """Exécute le Bloc 1 et retourne une structure de cours validée.

    `level`/`prerequisites` sont dérivés du sujet précis (par le LLM en mode réel, par un stub fixe
    en mode démo) — jamais une constante partagée entre tous les cours, voir le commentaire sur
    `LEVEL_ENUM` plus haut."""
    if demo:
        curriculum = {
            "title": f"{topic['title']} — Formation complète",
            "niche": NICHE,
            "level": DEMO_LEVEL,
            "prerequisites": DEMO_PREREQUISITES,
            "source_topic": {"title": topic["title"], "gap_reason": topic.get("gap_reason", "")},
            "chapters": [dict(c) for c in DEMO_CURRICULUM_CHAPTERS],
        }
        errors = validate_curriculum(curriculum)
        if errors:
            raise LLMCallError(f"Données démo invalides (bug interne) : {errors}")
        curriculum["generated_at"] = datetime.now(timezone.utc).isoformat()
        return curriculum

    gap_reason = topic.get("gap_reason", "")
    error_feedback = None
    last_errors: list[str] = []
    tracker = CostTracker(label="Bloc 1 - plan_curriculum")

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = call_llm_api(
            prompt=build_prompt(topic["title"], gap_reason, error_feedback),
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=4096,
            tracker=tracker,
            task="curriculum",
        )
        # JSON malformé (guillemet interne mal échappé, etc.) : traité comme une erreur de
        # validation, pas une exception qui tue le retry — constaté en production (2 échecs réels),
        # `extract_json` était auparavant appelé hors de tout try/except ici, donc son
        # `LLMCallError` court-circuitait le retry déjà prévu pour les erreurs de VALIDATION.
        # Le malformage est stochastique (une reformulation obtient généralement une réponse
        # propre) : le retry existant suffit, pas besoin de deviner toutes les façons dont un LLM
        # peut casser du JSON.
        try:
            curriculum = extract_json(response_text)
        except LLMCallError as exc:
            last_errors = [f"Réponse JSON invalide : {exc}"]
            error_feedback = "\n".join(f"- {e}" for e in last_errors)
            continue
        last_errors = validate_curriculum(curriculum)
        if not last_errors:
            curriculum["generated_at"] = datetime.now(timezone.utc).isoformat()
            tracker.print_summary()
            return curriculum
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    tracker.print_summary()
    raise LLMCallError(
        f"Structure de cours invalide après {attempt + 1} tentative(s) : {last_errors}"
    )


def regenerate_level_and_prerequisites(curriculum: dict) -> dict:
    """Redétermine UNIQUEMENT level/prerequisites d'un curriculum DÉJÀ généré (chapitres inchangés) —
    pour corriger une valeur mal dérivée (ex. héritée à tort d'un autre cours) sans regénérer le
    reste. Retourne {"level": ..., "prerequisites": ...} ; l'appelant applique la correction."""
    error_feedback = None
    last_errors: list[str] = []
    tracker = CostTracker(label="Bloc 1 - regenerate_level_and_prerequisites")

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = call_llm_api(
            prompt=build_regenerate_level_prompt(curriculum, error_feedback),
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=512,
            tracker=tracker,
            task="curriculum",
        )
        try:
            result = extract_json(response_text)
        except LLMCallError as exc:
            last_errors = [f"Réponse JSON invalide : {exc}"]
            error_feedback = "\n".join(f"- {e}" for e in last_errors)
            continue
        last_errors = _validate_level_and_prerequisites(result)
        if not last_errors:
            tracker.print_summary()
            return {"level": result["level"], "prerequisites": result["prerequisites"]}
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    tracker.print_summary()
    raise LLMCallError(
        f"level/prerequisites invalides après {attempt + 1} tentative(s) : {last_errors}"
    )


DECIDE_FORMAT_PROMPT_TEMPLATE = """\
Niche : "{niche}". Cours : "{course_title}" (niveau {level}).
Chapitre {number} : "{chapter_title}".

Objectifs pédagogiques :
{objectives}
Points clés couverts :
{key_points}

Extrait du contenu RÉEL déjà écrit pour ce chapitre (pour juger sur le fond, pas seulement le
titre) :
--- DÉBUT DE L'EXTRAIT ---
{lesson_excerpt}
--- FIN DE L'EXTRAIT{truncated_note} ---

Détermine le format de contenu PRINCIPAL le plus adapté à CE chapitre précis, à partir de son
contenu réel ci-dessus, choisi parmi EXACTEMENT "text", "video" ou "mix" — un vrai choix par
chapitre, jamais le même partout par défaut :
{format_decision_criteria}

Réponds avec EXACTEMENT ce format JSON :
{{"format": "...", "format_reasoning": "..."}}
(format_reasoning : 1-2 phrases qui justifient CE choix pour CE chapitre précis, à partir de son
contenu réel, pas une justification générique interchangeable d'un chapitre à l'autre)
"""


def build_decide_format_prompt(
    niche: str, course_title: str, level: str, chapter: dict, lesson_script: str, error_feedback: str | None = None
) -> str:
    objectives = "\n".join(f"- {o}" for o in chapter["learning_objectives"])
    key_points = "\n".join(f"- {kp}" for kp in chapter["key_points"])
    excerpt_limit = 2500
    truncated = len(lesson_script) > excerpt_limit
    prompt = DECIDE_FORMAT_PROMPT_TEMPLATE.format(
        niche=niche,
        course_title=course_title,
        level=level,
        number=chapter["number"],
        chapter_title=chapter["title"],
        objectives=objectives,
        key_points=key_points,
        lesson_excerpt=lesson_script[:excerpt_limit],
        truncated_note=" (tronqué)" if truncated else "",
        format_decision_criteria=FORMAT_DECISION_CRITERIA,
    )
    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def _validate_chapter_format(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("format") not in FORMAT_ENUM:
        errors.append(f"format invalide : {data.get('format')!r}, attendu l'un de {sorted(FORMAT_ENUM)}.")
    if not (data.get("format_reasoning") or "").strip():
        errors.append("format_reasoning manquant ou vide.")
    return errors


def decide_chapter_format(
    niche: str,
    course_title: str,
    level: str,
    chapter: dict,
    lesson_script: str,
    tracker: CostTracker | None = None,
) -> dict:
    """Détermine le format ("text"/"video"/"mix") d'un chapitre DÉJÀ ÉCRIT, à partir de son
    contenu réel — utilisé pour appliquer rétroactivement le modèle "format par chapitre" à un
    cours généré avant cette fonctionnalité (ex. cours 1), sans regénérer son contenu. Retourne
    {"format": ..., "format_reasoning": ...} ; l'appelant applique la décision."""
    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 1 - decide_chapter_format (chapitre {chapter['number']})")

    error_feedback = None
    last_errors: list[str] = []

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = call_llm_api(
            prompt=build_decide_format_prompt(niche, course_title, level, chapter, lesson_script, error_feedback),
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=512,
            tracker=tracker,
            task="curriculum",
        )
        result = extract_json(response_text)
        last_errors = _validate_chapter_format(result)
        if not last_errors:
            if own_tracker:
                tracker.print_summary()
            return {"format": result["format"], "format_reasoning": result["format_reasoning"]}
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    if own_tracker:
        tracker.print_summary()
    raise LLMCallError(
        f"format du chapitre {chapter['number']} invalide après {attempt + 1} tentative(s) : {last_errors}"
    )


def save_result(curriculum: dict) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = DATA_DIR / f"bloc1_curriculum_{timestamp}.json"
    md_path = DATA_DIR / f"bloc1_curriculum_{timestamp}.md"

    json_path.write_text(json.dumps(curriculum, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(curriculum), encoding="utf-8")
    return json_path, md_path


def to_markdown(curriculum: dict) -> str:
    lines = [
        f"# {curriculum['title']}",
        "",
        f"Niche : {curriculum['niche']}",
        f"Niveau : {curriculum.get('level', 'N/A')}",
        f"Prérequis : {curriculum.get('prerequisites', 'N/A')}",
        "",
    ]
    for c in curriculum["chapters"]:
        lines.append(f"## Chapitre {c['number']} — {c['title']}")
        lines.append("")
        lines.append("**Objectifs pédagogiques :**")
        for obj in c["learning_objectives"]:
            lines.append(f"- {obj}")
        lines.append("")
        lines.append("**Points clés :**")
        for kp in c["key_points"]:
            lines.append(f"- {kp}")
        lines.append("")
        lines.append(f"**Lien avec le chapitre précédent :** {c['builds_on_previous']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 1 — Planification du programme")
    parser.add_argument("--demo", action="store_true", help="Mode démo : données stub")
    parser.add_argument("--topic", type=str, help="Titre du sujet sélectionné (hors mode démo)")
    parser.add_argument("--gap-reason", type=str, default="", help="Raison de sélection du sujet")
    args = parser.parse_args()

    if args.demo:
        topic = {"title": "Automatiser ses workflows métier avec n8n", "gap_reason": ""}
    else:
        if not args.topic:
            parser.error("--topic est requis hors mode --demo")
        topic = {"title": args.topic, "gap_reason": args.gap_reason}

    curriculum = plan_curriculum(topic, demo=args.demo)
    print(to_markdown(curriculum))
    json_path, md_path = save_result(curriculum)
    print(f"Sauvegardé : {json_path}")
    print(f"Export lisible : {md_path}")


if __name__ == "__main__":
    main()
