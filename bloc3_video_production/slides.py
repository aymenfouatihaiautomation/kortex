"""Bloc 3 — Découpage de chaque lesson_script en diapositives.

Design clé : le LLM ne reproduit JAMAIS le texte de la leçon dans sa réponse. Le découpage en
phrases est fait déterministiquement côté Python (`split_sentences`), et le LLM se contente de
choisir où regrouper ces phrases numérotées en diapositives (`start_sentence`/`end_sentence`) et
d'extraire un titre visuel + des termes/chiffres clés. Le texte narré de chaque diapositive est
ensuite reconstruit par simple découpe de la liste de phrases originale — la fidélité verbatim est
garantie par construction, pas par une validation a posteriori fragile.
"""

import re

from common.llm_client import LLMCallError, extract_json, run_prompt

SYSTEM_PROMPT = (
    "Tu es un monteur vidéo pédagogique. Tu ne rédiges ni ne reformules jamais le contenu d'un "
    "cours, tu décides seulement comment le découper en diapositives et quoi y mettre en valeur "
    "visuellement. Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, "
    "sans bloc de code markdown."
)

PROMPT_TEMPLATE = """\
Voici le script d'une leçon ("{chapter_title}"), déjà découpé en {n} phrases numérotées (1-indexé) :
{numbered_sentences}

Regroupe ces phrases en diapositives pour une vidéo pédagogique Faceless (diapositives + voix) :
au moins une diapositive par idée clé ou sous-point du texte — jamais un seul bloc continu pendant
toute la narration. Vise des groupes de 2 à 5 phrases par diapositive selon la densité de l'idée
(une transition ou un exemple chiffré important peut justifier une diapositive à lui seul).

RÈGLE ABSOLUE : ne modifie, ne résume et ne reformule JAMAIS le texte des phrases. Tu ne reproduis
JAMAIS ce texte dans ta réponse — tu indiques seulement des numéros de phrases (start_sentence,
end_sentence).

Pour chaque diapositive, fournis aussi :
- visual_title : titre court (5-8 mots) résumant l'idée de cette diapositive, à afficher à l'écran
  (nouveau texte que tu rédiges, pas une phrase du script)
- key_terms : 2 à 5 termes techniques extraits VERBATIM des phrases de cette diapositive
- key_numbers : chiffres/statistiques/exemples chiffrés extraits VERBATIM des phrases de cette
  diapositive (liste vide si aucun chiffre)

Les diapositives doivent couvrir TOUTES les phrases, dans l'ordre, sans trou ni chevauchement : la
première diapositive commence à la phrase 1, la dernière se termine à la phrase {n}.

Réponds avec EXACTEMENT ce format JSON :
{{
  "slides": [
    {{"start_sentence": 1, "end_sentence": 3, "visual_title": "...", "key_terms": ["...", "..."], "key_numbers": []}}
  ]
}}
"""

RETRY_SUFFIX = """

ATTENTION : ta réponse précédente était invalide pour la raison suivante :
{errors}
Corrige ces problèmes et renvoie un JSON complet et valide respectant strictement le format demandé.
"""

# Enum fermé d'icônes (même principe que LEVEL_ENUM au Bloc 1, category au Bloc 3.5) : le LLM
# choisit un traitement visuel adapté au contenu, mais ne peut pas inventer un nom d'icône
# arbitraire — chaque nom doit exister côté Remotion (remotion/src/RichSlideVisuals.tsx::ICONS,
# à garder synchronisé avec cette liste).
DIAGRAM_ICONS = [
    "Brain", "Wrench", "Database", "Workflow", "Bug", "AlertTriangle", "CheckCircle", "XCircle",
    "Clock", "DollarSign", "TrendingUp", "TrendingDown", "Shield", "Server", "Cloud", "Cpu",
    "FlaskConical", "Gauge", "RefreshCw", "Zap", "MessageSquare", "Users", "FileText", "Settings",
    "Activity", "Target", "Layers", "GitBranch", "Lock", "Eye",
]

RICH_STYLE_PROMPT_ADDITION = """

Détermine aussi, pour CHAQUE diapositive, un traitement visuel adapté à son contenu réel (pas
seulement du texte animé) :
- visual_type : "diagram" si la diapositive décrit une architecture ou une relation entre plusieurs
  composants structurels distincts (ex. "les quatre composants d'un agent") ; "timeline" si elle
  décrit une séquence chronologique ou numérotée d'étapes (ex. "une semaine en production") ;
  sinon "default".
- Si visual_type = "diagram" : diagram_hub = {{"label": "...", "icon": "..."}} (élément central) et
  diagram_satellites = liste de 2 à 4 {{"label": "...", "icon": "..."}} (éléments reliés au hub).
  "label" = texte court (1-3 mots) que TU rédiges pour nommer le composant (pas une phrase copiée
  du script). "icon" = un nom EXACT (respecte la casse) parmi cette liste, le plus pertinent
  possible : {icon_list}.
- Si visual_type = "timeline" : timeline_steps = liste ORDONNÉE de 3 à 5
  {{"label": "...", "icon": "...", "number": "..."}}. "label"/"icon" comme ci-dessus. "number" DOIT
  être repris VERBATIM d'un des key_numbers de CETTE diapositive (jamais inventé) — laisse "" si
  aucun chiffre de cette diapositive ne correspond à cette étape.
- Si visual_type = "default" : ne fournis PAS diagram_hub/diagram_satellites/timeline_steps.

Ajoute ces champs dans le JSON de chaque diapositive (en plus de start_sentence/end_sentence/
visual_title/key_terms/key_numbers déjà demandés) : "visual_type", et selon le cas
"diagram_hub"/"diagram_satellites" ou "timeline_steps".
"""

