"""Pipeline — Module 2 : orchestrateur Bloc0 -> Bloc1 -> Bloc2 -> Bloc3.5 -> Bloc2.5 (enrich) -> Bloc7.

Le sujet (`--topic`/`--domain`) arrive déjà choisi (par `pipeline/domain_agent.py` ou un humain) —
"Bloc0" ici (voir `_stage_bloc0`) le CONFIRME/AFFINE via `pipeline/topic_discovery.py` (recherche
web réelle + API Anthropic directe), PAS via `bloc0_topic_discovery/discover_topics.py` : ce
dernier est câblé en dur sur `config.NICHE` ("AI Automation", sans paramètre de domaine) ET utilise
le Claude Agent SDK (`claude login`, session interactive) — incompatible avec un run 100% autonome
sur un serveur. Le vrai Bloc0 original n'est pas modifié et reste utilisable indépendamment.

Pour que `bloc1_curriculum_planning.plan_curriculum` (lui aussi câblé sur `config.NICHE` au niveau
module) produise un curriculum dans LE domaine demandé sans modifier son code, ce module patche
temporairement le nom `NICHE` importé dans l'espace de noms de `plan_curriculum` (via
`unittest.mock.patch.object`, le temps du seul appel) — même mécanisme que celui déjà utilisé par
les tests de ce dépôt pour patcher des constantes de module, pas une modification du fichier
source de Bloc 1. `bloc2_content_writing`/`bloc3_5_quality_control`/`bloc7_exam_generation` ne
lisent jamais `config.NICHE` directement : ils dérivent tous le "niche" du curriculum reçu en
entrée (confirmé par lecture de leur code), donc un seul point de patch suffit.

Chaque cours a un "slug" canonique = `slugify(topic)` (le sujet choisi, PAS le titre final généré
par le LLM en Bloc 1, qui peut légèrement différer) — dérivé UNE fois au démarrage et réutilisé
pour : le nom de fichier de checkpoint, le sous-dossier `data/<slug>/pipeline/`, et le dossier
`data/<slug>/` où le Bloc 7 écrit sa banque d'examen (`course["slug"]` est forcé à cette valeur
avant l'appel à `build_exam_bank`, plutôt que de laisser `content_loader.load_course` le
redériver du titre final).

`bloc1_curriculum_planning.plan_curriculum`, `bloc2_content_writing.write_content`,
`bloc3_5_quality_control.run_quality_control` et `bloc7_exam_generation.build_exam_bank` sont
appelés directement (pas via subprocess/CLI), et PAS via leurs propres `save_result()` (qui
écrivent tous des fichiers plats horodatés dans `data/`, une convention qui ne tient pas à
l'échelle de plusieurs cours par jour) — ce module sérialise lui-même chaque résultat intermédiaire
sous `data/<slug>/pipeline/*.json`. Seul le Bloc 7 garde son `save_result()` d'origine, qui écrit
déjà nativement sous `data/<slug>/exam_questions.json` — rien à changer là.
"""

import argparse
import contextlib
import io
import json
import queue
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bloc4_publication.content_loader import load_course, slugify
from common.llm_client import LLMCallError
from config import DATA_DIR
from pipeline.domain_agent import record_produced_course

PIPELINE_DIR = Path(__file__).resolve().parent
CHECKPOINTS_DIR = PIPELINE_DIR / "checkpoints"
REPORTS_DIR = PIPELINE_DIR / "reports"
PENDING_VALIDATION_FILE = PIPELINE_DIR / "pending_validation.json"

DEFAULT_VALIDATION_TIMEOUT_SECONDS = 1800  # 30 min, voir prompt_validation

_COST_LINE_RE = re.compile(r"\[cost\]\s+model=(\S+)\s+in=(\d+)\s+out=(\d+)\s+~\s+\$([\d.]+)")


# --- Checkpoint (reprise --resume) --------------------------------------------------------------


def _checkpoint_path(slug: str) -> Path:
    return CHECKPOINTS_DIR / f"{slug}.json"


