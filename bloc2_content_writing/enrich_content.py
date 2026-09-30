"""Bloc 2 — Enrichissement visuel du contenu déjà validé (mise en forme riche + schémas).

Périmètre de ce sprint (2026-08-07) : PAS d'images générées par IA — seulement (1) une mise en
forme riche du texte (titres intermédiaires, encadrés, code, listes, emphase) et (2) des schémas
structurés (architecture hub-and-spoke, timeline, flux, comparaison) rendus en HTML/CSS, pas en
image. Le choix du traitement par section est laissé au LLM : rien n'est forcé partout.

RÈGLE ABSOLUE : ceci est une passe de REFORMULATION VISUELLE, jamais de réécriture de fond. Le
lesson_script d'entrée est déjà validé (Bloc 2 initial + Bloc 3.5) — cette passe ne doit ni changer
les faits, ni les chiffres, ni les exemples, ni en inventer de nouveaux. Elle restructure la
présentation d'un texte déjà exact, elle ne le corrige pas et ne le complète pas.

Protection production : n'écrit JAMAIS dans `bloc2_content_final.json` (le fichier servi en ligne).
Écrit dans un fichier de travail séparé (voir `DEFAULT_ENRICHED_FILE`). Le contenu enrichi doit
repasser par le réviseur du Bloc 3.5 (`bloc3_5_quality_control.reviewer.review_chapter`, réutilisé
tel quel via `flatten_content_blocks_to_text` — voir ce module) avant d'être considéré valide, et
ne remplace le contenu en ligne qu'après validation humaine explicite.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.llm_client import CostTracker, LLMCallError, call_llm_api, extract_json
from config import DATA_DIR

DEFAULT_CURRICULUM_FILE = DATA_DIR / "bloc1_curriculum_20260726_122738.json"
DEFAULT_SOURCE_CONTENT_FILE = DATA_DIR / "bloc2_content_final.json"
DEFAULT_ENRICHED_FILE = DATA_DIR / "bloc2_content_cours1_enriched.json"

MODEL = "claude-sonnet-5"  # jugement éditorial (placement schémas/encadrés), cf. mapping validé

VALID_BLOCK_TYPES = {"paragraph", "heading", "callout", "code", "list", "diagram"}
# "reminder" ajouté après validation du style visuel (2026-08-08) : un encadré "à retenir" distinct
# du "key_point" (une idée importante développée dans le texte) — le reminder resitue un acquis en
# une phrase courte, en fin de section. Ajout rétrocompatible : le chapitre 1 déjà enrichi n'utilise
# que key_point/warning/tip, il n'est pas régénéré pour ce changement purement visuel/de schéma.
VALID_CALLOUT_STYLES = {"key_point", "warning", "reminder", "tip"}
VALID_LIST_STYLES = {"bullet", "numbered"}
VALID_DIAGRAM_TYPES = {"architecture", "timeline", "flow", "comparison"}

SYSTEM_PROMPT = (
    "Tu es un metteur en forme pédagogique. Ton SEUL rôle est de restructurer visuellement un "
    "texte de cours DÉJÀ VALIDÉ — jamais de le réécrire, corriger, compléter, ou raccourcir sur le "
    "fond. Tu ne dois inventer AUCUN fait, chiffre, exemple ou affirmation qui ne soit pas déjà "
    "présent dans le texte source. Chaque phrase du texte source doit se retrouver, avec le même "
    "sens, quelque part dans ta sortie (répartie entre paragraphes, encadrés, listes et schémas). "
    "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans bloc de code "
    "markdown."
)

PROMPT_TEMPLATE = """\
Chapitre : "{chapter_title}".

Points clés déjà validés que ce chapitre doit couvrir (pour information, ne pas dupliquer tels
quels, ils sont déjà développés dans le texte source) :
{key_points}

--- TEXTE SOURCE DÉJÀ VALIDÉ (à restructurer, ne JAMAIS en changer le sens ou le contenu) ---
{lesson_script}
--- FIN DU TEXTE SOURCE ---

Restructure ce texte en une liste de blocs visuels ("content_blocks"), dans l'ordre de lecture.
Pour CHAQUE portion du texte, choisis le type de bloc le plus adapté — ne force RIEN, la plupart
du texte peut rester en simples paragraphes bien écrits :

