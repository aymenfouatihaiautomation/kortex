"""Aplatit le contenu VALIDÉ d'un chapitre (bloc4_publication.content_loader.load_course) en texte
brut — la SEULE source autorisée pour générer et vérifier les questions d'examen (bloc7).

Ne lit jamais `comprehension_exercises` ni `practical_exercise` : la banque d'examen doit être
dérivée du COURS lui-même, pas des exercices déjà existants (sinon on ne fait que paraphraser un
quiz existant plutôt que vérifier une compréhension du contenu).
"""


def _flatten_content_blocks(blocks: list[dict]) -> list[str]:
    """Même inventaire de types que bloc4_publication/templates/_content_blocks.html — reproduit
    ici en texte brut plutôt qu'en HTML, pour qu'aucun passage du contenu enrichi n'échappe à la
    génération/vérification (un schéma ignoré serait une source silencieusement non couverte)."""
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "paragraph":
            lines.append(block["text"])
        elif block_type == "heading":
            lines.append(f"## {block['text']}")
        elif block_type == "callout":
            title = block.get("title")
            prefix = f"[{title}] " if title else "[Encadré] "
            lines.append(prefix + block["text"])
        elif block_type == "code":
            lines.append(f"[Bloc de code]\n{block['code']}")
        elif block_type == "list":
            lines.extend(f"- {item}" for item in block.get("items", []))
        elif block_type == "diagram":
            lines.extend(_flatten_diagram(block))
    return lines


def _flatten_diagram(block: dict) -> list[str]:
    diagram_type = block.get("diagram_type")
    title = block.get("title")
    lines = [f"[Schéma{': ' + title if title else ''}]"]
    if diagram_type == "architecture":
        hub = block["hub"]
        lines.append(f"Centre : {hub['label']}" + (f" — {hub['description']}" if hub.get("description") else ""))
        for sat in block.get("satellites", []):
            lines.append(f"- {sat['label']}" + (f" — {sat['description']}" if sat.get("description") else ""))
    elif diagram_type in ("timeline", "flow"):
        for step in block.get("steps", []):
            parts = [step["label"]]
            if step.get("stat"):
                parts.append(step["stat"])
            if step.get("description"):
                parts.append(step["description"])
            lines.append("- " + " — ".join(parts))
    elif diagram_type == "comparison":
        left, right = block["left"], block["right"]
        lines.append(f"{left['label']} : " + "; ".join(left.get("points", [])))
        lines.append(f"{right['label']} : " + "; ".join(right.get("points", [])))
    return lines


def chapter_source_text(chapter: dict) -> str:
    """Texte source complet d'un chapitre, dans le même ordre de priorité que chapter.html
    (content_blocks > lesson_script > written_complement — jamais les trois combinés, un seul
    est le contenu "affiché" réel de ce chapitre)."""
    parts: list[str] = [f"Titre du chapitre : {chapter['title']}"]

    if chapter.get("learning_objectives"):
        parts.append("Objectifs pédagogiques :\n" + "\n".join(f"- {o}" for o in chapter["learning_objectives"]))
    if chapter.get("key_points"):
        parts.append("Points clés :\n" + "\n".join(f"- {k}" for k in chapter["key_points"]))

    if chapter.get("content_blocks"):
        parts.append("Contenu du chapitre :\n" + "\n".join(_flatten_content_blocks(chapter["content_blocks"])))
    elif chapter.get("lesson_script"):
        parts.append("Contenu du chapitre :\n" + chapter["lesson_script"])
    elif chapter.get("written_complement"):
        parts.append("Contenu du chapitre :\n" + chapter["written_complement"])

    return "\n\n".join(parts)