def load_checkpoint(slug: str) -> dict | None:
    path = _checkpoint_path(slug)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checkpoint(checkpoint: dict) -> None:
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = _checkpoint_path(checkpoint["slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


def _new_checkpoint(slug: str, topic: str, domain: str, price_usd: float, dry_run: bool) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "slug": slug,
        "topic": topic,
        "domain": domain,
        "price_usd": price_usd,
        "dry_run": dry_run,
        "started_at": now,
        "updated_at": now,
        "stages": {},
        "status": "in_progress",
    }


# --- Coût : capture des lignes "[cost] ..." imprimées par common.llm_client --------------------


def _run_capturing_cost(fn, *args, **kwargs):
    """Exécute `fn(*args, **kwargs)` en capturant stdout pour agréger le coût réel de CET appel.
    Nécessaire car `plan_curriculum`/`write_content`/`run_quality_control` créent chacun leur
    propre `CostTracker` interne et ne le renvoient pas à l'appelant (changer leur signature
    violerait la consigne de ne pas toucher aux blocs existants) — mais `call_llm_api` imprime
    systématiquement une ligne `[cost] model=... in=... out=... ~ $...` à CHAQUE appel, qu'on peut
    parser sans rien modifier. Ré-imprime la sortie capturée après coup (les logs restent
    visibles, juste pas en flux live) et retourne `(résultat, cost_summary)`."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    captured = buf.getvalue()
    print(captured, end="")

    calls = total_input = total_output = 0
    total_cost = 0.0
    for m in _COST_LINE_RE.finditer(captured):
        calls += 1
        total_input += int(m.group(2))
        total_output += int(m.group(3))
        total_cost += float(m.group(4))

    return result, {
        "calls": calls,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cost_usd": round(total_cost, 4),
    }


def _aggregate_cost(checkpoint: dict) -> dict:
    calls = total_input = total_output = 0
    total_cost = 0.0
    for stage in checkpoint["stages"].values():
        cost = stage.get("cost")
        if cost:
            calls += cost.get("calls", 0)
            total_input += cost.get("input_tokens", 0)
            total_output += cost.get("output_tokens", 0)
            total_cost += cost.get("cost_usd", 0.0)
    return {"calls": calls, "input_tokens": total_input, "output_tokens": total_output, "cost_usd": round(total_cost, 4)}


# --- Étapes du pipeline --------------------------------------------------------------------------


def _course_pipeline_dir(slug: str) -> Path:
    d = DATA_DIR / slug / "pipeline"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stage_bloc0(checkpoint: dict, topic: str, domain: str, gap_reason: str, demo: bool) -> dict:
    """Équivalent Bloc0 en API directe (voir `pipeline/topic_discovery.py`) — confirme/affine le
    sujet déjà choisi via une recherche web réelle, SANS `claude login` (le vrai Bloc0 original,
    câblé sur le Claude Agent SDK, resterait bloquant sur un run autonome). Retourne le sujet
    affiné `{"title", "gap_reason", ...}`, utilisé par `_stage_bloc1` À LA PLACE de `topic`/
    `gap_reason` bruts — le slug du cours reste néanmoins figé sur le `topic` D'ORIGINE (voir
    `run_pipeline`), jamais recalculé depuis ce titre affiné, pour ne jamais dériver entre deux
    `--resume` d'un même cours."""
    from pipeline.topic_discovery import discover_topic

    refined, cost = _run_capturing_cost(discover_topic, topic, domain, angle=gap_reason, demo=demo)

    checkpoint["stages"]["bloc0"] = {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "input_topic": topic,
        "input_domain": domain,
        "refined_title": refined["title"],
        "refined_gap_reason": refined.get("gap_reason", ""),
        "demand_confirmed": refined.get("demand_confirmed"),
        "sources": refined.get("sources", []),
        "cost": cost,
    }
    _save_checkpoint(checkpoint)
    return refined