_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜŸÇ«"\'0-9])')


def split_sentences(text: str) -> list[str]:
    """Découpe un texte en phrases, déterministe et réversible : ' '.join(split_sentences(t))
    reconstruit t à l'espacement près (les retours à la ligne/espaces multiples sont normalisés)."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    sentences = _SENTENCE_SPLIT_RE.split(normalized)
    return [s.strip() for s in sentences if s.strip()]


def build_prompt(
    chapter_title: str, sentences: list[str], error_feedback: str | None = None, rich: bool = False
) -> str:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    prompt = PROMPT_TEMPLATE.format(chapter_title=chapter_title, n=len(sentences), numbered_sentences=numbered)
    if rich:
        prompt += RICH_STYLE_PROMPT_ADDITION.format(icon_list=", ".join(DIAGRAM_ICONS))
    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def validate_slide_plan(slide_plan: list[dict], num_sentences: int) -> list[str]:
    """Retourne la liste des erreurs de validation (vide = valide). Ne vérifie QUE le plan de
    découpage (bornes de phrases + métadonnées) — le texte narré est reconstruit par Python,
    pas généré par le LLM, donc il n'y a rien à valider de ce côté."""
    errors: list[str] = []

    if not slide_plan:
        return ["Le plan de diapositives est vide."]

    expected_start = 1
    for i, slide in enumerate(slide_plan):
        start, end = slide.get("start_sentence"), slide.get("end_sentence")
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            errors.append(f"Diapositive {i + 1} : bornes de phrases invalides ({start}-{end}).")
            continue
        if start != expected_start:
            errors.append(
                f"Diapositive {i + 1} : devrait commencer à la phrase {expected_start}, commence à {start}."
            )
        expected_start = end + 1

        if not slide.get("visual_title", "").strip():
            errors.append(f"Diapositive {i + 1} : visual_title vide.")
        if not isinstance(slide.get("key_terms"), list):
            errors.append(f"Diapositive {i + 1} : key_terms doit être une liste.")
        if not isinstance(slide.get("key_numbers"), list):
            errors.append(f"Diapositive {i + 1} : key_numbers doit être une liste.")

    if expected_start != num_sentences + 1:
        errors.append(
            f"Les diapositives couvrent jusqu'à la phrase {expected_start - 1}, attendu {num_sentences}."
        )

    return errors


def _validate_rich_fields(slide: dict, index: int) -> list[str]:
    """Valide les champs visuels riches d'UNE diapositive (visual_type + contenu structuré selon
    le cas). N'est appelée qu'en mode `rich=True` — ne change rien à la validation existante."""
    errors: list[str] = []
    n = index + 1
    visual_type = slide.get("visual_type")
    if visual_type not in ("default", "diagram", "timeline"):
        errors.append(f"Diapositive {n} : visual_type invalide ({visual_type!r}).")
        return errors

    def _valid_node(node) -> bool:
        return (
            isinstance(node, dict)
            and isinstance(node.get("label"), str)
            and node["label"].strip()
            and node.get("icon") in DIAGRAM_ICONS
        )

    if visual_type == "diagram":
        hub = slide.get("diagram_hub")
        satellites = slide.get("diagram_satellites")
        if not _valid_node(hub):
            errors.append(f"Diapositive {n} : diagram_hub manquant ou invalide (icon hors enum ?).")
        if not isinstance(satellites, list) or not (2 <= len(satellites) <= 4) or not all(
            _valid_node(s) for s in satellites
        ):
            errors.append(f"Diapositive {n} : diagram_satellites doit être une liste de 2 à 4 éléments valides.")

    elif visual_type == "timeline":
        steps = slide.get("timeline_steps")
        key_numbers = slide.get("key_numbers") or []
        if not isinstance(steps, list) or not (3 <= len(steps) <= 5):
            errors.append(f"Diapositive {n} : timeline_steps doit contenir 3 à 5 étapes.")
        else:
            for step in steps:
                if not _valid_node(step):
                    errors.append(f"Diapositive {n} : une étape de timeline_steps est invalide (icon hors enum ?).")
                    break
                number = step.get("number", "")
                if number and number not in key_numbers:
                    errors.append(
                        f"Diapositive {n} : le chiffre '{number}' d'une étape de timeline_steps n'est "
                        "pas repris verbatim de key_numbers (chiffre potentiellement inventé)."
                    )

    return errors


