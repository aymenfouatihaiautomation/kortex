"""Marketing KORTEX — Agent 0 : Director.

Décide de façon 100% autonome chaque matin :
- Quel domaine couvrir aujourd'hui
- Quel style visuel utiliser
- Quel format (image simple ou carrousel)
- Quel angle éditorial (éducatif, viral, conversion)
- Combien de posts publier (1 ou 2)

Basé sur :
1. L'historique des performances (performance_history.json)
2. Ce qui a été publié récemment (publications.json)
3. Les tendances tech du moment (web search)
4. La variété — jamais le même style/domaine deux jours de suite
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent

from marketing.config import (
    KORTEX_SITE_URL,
    PERFORMANCE_HISTORY_FILE,
    PUBLICATIONS_LOG_FILE,
    MarketingAPIError,
    call_anthropic,
    extract_json,
)

# ---------------------------------------------------------------------------
# Domaines disponibles
# ---------------------------------------------------------------------------
DOMAINS = [
    "AI & Automation",
    "DevOps & Cloud",
    "Cybersecurity",
    "Web Development",
    "Networking & Telecom",
    "Data Science",
]

# ---------------------------------------------------------------------------
# Styles visuels disponibles + modèle fal.ai associé
# ---------------------------------------------------------------------------
VISUAL_STYLES = {
    "cinematic": {
        "description": "Photorealistic cinematic scene, dramatic lighting, real humans/objects",
        "fal_model": "fal-ai/flux-pro/v1.1",
        "prompt_style": "photorealistic, cinematic lighting, dramatic, 4k, shallow depth of field",
    },
    "isometric": {
        "description": "Colorful isometric illustration, cartoon characters, tech objects",
        "fal_model": "fal-ai/recraft-v3",
        "prompt_style": "isometric illustration, colorful, flat design, tech characters, modern, vector style",
    },
    "infographic": {
        "description": "Technical diagram, network schema, flowchart with icons and arrows",
        "fal_model": "fal-ai/ideogram/v3",
        "prompt_style": "clean infographic, technical diagram, icons, arrows, flowchart, professional, white background",
    },
    "minimal": {
        "description": "Clean minimal photo, white/light background, Apple-style aesthetic",
        "fal_model": "fal-ai/flux-pro/v1.1",
        "prompt_style": "minimal clean photo, bright natural light, white background, professional, Apple aesthetic",
    },
    "human_story": {
        "description": "Real person at work, natural portrait, warm authentic atmosphere",
        "fal_model": "fal-ai/flux-pro/v1.1",
        "prompt_style": "natural portrait, person working, warm ambient light, authentic, candid, professional",
    },
}

CONTENT_ANGLES = ["educational", "viral", "conversion", "practical", "surprising", "course_teaser", "social_proof"]
FORMATS = ["single_image", "carousel"]

# ---------------------------------------------------------------------------
# Lecture de l'historique
# ---------------------------------------------------------------------------

def _load_published_courses() -> list[dict]:
    """Charge le catalogue de cours publiés (`data/published_courses.json`, écrit par
    `pipeline/auto_publish.py`) — titre/domaine/prix/slug de chaque cours disponible pour
    `course_teaser`. Contrairement à `bloc4_publication/content_loader.py::load_published_courses`
    (qui retombe sur le cours 1 en fallback), retourne une liste VIDE si le fichier est
    absent/vide/invalide — c'est à `decide()` de gérer explicitement ce cas ("No courses published
    yet") plutôt que de deviner un cours par défaut. Système volontairement autonome : lecture
    directe du fichier, pas d'import de `bloc4_publication`."""
    path = REPO_ROOT / "data" / "published_courses.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    courses = raw.get("courses") if isinstance(raw, dict) else None
    if not courses:
        return []
    return [
        {
            "title": c.get("title", ""),
            "domain": c.get("domain", ""),
            "price_usd": c.get("price_usd"),
            "slug": c.get("slug", ""),
        }
        for c in courses
    ]

