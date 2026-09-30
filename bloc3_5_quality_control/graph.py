"""Bloc 3.5 — Boucle de décision LangGraph : révision -> correction -> nouvelle révision.

Un graphe par chapitre (les 7 chapitres du Bloc 2 sont déjà indépendants les uns des autres, un
graphe par chapitre suffit et simplifie l'état par rapport à un unique gros graphe multi-chapitres).

Nœuds :
- review  : appelle le réviseur externe (bloc3_5_quality_control.reviewer, prompt séparé du Bloc 2)
- revise  : appelle la réécriture ciblée du Bloc 2 (bloc2_content_writing.write_content), qui ne
            corrige que les champs signalés par le réviseur
- accept / escalate : nœuds terminaux qui fixent le statut final avant la fin du graphe

Routage : accepted -> accept -> END ; needs_revision ET tentatives restantes -> revise -> review
(boucle) ; needs_revision ET plus de tentatives -> escalate -> END (revue manuelle, pas de boucle
infinie).
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from bloc2_content_writing.write_content import RUNNING_EXAMPLE as DEFAULT_RUNNING_EXAMPLE
from bloc2_content_writing.write_content import revise_chapter_content
from bloc3_5_quality_control.reviewer import review_chapter


class ChapterQCState(TypedDict):
    curriculum: dict
    chapter_spec: dict
    prev_chapter_spec: dict | None
    total_chapters: int
    content: dict
    running_example: str
    attempt: int
    max_attempts: int
    demo: bool
    review: dict | None
    history: list[dict]
    status: str


def _review_node(state: ChapterQCState) -> dict:
    review = review_chapter(
        state["curriculum"],
        state["chapter_spec"],
        state["prev_chapter_spec"],
        state["content"],
        state["total_chapters"],
        attempt=state["attempt"],
        demo=state["demo"],
    )
    entry = {
        "stage": "review",
        "attempt": state["attempt"],
        "overall_verdict": review["overall_verdict"],
        "issues": review["issues"],
    }
    return {"review": review, "history": state["history"] + [entry]}


def _revise_node(state: ChapterQCState) -> dict:
    revised_content = revise_chapter_content(
        state["curriculum"],
        state["chapter_spec"],
        state["total_chapters"],
        state["content"],
        state["review"]["issues"],
        demo=state["demo"],
        running_example=state["running_example"],
    )
    new_attempt = state["attempt"] + 1
    entry = {
        "stage": "revise",
        "attempt": new_attempt,
        "issues_addressed": state["review"]["issues"],
    }
    return {"content": revised_content, "attempt": new_attempt, "history": state["history"] + [entry]}


def _route_after_review(state: ChapterQCState) -> str:
    if state["review"]["overall_verdict"] == "accepted":
        return "accept"
    if state["attempt"] >= state["max_attempts"]:
        return "escalate"
    return "revise"


def build_graph():
    graph = StateGraph(ChapterQCState)
    graph.add_node("review", _review_node)
    graph.add_node("revise", _revise_node)
    graph.add_node("accept", lambda state: {"status": "accepted"})
    graph.add_node("escalate", lambda state: {"status": "escalated"})

    graph.add_edge(START, "review")
    graph.add_conditional_edges(
        "review", _route_after_review, {"accept": "accept", "escalate": "escalate", "revise": "revise"}
    )
    graph.add_edge("revise", "review")
    graph.add_edge("accept", END)
    graph.add_edge("escalate", END)

    return graph.compile()


_COMPILED_GRAPH = None


def run_chapter_qc(
    curriculum: dict,
    chapter_spec: dict,
    prev_chapter_spec: dict | None,
    content: dict,
    total_chapters: int,
    max_attempts: int = 3,
    demo: bool = False,
    running_example: str | None = None,
) -> ChapterQCState:
    """Exécute la boucle de contrôle qualité LangGraph pour UN chapitre et retourne l'état final.

    `running_example` : fil rouge à réutiliser si une réécriture (`revise`) est nécessaire — doit
    être celui utilisé pour générer `content` (voir `bloc2_result["running_example"]`). Par défaut,
    celui du Sprint 1 (rétrocompatibilité pour les appels qui ne le précisent pas)."""
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = build_graph()

    initial_state: ChapterQCState = {
        "curriculum": curriculum,
        "chapter_spec": chapter_spec,
        "prev_chapter_spec": prev_chapter_spec,
        "total_chapters": total_chapters,
        "content": content,
        "running_example": running_example or DEFAULT_RUNNING_EXAMPLE,
        "attempt": 0,
        "max_attempts": max_attempts,
        "demo": demo,
        "review": None,
        "history": [],
        "status": "in_review",
    }
    return _COMPILED_GRAPH.invoke(initial_state)
