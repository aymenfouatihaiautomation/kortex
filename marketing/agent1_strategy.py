"""Marketing KORTEX — Agent 1 : Strategy & Content Planning.

Turns Agent 0 (director)'s daily plan — domain + angle + visual style — into a concrete post
topic. Uses web_search to find a recent, relevant angle for the chosen domain.
All content is in English (international market).

Domain/angle used to come from a fixed weekly EDITORIAL_CALENDAR (removed) ; they're now supplied
by `agent0_director.py` via `director_input`, which decides based on real performance history
instead of a static day-of-week rule. `director_input=None` (e.g. running this file directly
without Agent 0) falls back to sensible defaults — see `decide_daily_topic`.
"""

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketing.config import KORTEX_SITE_URL, MarketingAPIError, call_anthropic, extract_json

REPO_ROOT = Path(__file__).resolve().parent.parent

KORTEX_COURSES = [
    {
        "title": "Agents IA en production : gérer les erreurs, évaluer et déployer sans risque",
        "domain": "AI & Automation",
        "price_usd": 15,
        "url": "https://cours.aymen-automation.site",
    }
]


def _load_published_courses_for_marketing() -> list[dict]:
    """Retourne le cours 1 (hardcodé) + les cours de `data/published_courses.json` si disponibles.

    Écart vs le brief initial, vérifié en lisant `pipeline/auto_publish.py::add_published_course`
    directement : la vraie structure de ce fichier est `{"courses": [{"slug", "title", "domain",
    "price_usd", ...}]}` — pas `{"produced": [{"course_title", ...}]}` (ce schéma est celui d'un
    AUTRE fichier, `pipeline/produced_courses.json`, qui sert à la déduplication de sujets, pas au
    catalogue public). Sans cette correction, cette fonction ne remonterait jamais un cours
    réellement publié, seulement le cours 1 codé en dur ci-dessus, indéfiniment. URL construite
    avec `/cours/<slug>` — la vraie route de `bloc4_publication/app.py::course_landing`, pas
    `/course/<slug>`. Pas de filtre "[DEMO]" ici : ce fichier ne contient que des cours réellement
    publiés (écrit uniquement après une exécution complète du pipeline), contrairement à
    `pipeline/produced_courses.json` qui peut contenir des stubs de test."""
    courses = list(KORTEX_COURSES)
    # Dédoublonnage par titre : published_courses.json contient désormais le cours 1 aussi
    # (ajouté le 2026-08-30, migration du price_id mock vers un vrai prix Paddle live) — sans ce
    # garde-fou, le cours 1 apparaîtrait deux fois (une fois via KORTEX_COURSES, une fois via ce
    # fichier). KORTEX_COURSES reste comme filet de sécurité si published_courses.json venait à
    # nouveau à manquer le cours 1 (fichier absent/corrompu, par ex.).
    known_titles = {c["title"] for c in courses}
    published_file = REPO_ROOT / "data" / "published_courses.json"
    if published_file.exists():
        try:
            import json as _json

            data = _json.loads(published_file.read_text(encoding="utf-8"))
            for c in data.get("courses", []):
                title = c.get("title", c.get("slug", ""))
                if title in known_titles:
                    continue
                courses.append(
                    {
                        "title": title,
                        "domain": c.get("domain", ""),
                        "price_usd": c.get("price_usd", 0),
                        "url": f"{KORTEX_SITE_URL}/cours/{c.get('slug', '')}",
                    }
                )
                known_titles.add(title)
        except Exception:
            pass
    return courses

# ---------------------------------------------------------------------------
# Content type (angle) -> short format label, shown to the LLM as "format" and echoed back in the
# JSON decision. Purely descriptive (not branched on downstream) — kept from the old
# EDITORIAL_CALENDAR so post "format" labels stay consistent now that the angle comes from Agent 0
# instead of a fixed weekday.
# ---------------------------------------------------------------------------