def _assemble_rich_slides(sentences: list[str], slide_plan: list[dict]) -> list[dict]:
    slides = _assemble_slides(sentences, slide_plan)
    for slide, entry in zip(slides, slide_plan):
        slide["visual_type"] = entry["visual_type"]
        if entry["visual_type"] == "diagram":
            slide["diagram_hub"] = entry["diagram_hub"]
            slide["diagram_satellites"] = entry["diagram_satellites"]
        elif entry["visual_type"] == "timeline":
            slide["timeline_steps"] = entry["timeline_steps"]
    return slides


def build_rich_slides(chapter_title: str, lesson_script: str, demo: bool = False) -> list[dict]:
    """Comme `build_slides`, mais demande en plus un traitement visuel riche par diapositive
    (`visual_type` + contenu structuré diagram/timeline) — voir `RICH_STYLE_PROMPT_ADDITION`.
    Utilisé uniquement par le pilote de style visuel riche (`produce_rich_preview.py`), jamais par
    la production standard (`produce_video.py`/`build_slides`, comportement inchangé)."""
    sentences = split_sentences(lesson_script)
    if not sentences:
        raise LLMCallError("lesson_script vide, impossible de découper en diapositives.")

    if demo:
        plan = _demo_slide_plan(len(sentences))
        for entry in plan:
            entry["visual_type"] = "default"
        return _assemble_rich_slides(sentences, plan)

    error_feedback = None
    last_errors: list[str] = []

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = run_prompt(
            prompt=build_prompt(chapter_title, sentences, error_feedback, rich=True),
            allowed_tools=[],
            system_prompt=SYSTEM_PROMPT,
            max_turns=6,
        )
        try:
            plan = extract_json(response_text)["slides"]
            last_errors = validate_slide_plan(plan, len(sentences))
            if not last_errors:
                for i, entry in enumerate(plan):
                    last_errors.extend(_validate_rich_fields(entry, i))
        except (LLMCallError, KeyError, TypeError) as exc:
            last_errors = [f"Réponse non exploitable : {exc}"]
            plan = None

        if plan is not None and not last_errors:
            return _assemble_rich_slides(sentences, plan)
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    raise LLMCallError(f"Plan de diapositives riche invalide après {attempt + 1} tentative(s) : {last_errors}")


def _demo_slide_plan(num_sentences: int, group_size: int = 3) -> list[dict]:
    plan = []
    start = 1
    while start <= num_sentences:
        end = min(start + group_size - 1, num_sentences)
        plan.append(
            {
                "start_sentence": start,
                "end_sentence": end,
                "visual_title": f"[DEMO] Diapositive {len(plan) + 1}",
                "key_terms": ["[DEMO] terme"],
                "key_numbers": [],
            }
        )
        start = end + 1
    return plan


def _assemble_slides(sentences: list[str], slide_plan: list[dict]) -> list[dict]:
    slides = []
    for i, entry in enumerate(slide_plan, start=1):
        narration_text = " ".join(sentences[entry["start_sentence"] - 1 : entry["end_sentence"]])
        slides.append(
            {
                "slide_number": i,
                "narration_text": narration_text,
                "visual_title": entry["visual_title"],
                "key_terms": entry["key_terms"],
                "key_numbers": entry["key_numbers"],
            }
        )
    return slides


def build_slides(chapter_title: str, lesson_script: str, demo: bool = False) -> list[dict]:
    """Découpe un lesson_script en diapositives. Retourne une liste de dicts
    {slide_number, narration_text, visual_title, key_terms, key_numbers}."""
    sentences = split_sentences(lesson_script)
    if not sentences:
        raise LLMCallError("lesson_script vide, impossible de découper en diapositives.")

    if demo:
        plan = _demo_slide_plan(len(sentences))
        errors = validate_slide_plan(plan, len(sentences))
        if errors:
            raise LLMCallError(f"Plan démo invalide (bug interne) : {errors}")
        return _assemble_slides(sentences, plan)

    error_feedback = None
    last_errors: list[str] = []

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = run_prompt(
            prompt=build_prompt(chapter_title, sentences, error_feedback),
            allowed_tools=[],
            system_prompt=SYSTEM_PROMPT,
            max_turns=4,
        )
        try:
            plan = extract_json(response_text)["slides"]
            last_errors = validate_slide_plan(plan, len(sentences))
        except (LLMCallError, KeyError, TypeError) as exc:
            last_errors = [f"Réponse non exploitable : {exc}"]
            plan = None

        if plan is not None and not last_errors:
            return _assemble_slides(sentences, plan)
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    raise LLMCallError(f"Plan de diapositives invalide après {attempt + 1} tentative(s) : {last_errors}")