def _stage_bloc1(checkpoint: dict, topic: str, domain: str, gap_reason: str, demo: bool) -> dict:
    import bloc1_curriculum_planning.plan_curriculum as plan_curriculum_module

    topic_dict = {"title": topic, "gap_reason": gap_reason}
    with patch.object(plan_curriculum_module, "NICHE", domain):
        curriculum, cost = _run_capturing_cost(plan_curriculum_module.plan_curriculum, topic_dict, demo=demo)

    curriculum_path = _course_pipeline_dir(checkpoint["slug"]) / "curriculum.json"
    curriculum_path.write_text(json.dumps(curriculum, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint["stages"]["bloc1"] = {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "curriculum_path": str(curriculum_path),
        "cost": cost,
    }
    _save_checkpoint(checkpoint)
    return curriculum


def _stage_bloc2(checkpoint: dict, curriculum: dict, demo: bool) -> dict:
    from bloc2_content_writing.write_content import write_content

    content, cost = _run_capturing_cost(write_content, curriculum, demo=demo)

    content_path = _course_pipeline_dir(checkpoint["slug"]) / "content.json"
    content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint["stages"]["bloc2"] = {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "content_path": str(content_path),
        "cost": cost,
    }
    _save_checkpoint(checkpoint)
    return content


def _validate_chapter_content_with_real_format(content: dict, is_final_chapter: bool) -> list[str]:
    """Bug pré-existant découvert dans `bloc3_5_quality_control/export_final_content.py` : son
    appel à `validate_chapter_content(content, is_final_chapter)` omet le 3ème paramètre
    `format`, qui retombe donc TOUJOURS sur son défaut `"text"` — ce qui fait échouer l'export de
    tout chapitre "video"/"mix" (il exige alors un `lesson_script` que ce format n'a jamais,
    utilisant `video_script`/`written_complement` à la place), y compris HORS de ce pipeline, pour
    n'importe quel cours ayant un tel chapitre (une issue normale du Bloc 1, pas un cas
    exceptionnel). `content["format"]` existe déjà sur chaque chapitre (voir `write_content.py`,
    ligne où `content["format"] = content_format` est assigné) — ce correctif se contente de le
    transmettre. Neutralisé ici par patch temporaire de `validate_chapter_content` DANS l'espace
    de noms de `export_final_content` (voir `_stage_bloc3_5`), jamais en modifiant le fichier
    source du Bloc 3.5 — même mécanisme non-invasif que le patch de `NICHE` en Bloc 1."""
    from bloc2_content_writing.write_content import validate_chapter_content

    return validate_chapter_content(content, is_final_chapter, format=content.get("format", "text"))


def _stage_bloc3_5(checkpoint: dict, curriculum: dict, content: dict, demo: bool) -> tuple[dict | None, dict]:
    """Retourne `(final_content, qc_report)` ; `final_content` est `None` si au moins un chapitre
    reste `escalated` (voir `export_final_content`, qui refuse l'export dans ce cas) — c'est à
    `run_pipeline` de décider d'arrêter le pipeline sur ce statut, pas à cette fonction de lever."""
    import bloc3_5_quality_control.export_final_content as export_final_content_module
    from bloc3_5_quality_control.quality_control import run_quality_control

    qc_report, cost = _run_capturing_cost(run_quality_control, curriculum, content, demo=demo)

    qc_report_path = _course_pipeline_dir(checkpoint["slug"]) / "qc_report.json"
    qc_report_path.write_text(json.dumps(qc_report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        with patch.object(
            export_final_content_module, "validate_chapter_content", _validate_chapter_content_with_real_format
        ):
            final_content = export_final_content_module.export_final_content(qc_report)
    except ValueError as exc:
        checkpoint["stages"]["bloc3_5"] = {
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "qc_report_path": str(qc_report_path),
            "cost": cost,
            "summary": qc_report["summary"],
            "error": str(exc),
        }
        _save_checkpoint(checkpoint)
        return None, qc_report

    final_content_path = _course_pipeline_dir(checkpoint["slug"]) / "final_content.json"
    final_content_path.write_text(json.dumps(final_content, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint["stages"]["bloc3_5"] = {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "qc_report_path": str(qc_report_path),
        "final_content_path": str(final_content_path),
        "cost": cost,
        "summary": qc_report["summary"],
    }
    _save_checkpoint(checkpoint)
    return final_content, qc_report


def _stage_skip_qc(checkpoint: dict, content: dict) -> None:
    """`--skip-qc` : `content` (sortie brute du Bloc 2) a EXACTEMENT le même schéma que la sortie
    de `export_final_content` (mêmes clés `course_title/niche/level/running_example/chapters_content`
    — vérifié par lecture des deux fonctions), donc réutilisable tel quel comme "contenu final",
    sans repasser par le Bloc 3.5."""
    final_content_path = _course_pipeline_dir(checkpoint["slug"]) / "final_content.json"
    final_content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint["stages"]["bloc3_5"] = {
        "status": "skipped",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "final_content_path": str(final_content_path),
        "reason": "--skip-qc",
    }
    _save_checkpoint(checkpoint)


def _stage_enrich(checkpoint: dict, curriculum: dict, demo: bool) -> None:
    """Bloc 2.5 (bonus, non checkpointé comme un bloc "officiel" du docstring module) —
    enrichissement visuel (`content_blocks` : titres, encadrés, schémas) du contenu déjà validé
    par le Bloc 3.5. Réutilise `bloc2_content_writing/enrich_content.py` TEL QUEL (déjà construit,
    déjà utilisé manuellement pour le cours 1) plutôt que de dupliquer sa logique dans
    `write_content.py` — cf. docstring d'`enrich_content.py` : c'est une passe de reformulation
    VISUELLE d'un texte déjà validé, jamais un changement de fond, donc elle doit rester séparée
    de la rédaction initiale.

    Best-effort et non-bloquant : un chapitre qui échoue à l'enrichissement (erreur LLM après
    retry) ou à la re-revue qualité (`run_qc_on_enriched_chapter`, le réviseur EXISTANT du Bloc
    3.5 réutilisé sans modification) garde simplement son `lesson_script` brut — jamais d'échec
    du cours entier pour un enrichissement visuel bonus. Modifie `final_content.json` EN PLACE
    (ajoute `content_blocks` aux chapitres réussis) ; lu ensuite par `publish_course_files()`
    comme n'importe quel autre champ, et par Bloc 7 qui l'ignore (ne lit que lesson_script)."""
    from bloc2_content_writing.enrich_content import enrich_chapter_content, run_qc_on_enriched_chapter

    final_content_path = _course_pipeline_dir(checkpoint["slug"]) / "final_content.json"
    final_content = json.loads(final_content_path.read_text(encoding="utf-8"))
    chapters_by_number = {c["number"]: c for c in curriculum["chapters"]}
    total_chapters = len(curriculum["chapters"])

    def _enrich_all_chapters() -> int:
        enriched_count = 0
        for chap_content in final_content["chapters_content"]:
            number = chap_content["chapter_number"]
            chap_spec = chapters_by_number.get(number)
            # Pas de lesson_script (chapitre "video" pur, écrit uniquement via written_complement/
            # video_script) : rien à restructurer visuellement par cette passe, on le laisse tel
            # quel — content_loader.py retombera sur written_complement comme aujourd'hui.
            if chap_spec is None or not chap_content.get("lesson_script"):
                continue
            try:
                blocks = enrich_chapter_content(
                    chapter_title=chap_content["chapter_title"],
                    lesson_script=chap_content["lesson_script"],
                    key_points=chap_spec.get("key_points", []),
                    demo=demo,
                )
            except LLMCallError:
                continue

            enriched_chapter = {
                "chapter_number": number,
                "chapter_title": chap_content["chapter_title"],
                "content_blocks": blocks,
                "comprehension_exercises": chap_content["comprehension_exercises"],
                "practical_exercise": chap_content["practical_exercise"],
            }
            # Re-revue sautée en démo : _demo_review() échoue TOUJOURS au premier essai (exprès,
            # pour tester la boucle révision->correction ailleurs) — l'appliquer ici rejetterait
            # systématiquement des blocs stub déjà validés par construction, sans rapport avec un
            # vrai souci de qualité. En mode réel, la revue s'applique normalement.
            if not demo:
                prev_spec = chapters_by_number.get(number - 1)
                try:
                    review = run_qc_on_enriched_chapter(
                        curriculum, chap_spec, prev_spec, enriched_chapter, total_chapters, demo=demo
                    )
                except LLMCallError:
                    continue
                if any(c.get("verdict") != "pass" for c in review.get("criteria", {}).values()):
                    # Dérive de sens détectée malgré la consigne stricte du prompt d'enrichissement
                    # (règle absolue : jamais changer le fond) — on garde le lesson_script brut
                    # plutôt que de publier une version dont le réviseur doute.
                    continue

            chap_content["content_blocks"] = blocks
            enriched_count += 1
        return enriched_count

    enriched_count, cost = _run_capturing_cost(_enrich_all_chapters)
    final_content_path.write_text(json.dumps(final_content, ensure_ascii=False, indent=2), encoding="utf-8")

    checkpoint["stages"]["enrich"] = {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "enriched_chapters": enriched_count,
        "total_chapters": total_chapters,
        "cost": cost,
    }
    _save_checkpoint(checkpoint)


def _stage_bloc7(checkpoint: dict, demo: bool) -> dict:
    from bloc7_exam_generation.build_exam_bank import build_exam_bank
    from bloc7_exam_generation.build_exam_bank import save_result as save_exam_result

    course_dir = _course_pipeline_dir(checkpoint["slug"])
    course = load_course(curriculum_file=course_dir / "curriculum.json", content_file=course_dir / "final_content.json")
    # Slug canonique = slugify(topic initial), pas slugify(curriculum["title"]) qui peut différer
    # légèrement (titre final décidé par le LLM) — voir docstring du module.
    course["slug"] = checkpoint["slug"]

    result, cost = _run_capturing_cost(build_exam_bank, course, demo=demo)
    questions_path, report_json_path, _report_md_path = save_exam_result(result)

    checkpoint["stages"]["bloc7"] = {
        "status": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "questions_path": str(questions_path),
        "report_path": str(report_json_path),
        "cost": cost,
        "totals": result["report"]["totals"],
    }
    _save_checkpoint(checkpoint)
    return result


# --- Rapport final --------------------------------------------------------------------------------


def _build_report(checkpoint: dict, curriculum: dict | None, qc_report: dict | None) -> dict:
    chapters = curriculum["chapters"] if curriculum else []
    plan_lines = [f"{c['number']}. {c['title']}" for c in chapters[:5]]

    return {
        "slug": checkpoint["slug"],
        "topic": checkpoint["topic"],
        "domain": checkpoint["domain"],
        "titre": curriculum["title"] if curriculum else None,
        "plan": plan_lines,
        "chapitres": [{"number": c["number"], "title": c["title"]} for c in chapters],
        "score_qc": qc_report["summary"] if qc_report else None,
        "cout_tokens_estime": _aggregate_cost(checkpoint),
        "prix_suggere_usd": checkpoint["price_usd"],
        "statut_banque_examen": checkpoint["stages"].get("bloc7", {}).get("status", "not_run"),
        "statut_pipeline": checkpoint["status"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _report_to_text(report: dict) -> str:
    lines = [
        f"Cours : {report['titre'] or report['topic']}",
        f"Domaine : {report['domain']} | Slug : {report['slug']}",
        f"Prix suggere : ${report['prix_suggere_usd']:.2f}" if report["prix_suggere_usd"] is not None else "Prix : N/A",
        "",
        "Plan (5 premieres lignes) :",
    ]
    lines += [f"  {line}" for line in report["plan"]] or ["  (aucun chapitre - echec avant le Bloc 1)"]
    lines.append("")
    lines.append(f"Chapitres ({len(report['chapitres'])}) :")
    for c in report["chapitres"]:
        lines.append(f"  {c['number']}. {c['title']}")
    lines.append("")
    if report["score_qc"]:
        lines.append(f"QC : {report['score_qc']['accepted']} accepte(s), {report['score_qc']['escalated']} escalade(s)")
    else:
        lines.append("QC : non execute (--skip-qc, ou echec avant cette etape)")
    cost = report["cout_tokens_estime"]
    lines.append(
        f"Cout estime : {cost['calls']} appel(s), {cost['input_tokens']} tokens in / "
        f"{cost['output_tokens']} tokens out, ~ ${cost['cost_usd']:.4f}"
    )
    lines.append(f"Banque d'examen : {report['statut_banque_examen']}")
    lines.append(f"Statut pipeline : {report['statut_pipeline']}")
    return "\n".join(lines)


def save_report(report: dict) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"{report['slug']}_report.json"
    txt_path = REPORTS_DIR / f"{report['slug']}_report.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(_report_to_text(report), encoding="utf-8")
    return json_path, txt_path


# --- Validation (interactive) et marqueurs data/<slug>/ -------------------------------------------


def prompt_validation(timeout_seconds: int = DEFAULT_VALIDATION_TIMEOUT_SECONDS) -> str:
    """Demande oui/non/attente à l'opérateur ; retourne 'attente' automatiquement si aucune
    réponse n'arrive dans `timeout_seconds` (jamais bloquant indéfiniment). `input()` n'a pas de
    timeout natif : on le lit dans un thread daemon et on attend sur une queue avec timeout."""
    result_queue: "queue.Queue[str]" = queue.Queue()

    def _read_input() -> None:
        try:
            answer = input("Tapez 'oui' pour valider, 'non' pour abandonner, 'attente' pour decider plus tard : ")
        except EOFError:
            answer = "attente"
        result_queue.put(answer.strip().lower())

    threading.Thread(target=_read_input, daemon=True).start()

    try:
        answer = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        print(f"\nAucune reponse recue en {timeout_seconds}s - statut 'attente' applique automatiquement.")
        return "attente"

    if answer not in ("oui", "non", "attente"):
        print(f"Reponse non reconnue ({answer!r}) - statut 'attente' applique par securite.")
        return "attente"
    return answer


def apply_validation_decision(slug: str, decision: str, price_usd: float | None = None, reason: str = "") -> Path:
    """Écrit le marqueur `data/<slug>/READY_TO_PUBLISH` ou `REJECTED`. 'attente' n'a pas de
    marqueur (le cours reste en brouillon, voir `pending_validation.json`) — lève `ValueError` si
    appelée avec 'attente', pour ne jamais créer un marqueur incohérent par erreur d'appel."""
    if decision not in ("oui", "non"):
        raise ValueError(f"decision invalide pour un marqueur : {decision!r} (attendu 'oui' ou 'non')")

    course_dir = DATA_DIR / slug
    course_dir.mkdir(parents=True, exist_ok=True)

    if decision == "oui":
        path = course_dir / "READY_TO_PUBLISH"
        payload = {"validated_at": datetime.now(timezone.utc).isoformat(), "price_usd": price_usd}
    else:
        path = course_dir / "REJECTED"
        payload = {"rejected_at": datetime.now(timezone.utc).isoformat(), "reason": reason}

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_pending_validation(path: Path | str | None = None) -> list[dict]:
    path = Path(path) if path else PENDING_VALIDATION_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("pending", [])


def _write_pending_validation(pending: list[dict], path: Path | str | None = None) -> None:
    path = Path(path) if path else PENDING_VALIDATION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pending": pending}, ensure_ascii=False, indent=2), encoding="utf-8")


def add_pending_validation(entry: dict, path: Path | str | None = None) -> None:
    """Ajoute (ou remplace, si ce slug y figure déjà) une entrée dans la file d'attente de
    validation humaine — voir `pipeline/validate.py`."""
    pending = [p for p in load_pending_validation(path) if p.get("slug") != entry.get("slug")]
    pending.append(entry)
    _write_pending_validation(pending, path)


def remove_pending_validation(slug: str, path: Path | str | None = None) -> None:
    pending = [p for p in load_pending_validation(path) if p.get("slug") != slug]
    _write_pending_validation(pending, path)


# --- Orchestrateur principal -----------------------------------------------------------------------


def run_pipeline(
    topic: str,
    domain: str,
    price_usd: float,
    gap_reason: str = "",
    skip_qc: bool = False,
    dry_run: bool = False,
    resume: bool = False,
    interactive: bool = True,
    validation_timeout_seconds: int = DEFAULT_VALIDATION_TIMEOUT_SECONDS,
) -> dict:
    """Enchaîne Bloc0 (enregistrement du sujet) -> Bloc1 -> Bloc2 -> Bloc3.5 (ou skip) -> Bloc7,
    avec checkpoint après chaque étape (voir `load_checkpoint`/`_save_checkpoint`) et validation
    interactive (ou `pending_validation.json` si `interactive=False`, utilisé par
    `pipeline/scheduler.py` qui n'a pas de terminal pour répondre à un `input()`).

    `dry_run=True` force `demo=True` sur TOUS les blocs (aucun appel réseau/coût réel) — valide le
    câblage complet sans dépenser de tokens, jamais un mode "à moitié réel".

    Une exception levée par le Bloc 1/2 (ex. `LLMCallError`) N'EST PAS interceptée ici : elle
    remonte volontairement, en laissant le checkpoint dans son dernier état sauvegardé — c'est
    exactement ce qui permet à `--resume` de reprendre à l'étape suivante plutôt que de tout
    relancer depuis zéro."""
    slug = slugify(topic)
    demo = dry_run

    checkpoint = load_checkpoint(slug) if resume else None
    if checkpoint is None:
        checkpoint = _new_checkpoint(slug, topic, domain, price_usd, dry_run)
        _save_checkpoint(checkpoint)
    stages = checkpoint["stages"]

    if stages.get("bloc0", {}).get("status") == "done":
        refined_title = stages["bloc0"]["refined_title"]
        refined_gap_reason = stages["bloc0"]["refined_gap_reason"]
    else:
        refined = _stage_bloc0(checkpoint, topic, domain, gap_reason, demo)
        refined_title = refined["title"]
        refined_gap_reason = refined.get("gap_reason", "")

    if stages.get("bloc1", {}).get("status") == "done":
        curriculum = json.loads(Path(stages["bloc1"]["curriculum_path"]).read_text(encoding="utf-8"))
    else:
        curriculum = _stage_bloc1(checkpoint, refined_title, domain, refined_gap_reason, demo)

    if stages.get("bloc2", {}).get("status") == "done":
        content = json.loads(Path(stages["bloc2"]["content_path"]).read_text(encoding="utf-8"))
    else:
        content = _stage_bloc2(checkpoint, curriculum, demo)

    qc_report = None
    if skip_qc:
        if stages.get("bloc3_5", {}).get("status") != "skipped":
            _stage_skip_qc(checkpoint, content)
    elif stages.get("bloc3_5", {}).get("status") == "done":
        qc_report = json.loads(Path(stages["bloc3_5"]["qc_report_path"]).read_text(encoding="utf-8"))
    elif stages.get("bloc3_5", {}).get("status") != "failed":
        _final_content, qc_report = _stage_bloc3_5(checkpoint, curriculum, content, demo)

    if stages.get("bloc3_5", {}).get("status") == "failed":
        checkpoint["status"] = "failed"
        _save_checkpoint(checkpoint)
        report = _build_report(checkpoint, curriculum, qc_report)
        save_report(report)
        return {"slug": slug, "status": "failed", "reason": "qc_escalated", "report": report}

    if stages.get("enrich", {}).get("status") != "done":
        _stage_enrich(checkpoint, curriculum, demo)

    if stages.get("bloc7", {}).get("status") != "done":
        _stage_bloc7(checkpoint, demo)

    checkpoint["status"] = "completed"
    _save_checkpoint(checkpoint)

    report = _build_report(checkpoint, curriculum, qc_report)
    _report_json_path, report_txt_path = save_report(report)
    print("\n" + _report_to_text(report))

    decision = prompt_validation(timeout_seconds=validation_timeout_seconds) if interactive else "attente"

    if decision in ("oui", "non"):
        apply_validation_decision(slug, decision, price_usd=price_usd)
        remove_pending_validation(slug)
    else:
        add_pending_validation(
            {
                "slug": slug,
                "topic": topic,
                "domain": domain,
                "report_path": str(report_txt_path),
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    record_produced_course(domain, topic, slug=slug)

    return {"slug": slug, "status": "completed", "decision": decision, "report": report}


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline — Orchestrateur Bloc0 -> Bloc1 -> Bloc2 -> Bloc3.5 -> Bloc7")
    parser.add_argument("--topic", type=str, required=True)
    parser.add_argument("--domain", type=str, required=True)
    parser.add_argument("--price", type=float, required=True)
    parser.add_argument("--gap-reason", type=str, default="")
    parser.add_argument("--skip-qc", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Force le mode demo sur tous les blocs (aucun cout reel)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--non-interactive", action="store_true",
        help="Pas de prompt de validation (utilise par scheduler.py) - le cours part en 'attente'",
    )
    parser.add_argument("--validation-timeout", type=int, default=DEFAULT_VALIDATION_TIMEOUT_SECONDS)
    args = parser.parse_args()

    try:
        result = run_pipeline(
            topic=args.topic,
            domain=args.domain,
            price_usd=args.price,
            gap_reason=args.gap_reason,
            skip_qc=args.skip_qc,
            dry_run=args.dry_run,
            resume=args.resume,
            interactive=not args.non_interactive,
            validation_timeout_seconds=args.validation_timeout,
        )
    except LLMCallError as exc:
        print(f"Erreur LLM - pipeline interrompu, checkpoint conserve pour --resume : {exc}")
        raise SystemExit(1) from exc

    suffix = f" ({result['decision']})" if result.get("decision") else f" ({result.get('reason')})" if result.get("reason") else ""
    print(f"\nStatut final : {result['status']}{suffix}")


if __name__ == "__main__":
    main()