- "paragraph" : texte normal. Utilise **double astérisque** autour d'un terme technique important
  pour le mettre en valeur (avec parcimonie, pas plus de 2-3 par paragraphe).
- "heading" : un titre intermédiaire court, uniquement si le chapitre a plusieurs sections
  distinctes qui gagnent à être nommées (ne force pas un heading avant chaque paragraphe).
- "callout" : un encadré, UNIQUEMENT quand le texte source contient déjà l'idée correspondante.
  Quatre styles possibles, choisis le plus précis :
  - "key_point" : une idée importante développée dans le texte (le cœur d'un raisonnement).
  - "warning" : une mise en garde explicite (ex. "attention à...", un piège à éviter).
  - "reminder" : un acquis à retenir, formulé en une phrase courte, typiquement en fin de section
    (différent de "key_point" : plus court, plus proche d'un résumé que d'une explication).
  - "tip" : un conseil pratique, actionnable.
  Champs : style, title (court), text (repris du texte source, pas inventé).
- "list" : une liste à puces ("bullet") ou numérotée ("numbered"), quand le texte source énumère
  déjà plusieurs éléments de façon énumérable (ex. "trois grandes familles de pannes...").
- "code" : UNIQUEMENT si le texte source mentionne un exemple de code, un nom de fonction, un
  schéma de données ou un appel d'outil qui gagne à être présenté comme du code (langage à
  déduire du contexte, ex. "python"). Ne jamais inventer un exemple de code qui n'est pas déjà
  décrit dans le texte source.
- "diagram" : UNIQUEMENT quand une section du texte source décrit une STRUCTURE visualisable —
  une architecture (un composant central relié à plusieurs autres), une séquence/timeline
  d'événements, un flux d'étapes, ou une comparaison entre deux choses. Le diagramme
  COMPLÈTE le paragraphe qui explique la structure en texte, il ne le remplace pas — garde le
  paragraphe narratif ET ajoute le bloc diagram juste après.
  Types de diagram_type et leurs champs exacts :
  - "architecture" : {{"hub": {{"id","label","description"}}, "satellites": [{{"id","label","description"}}, ...]}}
  - "timeline" : {{"steps": [{{"number","label","stat","description"}}, ...]}} (stat = chiffre clé si présent dans le texte, sinon chaîne vide)
  - "flow" : {{"steps": [{{"label","description"}}, ...]}}
  - "comparison" : {{"left": {{"label","points":[...]}}, "right": {{"label","points":[...]}}}}

Réponds avec EXACTEMENT ce format JSON :
{{
  "content_blocks": [
    {{"type": "paragraph", "text": "..."}},
    {{"type": "heading", "text": "..."}},
    {{"type": "callout", "style": "key_point", "title": "...", "text": "..."}},
    {{"type": "list", "style": "bullet", "items": ["...", "..."]}},
    {{"type": "code", "language": "python", "code": "..."}},
    {{"type": "diagram", "diagram_type": "architecture", "title": "...",
      "hub": {{"id": "...", "label": "...", "description": "..."}},
      "satellites": [{{"id": "...", "label": "...", "description": "..."}}]}}
  ]
}}
"""

RETRY_SUFFIX = """