def _load_recent_publications(days: int = 7) -> list[dict]:
    """Charge les publications des N derniers jours."""
    if not PUBLICATIONS_LOG_FILE.exists():
        return []
    pubs = json.loads(
        PUBLICATIONS_LOG_FILE.read_text(encoding="utf-8")
    ).get("publications", [])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [p for p in pubs if p.get("timestamp", "") >= cutoff]


def _load_performance_history() -> list[dict]:
    """Charge l'historique des performances."""
    if not PERFORMANCE_HISTORY_FILE.exists():
        return []
    return json.loads(
        PERFORMANCE_HISTORY_FILE.read_text(encoding="utf-8")
    ).get("history", [])


def _build_context_summary() -> str:
    """Construit un résumé de l'historique pour le Director."""
    recent_pubs = _load_recent_publications(days=7)
    history = _load_performance_history()

    # Domaines récents
    recent_domains = []
    recent_styles = []
    for pub in recent_pubs:
        if pub.get("statut") == "success":
            recent_domains.append(pub.get("domain", ""))
            recent_styles.append(pub.get("visual_style", ""))

    # Performances par style
    style_performance = {}
    for report in history[-14:]:
        style = report.get("visual_style", "unknown")
        engagement = max(
            ch.get("engagement_rate", 0)
            for ch in report.get("channels", {}).values()
            if isinstance(ch, dict)
        ) if report.get("channels") else 0
        if style not in style_performance:
            style_performance[style] = []
        style_performance[style].append(engagement)

    avg_by_style = {
        style: sum(rates) / len(rates)
        for style, rates in style_performance.items()
        if rates
    }

    return f"""
Recent domains published (last 7 days): {recent_domains or 'none yet'}
Recent visual styles used (last 7 days): {recent_styles or 'none yet'}
Performance by style (avg engagement rate): {avg_by_style or 'no data yet'}
Total successful publications: {len([p for p in recent_pubs if p.get('statut') == 'success'])}
"""


# ---------------------------------------------------------------------------
# Web search pour tendances
# ---------------------------------------------------------------------------

TREND_SEARCH_PROMPT = """\
Search for the hottest tech news or trends from the last 24-48 hours across these domains:
AI & Automation, DevOps & Cloud, Cybersecurity, Web Development, Networking, Data Science.

Find the single most viral, surprising, or impactful story that would make great social media
content for a tech education platform. Return a 3-sentence summary including:
1. The domain it belongs to
2. What happened / the key insight
3. Why developers and tech people would care
"""

def _fetch_trending_topic() -> str:
    """Récupère la tendance tech du moment via web search."""
    try:
        result = call_anthropic(
            messages=[{"role": "user", "content": TREND_SEARCH_PROMPT}],
            system="You are a tech news researcher. Search the web and return a factual, concise summary.",
            max_tokens=512,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
        )
        return result.strip() or "No trending topic found."
    except Exception as exc:
        return f"Web search unavailable: {exc}"


# ---------------------------------------------------------------------------
# Décision autonome
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the autonomous content director for KORTEX, a tech education platform. "
    "You make 100% independent decisions about content strategy. "
    "Respond ONLY with a valid JSON object, no text before or after, no markdown."
)