ANGLE_FORMAT_LABELS = {
    "educational": "tip",
    "viral": "hook",
    "practical": "tip",
    "surprising": "fact",
    "conversion": "cta",
    "course_teaser": "teaser",
    "social_proof": "proof",
}

CONTENT_TYPE_INSTRUCTIONS = {
    "educational": (
        "Write an educational tip that teaches something concrete and actionable. "
        "Style: '3 mistakes that make your AI agent fail' or 'How to do X in 3 steps'. "
        "The reader should learn something immediately useful."
    ),
    "viral": (
        "Write a hook designed to stop the scroll. Use a surprising fact, a controversial "
        "statement, or a scary-but-true insight about the domain. "
        "Style: 'Your password manager was hacked. Now what?' or 'Nobody talks about this DevOps mistake'."
    ),
    "practical": (
        "Write a practical, hands-on tip with a concrete example or code snippet idea. "
        "Something the reader can apply today. Style: 'This one trick saves 2 hours every week'."
    ),
    "surprising": (
        "Write a surprising, mind-blowing fact or insight about the domain. "
        "Something most people don't know. Style: 'How BGP runs the entire internet (and why it's terrifying)'."
    ),
    "conversion": (
        "Write content that drives traffic to KORTEX. Highlight the value of learning this skill, "
        "the career impact, and end with a strong CTA to the platform. "
        "Style: 'If you're not learning AI automation in 2026, you're already behind. Here's where to start.'"
    ),
    "course_teaser": (
        "Showcase a specific KORTEX course. Highlight what the student will learn, why it matters "
        "now, and drive to link in bio. Use when a course matches today's trending topic."
    ),
    "social_proof": (
        "Share a milestone, stat, or testimonial about KORTEX. \"X developers already enrolled\", "
        "\"Our AI course covers Y\", etc. Use to build trust and credibility."
    ),
}

# ---------------------------------------------------------------------------
# System prompt + template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the social media strategist for KORTEX, an online tech education platform "
    f"({KORTEX_SITE_URL}). You respond ONLY with a valid JSON object, no text before or after, "
    "no markdown code blocks."
)

PROMPT_TEMPLATE = """\
Today is {weekday}.
Domain: {domain}
Content type: {content_type}
Instructions: {instructions}
CTA link: {site_url}

Recent context from the web (use this to make the content timely and relevant):
\"\"\"
{web_context}
\"\"\"

Based on the domain, content type, and recent context above, generate ONE compelling post topic.
The topic must:
- Be directly related to {domain}
- Match the content type: {content_type}
- Feel current and relevant (reference the web context if useful)
- Be actionable or surprising enough to stop someone scrolling Instagram
- Position KORTEX as the place to learn more

If content type is "course_teaser": Generate content that showcases a specific KORTEX course.
The topic should be the course title, angle should highlight 3 key things the student learns.
Always end with "Full course at {site_url}"

If content type is "social_proof": Generate content about KORTEX's credibility.
Highlight the platform, the quality of courses, the community growing.
Use stats if available, otherwise focus on the promise and mission.

Respond with EXACTLY this JSON format:
{{
  "topic": "compelling post title/hook in English",
  "format": "{format}",
  "angle": "precise angle: what specifically to cover, for whom, what insight to deliver",
  "cta_link": "{site_url}",
  "domain": "{domain}",
  "content_type": "{content_type}"
}}
"""

WEB_SEARCH_PROMPT = """\
Search for the latest news, trends, or developments in {domain} from the past 7 days.
Find something surprising, useful, or controversial that would make great social media content
for a tech education platform targeting developers and tech professionals.
Return a brief summary (3-5 sentences) of the most interesting recent finding.
"""

# ---------------------------------------------------------------------------
# Web search via Anthropic (with web_search tool)
# ---------------------------------------------------------------------------