ATTENTION : ta réponse précédente était invalide pour la raison suivante :
{errors}
Corrige ces problèmes et renvoie un JSON complet et valide respectant strictement le format demandé.
"""


def build_enrichment_prompt(
    chapter_title: str, lesson_script: str, key_points: list[str], error_feedback: str | None = None
) -> str:
    prompt = PROMPT_TEMPLATE.format(
        chapter_title=chapter_title,
        lesson_script=lesson_script,
        key_points="\n".join(f"- {kp}" for kp in key_points),
    )
    if error_feedback:
        prompt += RETRY_SUFFIX.format(errors=error_feedback)
    return prompt


def validate_content_blocks(blocks) -> list[str]:
    """Retourne la liste des erreurs de validation (vide = valide)."""
    errors: list[str] = []
    if not blocks or not isinstance(blocks, list):
        return ["content_blocks vide ou n'est pas une liste."]

    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"Bloc {i} : n'est pas un objet.")
            continue
        btype = block.get("type")
        if btype not in VALID_BLOCK_TYPES:
            errors.append(f"Bloc {i} : type invalide {btype!r} (attendu un de {sorted(VALID_BLOCK_TYPES)}).")
            continue

        if btype == "paragraph":
            if not (block.get("text") or "").strip():
                errors.append(f"Bloc {i} (paragraph) : champ 'text' vide.")
        elif btype == "heading":
            if not (block.get("text") or "").strip():
                errors.append(f"Bloc {i} (heading) : champ 'text' vide.")
        elif btype == "callout":
            if block.get("style") not in VALID_CALLOUT_STYLES:
                errors.append(f"Bloc {i} (callout) : style invalide {block.get('style')!r}.")
            if not (block.get("text") or "").strip():
                errors.append(f"Bloc {i} (callout) : champ 'text' vide.")
        elif btype == "code":
            if not (block.get("code") or "").strip():
                errors.append(f"Bloc {i} (code) : champ 'code' vide.")
            if not (block.get("language") or "").strip():
                errors.append(f"Bloc {i} (code) : champ 'language' vide.")
        elif btype == "list":
            if block.get("style") not in VALID_LIST_STYLES:
                errors.append(f"Bloc {i} (list) : style invalide {block.get('style')!r}.")
            if not block.get("items"):
                errors.append(f"Bloc {i} (list) : champ 'items' vide.")
        elif btype == "diagram":
            dtype = block.get("diagram_type")
            if dtype not in VALID_DIAGRAM_TYPES:
                errors.append(f"Bloc {i} (diagram) : diagram_type invalide {dtype!r}.")
            elif dtype == "architecture":
                if not block.get("hub") or not isinstance(block.get("satellites"), list) or not block["satellites"]:
                    errors.append(f"Bloc {i} (diagram architecture) : 'hub' et 'satellites' (non vide) requis.")
            elif dtype in ("timeline", "flow"):
                steps = block.get("steps")
                if not isinstance(steps, list) or len(steps) < 2:
                    errors.append(f"Bloc {i} (diagram {dtype}) : 'steps' doit contenir au moins 2 éléments.")
            elif dtype == "comparison":
                left, right = block.get("left"), block.get("right")
                if not left or not right or not left.get("points") or not right.get("points"):
                    errors.append(f"Bloc {i} (diagram comparison) : 'left' et 'right' avec 'points' requis.")

    return errors


def flatten_content_blocks_to_text(blocks: list[dict]) -> str:
    """Reconstruit une vue textuelle des blocs enrichis, pour la revue Bloc 3.5 (qui évalue du
    texte) — ce n'est PAS le rendu affiché à l'apprenant, juste une projection fidèle du contenu
    permettant au réviseur d'évaluer couverture/cohérence/exactitude sans connaître le rendu
    visuel. Réutilise `reviewer.review_chapter` sans le modifier."""
    lines = []
    for block in blocks:
        btype = block["type"]
        if btype == "paragraph":
            lines.append(block["text"].replace("**", ""))
        elif btype == "heading":
            lines.append(f"## {block['text']}")
        elif btype == "callout":
            lines.append(f"[ENCADRÉ {block['style'].upper()} — {block.get('title', '')}] {block['text']}")
        elif btype == "code":
            lines.append(f"[CODE {block['language']}]\n{block['code']}")
        elif btype == "list":
            for item in block["items"]:
                lines.append(f"- {item}")
        elif btype == "diagram":
            dtype = block["diagram_type"]
            title = block.get("title", "")
            if dtype == "architecture":
                sat_labels = ", ".join(s["label"] for s in block["satellites"])
                lines.append(
                    f"[SCHÉMA ARCHITECTURE — {title}] Centre : {block['hub']['label']} "
                    f"({block['hub'].get('description', '')}). Relié à : {sat_labels}."
                )
                for s in block["satellites"]:
                    lines.append(f"  - {s['label']} : {s.get('description', '')}")
            elif dtype in ("timeline", "flow"):
                lines.append(f"[SCHÉMA {dtype.upper()} — {title}]")
                for step in block["steps"]:
                    label = step.get("label", "")
                    stat = f" ({step['stat']})" if step.get("stat") else ""
                    lines.append(f"  {step.get('number', '-')}. {label}{stat} : {step.get('description', '')}")
            elif dtype == "comparison":
                lines.append(f"[SCHÉMA COMPARAISON — {title}]")
                lines.append(f"  {block['left']['label']} : " + "; ".join(block["left"]["points"]))
                lines.append(f"  {block['right']['label']} : " + "; ".join(block["right"]["points"]))
        lines.append("")
    return "\n".join(lines).strip()


def _demo_content_blocks(chapter_title: str, key_points: list[str]) -> list[dict]:
    return [
        {"type": "paragraph", "text": f"[DEMO] Introduction reformattée pour **{chapter_title}**."},
        {"type": "heading", "text": "[DEMO] Section 1"},
        {"type": "callout", "style": "key_point", "title": "[DEMO] Point clé", "text": key_points[0] if key_points else "[DEMO]"},
        {"type": "list", "style": "bullet", "items": ["[DEMO] Item 1", "[DEMO] Item 2"]},
        {
            "type": "diagram",
            "diagram_type": "architecture",
            "title": "[DEMO] Schéma",
            "hub": {"id": "hub", "label": "[DEMO] Centre", "description": "..."},
            "satellites": [
                {"id": "a", "label": "[DEMO] A", "description": "..."},
                {"id": "b", "label": "[DEMO] B", "description": "..."},
            ],
        },
    ]


def enrich_chapter_content(
    chapter_title: str,
    lesson_script: str,
    key_points: list[str],
    demo: bool = False,
    tracker: CostTracker | None = None,
) -> list[dict]:
    """Appelle le LLM pour restructurer `lesson_script` en content_blocks. Retente une fois sur
    échec de validation (même schéma que `write_content.generate_chapter_content`).

    `tracker` : passe un `CostTracker` partagé pour accumuler le coût sur plusieurs chapitres (voir
    `enrich_course`) ; sinon un tracker local est créé et son résumé affiché avant de retourner."""
    if demo:
        blocks = _demo_content_blocks(chapter_title, key_points)
        errors = validate_content_blocks(blocks)
        if errors:
            raise LLMCallError(f"Données démo d'enrichissement invalides (bug interne) : {errors}")
        return blocks

    own_tracker = tracker is None
    if own_tracker:
        tracker = CostTracker(label=f"Bloc 2 - enrich_chapter_content ({chapter_title})")

    error_feedback = None
    last_errors: list[str] = []

    for attempt in range(2):  # 1 essai + 1 retry
        response_text = call_llm_api(
            prompt=build_enrichment_prompt(chapter_title, lesson_script, key_points, error_feedback),
            model=MODEL,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=8192,
            tracker=tracker,
        )
        try:
            data = extract_json(response_text)
            blocks = data.get("content_blocks")
            last_errors = validate_content_blocks(blocks)
        except LLMCallError as exc:
            # Sans ce try/except, un JSON malformé (bug réel déjà rencontré et corrigé ailleurs
            # cette session — plan_curriculum.py, write_content.py) ferait planter cette fonction
            # immédiatement au lieu de déclencher le retry déjà prévu ci-dessous.
            last_errors = [f"Réponse JSON invalide : {exc}"]
        if not last_errors:
            if own_tracker:
                tracker.print_summary()
            return blocks
        error_feedback = "\n".join(f"- {e}" for e in last_errors)

    if own_tracker:
        tracker.print_summary()
    raise LLMCallError(f"Enrichissement de '{chapter_title}' invalide après {attempt + 1} tentative(s) : {last_errors}")


def load_json(path: Path | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def enrich_course(
    curriculum_file: Path | str = DEFAULT_CURRICULUM_FILE,
    source_content_file: Path | str = DEFAULT_SOURCE_CONTENT_FILE,
    chapter_numbers: list[int] | None = None,
    demo: bool = False,
) -> dict:
    """Enrichit les chapitres demandés (tous par défaut) à partir du contenu DÉJÀ PUBLIÉ (lecture
    seule — jamais modifié). `comprehension_exercises`/`practical_exercise` sont copiés tels quels
    (non enrichis ce sprint)."""
    curriculum = load_json(curriculum_file)
    source = load_json(source_content_file)
    source_by_number = {c["chapter_number"]: c for c in source["chapters_content"]}

    chapters_to_process = chapter_numbers or [c["chapter_number"] for c in source["chapters_content"]]
    tracker = None if demo else CostTracker(label="Bloc 2 - enrich_course (cours complet)")

    enriched_chapters = []
    for chap_spec in curriculum["chapters"]:
        number = chap_spec["number"]
        if number not in chapters_to_process:
            continue
        source_chapter = source_by_number[number]
        blocks = enrich_chapter_content(
            chapter_title=chap_spec["title"],
            lesson_script=source_chapter["lesson_script"],
            key_points=chap_spec["key_points"],
            demo=demo,
            tracker=tracker,
        )
        enriched_chapters.append(
            {
                "chapter_number": number,
                "chapter_title": chap_spec["title"],
                "content_blocks": blocks,
                "comprehension_exercises": source_chapter["comprehension_exercises"],
                "practical_exercise": source_chapter["practical_exercise"],
            }
        )

    if tracker is not None:
        tracker.print_summary()

    return {
        "course_title": curriculum["title"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chapters_content": enriched_chapters,
    }


def save_enriched_content(result: dict, path: Path | str = DEFAULT_ENRICHED_FILE) -> Path:
    """Sauvegarde en FUSIONNANT avec le contenu déjà enrichi présent dans `path` (permet
    d'enrichir un chapitre à la fois sans écraser les précédents) — écrit UNIQUEMENT dans le
    fichier de travail, jamais dans `bloc2_content_final.json`."""
    path = Path(path)
    existing = {"chapters_content": []}
    if path.exists():
        existing = load_json(path)

    by_number = {c["chapter_number"]: c for c in existing.get("chapters_content", [])}
    for chap in result["chapters_content"]:
        by_number[chap["chapter_number"]] = chap

    merged = {
        "course_title": result["course_title"],
        "generated_at": result["generated_at"],
        "chapters_content": sorted(by_number.values(), key=lambda c: c["chapter_number"]),
    }
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_qc_on_enriched_chapter(
    curriculum: dict,
    chapter_spec: dict,
    prev_chapter_spec: dict | None,
    enriched_chapter: dict,
    total_chapters: int,
    demo: bool = False,
) -> dict:
    """Fait repasser un chapitre enrichi par le réviseur EXISTANT du Bloc 3.5, SANS le modifier —
    `review_chapter` évalue du texte (couverture/cohérence/exactitude/qualité des exercices), on
    lui fournit donc une vue textuelle fidèle des content_blocks via `flatten_content_blocks_to_text`
    plutôt que de lui apprendre à lire un format qu'il n'a pas besoin de connaître visuellement.
    Import local pour éviter un couplage au niveau module (bloc3_5 importe déjà bloc2 ailleurs dans
    le projet, ce sens-ci n'est utilisé que par cette fonction d'orchestration)."""
    from bloc3_5_quality_control.reviewer import review_chapter

    flattened = flatten_content_blocks_to_text(enriched_chapter["content_blocks"])
    content_for_review = {
        "lesson_script": flattened,
        "comprehension_exercises": enriched_chapter["comprehension_exercises"],
        "practical_exercise": enriched_chapter["practical_exercise"],
    }
    return review_chapter(
        curriculum, chapter_spec, prev_chapter_spec, content_for_review, total_chapters, demo=demo
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bloc 2 — Enrichissement visuel du contenu déjà validé")
    parser.add_argument("--demo", action="store_true", help="Mode démo : blocs placeholder, aucun appel réseau")
    parser.add_argument("--chapters", type=str, default=None, help="Numéros de chapitres à enrichir, ex. '1' ou '1,2,3' (défaut : tous)")
    parser.add_argument("--curriculum-file", type=str, default=str(DEFAULT_CURRICULUM_FILE))
    parser.add_argument("--source-content-file", type=str, default=str(DEFAULT_SOURCE_CONTENT_FILE))
    parser.add_argument("--output", type=str, default=str(DEFAULT_ENRICHED_FILE))
    args = parser.parse_args()

    chapter_numbers = [int(n) for n in args.chapters.split(",")] if args.chapters else None

    result = enrich_course(
        curriculum_file=args.curriculum_file,
        source_content_file=args.source_content_file,
        chapter_numbers=chapter_numbers,
        demo=args.demo,
    )

    for c in result["chapters_content"]:
        print(f"Chapitre {c['chapter_number']} — {c['chapter_title']} ({len(c['content_blocks'])} blocs)")

    output_path = save_enriched_content(result, args.output)
    print(f"\nSauvegardé (fusionné) : {output_path}")


if __name__ == "__main__":
    main()
