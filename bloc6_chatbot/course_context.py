"""Bloc 6 — Construction du contenu complet d'UN cours, injecté dans le prompt système du tuteur.

Contrairement au chatbot général (métadonnées de tous les cours, context-stuffing léger), le
tuteur reçoit le contenu pédagogique COMPLET du seul cours acheté (structure produite par
`bloc4_publication.content_loader.load_course`) — leçons de chaque chapitre, contexte des
exercices. Une seule exception délibérée : le champ `correct_answer` des questions ouvertes
(`comprehension_exercises` de type "short_answer") n'est jamais inclus — voir
`_chapter_exercises_text` pour la raison."""


def build_course_content_context(course: dict) -> str:
    """Un bloc de texte pour le cours entier : titre/description, puis chaque chapitre (objectifs,
    points clés, contenu pédagogique, contexte des exercices)."""
    parts = [f"# {course['title']}\n\n{course['description']}"]
    for chapter in course["chapters"]:
        teaching_text = _chapter_teaching_text(chapter)
        exercises_text = _chapter_exercises_text(chapter)
        parts.append(
            f"## Chapitre {chapter['number']} — {chapter['title']}\n"
            f"Objectifs d'apprentissage : {'; '.join(chapter['learning_objectives'])}\n"
            f"Points clés : {'; '.join(chapter['key_points'])}\n\n"
            f"{teaching_text}\n\n"
            f"{exercises_text}"
        )
    return "\n\n".join(parts)


def _chapter_teaching_text(chapter: dict) -> str:
    """Le contenu pédagogique du chapitre, dans le même ordre de priorité que son affichage réel
    sur la page de lecture (`chapter.html`) : `content_blocks` enrichis, sinon `lesson_script`,
    sinon un assemblage du script vidéo + complément écrit."""
    if chapter.get("content_blocks"):
        flattened = (_flatten_content_block(block) for block in chapter["content_blocks"])
        return "\n\n".join(text for text in flattened if text)

    if chapter.get("lesson_script"):
        return chapter["lesson_script"]

    parts = []
    video_script = chapter.get("video_script") or {}
    if video_script.get("summary"):
        parts.append(video_script["summary"])
    parts.extend(scene.get("narration", "") for scene in video_script.get("scenes", []))
    if chapter.get("written_complement"):
        parts.append(chapter["written_complement"])
    return "\n\n".join(p for p in parts if p)


def _flatten_content_block(block: dict) -> str:
    """Réduit un bloc enrichi (voir `_content_blocks.html`) à sa substance textuelle — y compris
    les schémas (architecture/timeline/flow/comparison), pour que le tuteur puisse les expliquer
    en mots, pas seulement le texte courant."""
    block_type = block.get("type")
    if block_type == "paragraph":
        return block.get("text", "")
    if block_type == "heading":
        return f"### {block.get('text', '')}"
    if block_type == "callout":
        prefix = f"[{block['title']}] " if block.get("title") else ""
        return prefix + block.get("text", "")
    if block_type == "code":
        return f"```\n{block.get('code', '')}\n```"
    if block_type == "list":
        return "\n".join(f"- {item}" for item in block.get("items", []))
    if block_type == "diagram":
        return _flatten_diagram_block(block)
    return ""


def _flatten_diagram_block(block: dict) -> str:
    diagram_type = block.get("diagram_type")
    title = block.get("title", "")

    if diagram_type == "architecture":
        hub = block.get("hub", {})
        lines = [f"Schéma \"{title}\" — centre : {hub.get('label', '')} ({hub.get('description', '')})"]
        for sat in block.get("satellites", []):
            lines.append(f"  - {sat.get('label', '')} : {sat.get('description', '')}")
        return "\n".join(lines)

    if diagram_type in ("timeline", "flow"):
        lines = [f"Schéma \"{title}\" :"]
        for step in block.get("steps", []):
            number = f"{step['number']}. " if step.get("number") else ""
            lines.append(f"  {number}{step.get('label', '')} — {step.get('description', '')}")
        return "\n".join(lines)

    if diagram_type == "comparison":
        left, right = block.get("left", {}), block.get("right", {})
        lines = [f"Comparaison \"{title}\" : {left.get('label', '')} vs {right.get('label', '')}"]
        for point in left.get("points", []):
            lines.append(f"  {left.get('label', '')} : {point}")
        for point in right.get("points", []):
            lines.append(f"  {right.get('label', '')} : {point}")
        return "\n".join(lines)

    return ""


def _chapter_exercises_text(chapter: dict) -> str:
    """Contexte des exercices du chapitre — SAUF le champ `correct_answer` des questions ouvertes
    (`type == "short_answer"`).

    C'est le seul corrigé du système jamais montré à l'apprenant sur la page : le corrigé d'un QCM
    est déjà présent dans le DOM (`data-correct` sur chaque option, voir chapter.html) et le
    résultat attendu d'un exercice pratique est déjà affiché en clair. Donner `correct_answer` au
    tuteur permettrait à l'apprenant de l'obtenir simplement en le demandant en conversation,
    contournant la correction LLM dédiée (plafonnée à MAX_CORRECTIONS_PER_EXERCISE) — voir la
    règle correspondante dans le prompt système du tuteur (course_bot.PERSONA_PROMPT)."""
    lines = []
    exercises = chapter.get("comprehension_exercises") or []
    if exercises:
        lines.append("Exercices de compréhension :")
        for i, ex in enumerate(exercises, start=1):
            if ex.get("type") == "mcq":
                options = " / ".join(ex.get("options", []))
                lines.append(f"{i}. (QCM) {ex.get('question', '')} — Options : {options}")
            else:
                lines.append(f"{i}. (question ouverte) {ex.get('question', '')}")

    practical = chapter.get("practical_exercise")
    if practical:
        lines.append(f"Exercice pratique — {practical.get('title', '')} : {practical.get('instructions', '')}")
        if practical.get("expected_outcome"):
            lines.append(f"Résultat attendu : {practical['expected_outcome']}")

    return "\n".join(lines)