DECISION_PROMPT = """\
You are the autonomous content director for KORTEX (@kortex.platform on Instagram).
Today is {today} ({weekday}).

PERFORMANCE & HISTORY CONTEXT:
{context}

TRENDING TECH NEWS RIGHT NOW:
{trending}

AVAILABLE DOMAINS: {domains}
AVAILABLE VISUAL STYLES: {styles}
AVAILABLE FORMATS: {formats}
AVAILABLE ANGLES: {angles}

AVAILABLE COURSES ON KORTEX RIGHT NOW:
{courses_available}

NEW CONTENT TYPES:
- course_teaser: Showcase a specific KORTEX course. Highlight what the student will learn,
  why it matters now, and drive to link in bio. Use when a course matches today's trending topic.
- social_proof: Share a milestone, stat, or testimonial about KORTEX.
  "X developers already enrolled", "Our AI course covers Y", etc.
  Use to build trust and credibility.

Make today's content decision. Your rules:
1. NEVER repeat the same domain as the last 2 posts
2. NEVER repeat the same visual style as yesterday
3. PRIORITIZE styles that have higher engagement rates (from history)
4. If a trending topic is strong, use it — it will get more reach
5. Post 2 items if today is Monday, Wednesday, or Friday (high-traffic days)
6. Post 1 item on other days
7. Use "carousel" format at least twice per week (higher save rate)
8. Think about what a developer or tech professional would stop scrolling for

UPDATED RULES:
- Use "course_teaser" at least 2x per week — always link to a specific course
- Use "social_proof" at least 1x per week
- Use "conversion" max 1x per week
- Educational/viral/practical/surprising fill the remaining days
- When choosing course_teaser, pick the course most relevant to today's trending topic

Respond with EXACTLY this JSON:
{{
  "posts": [
    {{
      "domain": "one of the available domains",
      "visual_style": "one of the available visual styles",
      "format": "single_image or carousel",
      "angle": "educational/viral/conversion/practical/surprising/course_teaser/social_proof",
      "reasoning": "one sentence: why this choice today"
    }}
  ],
  "director_note": "one sentence summary of today's strategy"
}}
"""


def decide(demo: bool = False) -> dict:
    """Décision 100% autonome du Director."""
    if demo:
        return {
            "posts": [
                {
                    "domain": "AI & Automation",
                    "visual_style": "isometric",
                    "format": "single_image",
                    "angle": "viral",
                    "reasoning": "DEMO mode — AI content always performs well on Mondays",
                    "fal_model": VISUAL_STYLES["isometric"]["fal_model"],
                    "prompt_style": VISUAL_STYLES["isometric"]["prompt_style"],
                    "cta_link": KORTEX_SITE_URL,
                }
            ],
            "director_note": "DEMO: Testing isometric style for AI domain.",
        }

    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().strftime("%A")

    context = _build_context_summary()

    print("[agent0] Fetching trending tech topic…", file=sys.stderr)
    trending = _fetch_trending_topic()
    print(f"[agent0] Trending: {trending[:80]}…", file=sys.stderr)

    courses = _load_published_courses()
    courses_str = "\n".join(
        [f"- {c['title']} ({c['domain']}, ${c.get('price_usd', 'N/A')})" for c in courses]
    ) if courses else "No courses published yet — use generic KORTEX platform teaser"

    response = call_anthropic(
        messages=[{
            "role": "user",
            "content": DECISION_PROMPT.format(
                today=today,
                weekday=weekday,
                context=context,
                trending=trending,
                domains=DOMAINS,
                styles=list(VISUAL_STYLES.keys()),
                formats=FORMATS,
                angles=CONTENT_ANGLES,
                courses_available=courses_str,
            ),
        }],
        system=SYSTEM_PROMPT,
        max_tokens=1024,
    )

    decision = extract_json(response)
    # Enrichit chaque post avec les infos du style visuel
    for post in decision.get("posts", []):
        style_key = post.get("visual_style", "cinematic")
        post["fal_model"] = VISUAL_STYLES.get(style_key, VISUAL_STYLES["cinematic"])["fal_model"]
        post["prompt_style"] = VISUAL_STYLES.get(style_key, VISUAL_STYLES["cinematic"])["prompt_style"]
        post["cta_link"] = KORTEX_SITE_URL

    return decision


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 0: Director")
    parser.add_argument("--demo", action="store_true", help="Demo mode")
    args = parser.parse_args()

    decision = decide(demo=args.demo)
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