def _fetch_web_context(domain: str) -> str:
    """Uses Claude with web_search tool to get recent context for the domain."""
    try:
        response_text = call_anthropic(
            messages=[{
                "role": "user",
                "content": WEB_SEARCH_PROMPT.format(domain=domain),
            }],
            system=(
                "You are a tech news researcher. Search the web and return a brief, "
                "factual summary of recent developments. Be concise and specific."
            ),
            max_tokens=512,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
        )
        return response_text.strip() if response_text.strip() else "No recent context found."
    except Exception as exc:
        return f"Web search unavailable: {exc}"


# ---------------------------------------------------------------------------
# Demo stub
# ---------------------------------------------------------------------------

def _demo_decision() -> dict:
    return {
        "topic": "3 mistakes that make your AI agent cost 30% more in production",
        "format": "tip",
        "angle": "RAG context bloat, prompt growth, missing cost dashboard — for devs running agents in prod",
        "cta_link": KORTEX_SITE_URL,
        "domain": "AI & Automation",
        "content_type": "educational",
    }


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------

def decide_daily_topic(demo: bool = False, director_input: dict | None = None) -> dict:
    """Returns today's content decision. Domain/angle/visual style come from Agent 0
    (`director_input`) instead of a fixed weekly calendar. `director_input=None` (direct CLI use
    without Agent 0) falls back to safe defaults (AI & Automation / educational / cinematic)."""
    if demo:
        return _demo_decision()

    director_input = director_input or {}
    domain = director_input.get("domain", "AI & Automation")
    content_type = director_input.get("angle", "educational")
    visual_style = director_input.get("visual_style", "cinematic")
    fal_model = director_input.get("fal_model", "fal-ai/flux-pro/v1.1")
    prompt_style = director_input.get("prompt_style", "photorealistic, cinematic")

    content_format = ANGLE_FORMAT_LABELS.get(content_type, "tip")
    instructions = CONTENT_TYPE_INSTRUCTIONS.get(content_type, CONTENT_TYPE_INSTRUCTIONS["educational"])
    weekday_name = datetime.now().strftime("%A")

    # Fetch recent web context for this domain — sauf pour "course_teaser", qui utilise directement
    # le vrai catalogue de cours KORTEX comme contexte (voir _load_published_courses_for_marketing)
    # au lieu d'une recherche web : évite un appel web_search inutile ET surtout garantit que le
    # LLM référence un vrai titre de cours au lieu d'en halluciner un.
    if director_input.get("angle") == "course_teaser":
        courses = _load_published_courses_for_marketing()
        courses_info = "\n".join([
            f'- "{c["title"]}" ({c["domain"]}, ${c["price_usd"]}) → {c["url"]}'
            for c in courses
        ])
        web_context = f"KORTEX courses available:\n{courses_info}"
    else:
        print(f"[agent1] Fetching web context for {domain}…", file=sys.stderr)
        web_context = _fetch_web_context(domain)
        print(f"[agent1] Web context: {web_context[:100]}…", file=sys.stderr)

    response_text = call_anthropic(
        messages=[{
            "role": "user",
            "content": PROMPT_TEMPLATE.format(
                weekday=weekday_name,
                domain=domain,
                content_type=content_type,
                instructions=instructions,
                format=content_format,
                site_url=KORTEX_SITE_URL,
                web_context=web_context,
            ),
        }],
        system=SYSTEM_PROMPT,
        max_tokens=1024,
    )

    decision = extract_json(response_text)
    decision.setdefault("cta_link", KORTEX_SITE_URL)
    decision.setdefault("domain", domain)
    decision.setdefault("content_type", content_type)
    decision["format"] = content_format
    decision["visual_style"] = visual_style
    decision["fal_model"] = fal_model
    decision["prompt_style"] = prompt_style
    return decision


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 1: Strategy")
    parser.add_argument("--demo", action="store_true", help="Demo mode: no API calls")
    args = parser.parse_args()

    decision = decide_daily_topic(demo=args.demo)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
