"""Marketing KORTEX — Agent 2 (carrousel) : Génération de carrousels Instagram 5 slides.

Variante de agent2_content.py pour le format "carousel" décidé par agent0_director.py — réutilise
ses fonctions/constantes existantes (`_generate_image_fal`, `_fit_font`, `_wrap_text`, constantes
visuelles) au lieu de les dupliquer. `_apply_overlay`/`_pillow_fallback` (layout plein cadre avec
dégradé semi-transparent) ne sont PLUS utilisées ici depuis le layout 70/30 — voir
`_apply_carousel_overlay` ci-dessous, propre à ce module.

Layout validé (toutes les slides, uniforme) :
  - Image (fal.ai, ou fond dégradé pour la slide CTA) : 70% de la hauteur (756px / 1080px)
  - Bandeau KORTEX fixe : 30% de la hauteur (324px) — fond #0d1b3e, bordure violette 4px en haut,
    titre court (max 8 mots, bold 52px, blanc, 1-2 lignes), badge de position en haut à droite du
    bandeau (slides 2-4 uniquement, jamais sur l'image), footer domaine (gris, gauche) + wordmark
    KORTEX (droite). Pas de "body" dans le bandeau — l'image seule porte le message visuel.

Structure du carrousel (toujours 5 slides) :
  1. Hook fort — image fal.ai + bandeau, pas de badge
  2-4. Point clé — image fal.ai + bandeau + badge "2/5"/"3/5"/"4/5"
  5. CTA — "Save this. Follow @kortex.platform." — fond dégradé KORTEX + icône (PAS d'appel fal.ai,
     pas de scène à décrire pour un simple appel à l'action), même bandeau que les autres slides."""

import argparse
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketing.agent2_content import (
    ARIAL_BOLD,
    ARIAL_REGULAR,
    BG_BOTTOM,
    BG_TOP,
    FAL_API_KEY,
    IMAGE_SIZE,
    VIOLET,
    WHITE,
    _fit_font,
    _generate_image_fal,
    _wrap_text,
)
from marketing.config import GENERATED_IMAGES_DIR, MarketingAPIError, call_anthropic, extract_json

CTA_HEADLINE = "Save this. Follow @kortex.platform."

# ---------------------------------------------------------------------------
# Layout 70/30 (validé) — constantes propres au carrousel
# ---------------------------------------------------------------------------
IMAGE_BAND_HEIGHT = int(IMAGE_SIZE * 0.7)  # 756
KORTEX_BAND_BG = (13, 27, 62)  # #0d1b3e
GREY = (170, 170, 190)

# ---------------------------------------------------------------------------
# Prompts LLM
# ---------------------------------------------------------------------------

CAROUSEL_SYSTEM_PROMPT = (
    "You are the social media copywriter for KORTEX, an online tech education platform. "
    "You write Instagram carousels (5 slides) that teach one clear idea, slide by slide. "
    "Your style is direct, concrete, never corporate. Write ALL content in English. "
    "Respond ONLY with a valid JSON object, no text before or after, no markdown code blocks."
)

CAROUSEL_PROMPT_TEMPLATE = """\
Topic: "{topic}"
Angle: {angle}
Domain: {domain}
CTA link: {cta_link}
Visual style required for every slide image: {visual_style} — {prompt_style}

Write a 5-slide Instagram carousel that teaches ONE clear idea about this topic, slide by slide:

- Slide 1 (hook): a strong scroll-stopping headline that states the problem or surprising claim.
- Slides 2-4 (key points): one concrete, actionable point per slide, building on the previous one.
- Slide 5 (CTA): headline MUST be exactly "{cta_headline}" (do not change it).

For EACH of the 5 slides, provide:
- headline : short (max ~8 words), punchy, fits large on an image — NOT a full sentence
- body : 1-2 sentences of supporting detail (for the caption / internal use, not drawn on the image)
- image_prompt : visual description IN ENGLISH for slides 1-4 only (empty string "" for slide 5,
  which uses a plain gradient background, no photo). ALWAYS describe a CONCRETE SCENE with
  people and/or objects — NEVER a diagram, flowchart, chart, or any text/labels inside the image.
  Adapt the STYLE to the visual style EXACTLY like this (scene content stays concrete either way):
  - cinematic → dramatic real scene, humans, objects, cinematic lighting, photorealistic 4k
  - isometric → colorful illustration, cartoon tech characters interacting with objects, flat
    design, no photo
  - infographic → clean minimal illustration of a person using tech (laptop, screen, device
    visible in the scene), bright/light background, professional — a SCENE with a person, not a
    diagram
  - minimal → clean bright photo, white/light background, simple composition, one person or
    object, Apple aesthetic
  - human_story → natural portrait, real person working, warm authentic light, candid
  NO text, labels, boxes, or arrows inside any image.

Also provide:
- ig_caption : ~150 words Instagram caption for the whole carousel, punchy, summarizing the value,
  ending with a CTA to {cta_link}. SANS hashtags (separate field).
- ig_hashtags : 8-15 hashtags (no # symbol), relevant to KORTEX and the topic.

Respond with EXACTLY this JSON format:
{{
  "slides": [
    {{"headline": "...", "body": "...", "image_prompt": "..."}},
    {{"headline": "...", "body": "...", "image_prompt": "..."}},
    {{"headline": "...", "body": "...", "image_prompt": "..."}},
    {{"headline": "...", "body": "...", "image_prompt": "..."}},
    {{"headline": "{cta_headline}", "body": "...", "image_prompt": ""}}
  ],
  "ig_caption": "...",
  "ig_hashtags": ["...", "..."]
}}
"""


def _demo_carousel_content() -> dict:
    """Stub déterministe, aucun appel réseau vers Claude (les images, elles, sont réellement
    générées via fal.ai/Pillow — même convention que agent2_content.py::_demo_content, où seul le
    texte est stubé, jamais l'image)."""
    return {
        "slides": [
            {
                "headline": "Your AI agent is bleeding money",
                "body": "[DEMO] Production costs creep up silently — most teams don't notice until the invoice.",
                "image_prompt": (
                    "A focused developer looking worried at a laptop showing a rising cost graph, "
                    "dramatic purple ambient lighting, cinematic shallow depth of field, photorealistic 4k"
                ),
            },
            {
                "headline": "1. Watch your RAG context size",
                "body": "[DEMO] Bloated retrieval context means every call costs more, silently.",
                "image_prompt": (
                    "A developer pointing at a laptop screen showing a document search interface, "
                    "explaining something to a colleague, bright clean office, natural light, "
                    "professional candid photo"
                ),
            },
            {
                "headline": "2. Cap your prompt growth",
                "body": "[DEMO] System prompts that grow with every iteration quietly inflate token costs.",
                "image_prompt": (
                    "A developer scrolling through a very long text document on a laptop, looking "
                    "concerned, sticky notes on the desk, bright clean office, natural light, "
                    "professional candid photo"
                ),
            },
            {
                "headline": "3. Build a cost dashboard",
                "body": "[DEMO] Track cost per call, per ticket, and cumulative — before the bill, not after.",
                "image_prompt": (
                    "A developer smiling while looking at a laptop showing colorful charts, "
                    "coffee cup on the desk, bright modern office, natural light, professional "
                    "candid photo"
                ),
            },
            {
                "headline": CTA_HEADLINE,
                "body": "[DEMO] Come back to this checklist next time you deploy an agent.",
                "image_prompt": "",
            },
        ],
        "ig_caption": (
            "[DEMO] Your AI agent's bill going up and nobody knows why? It's rarely one big thing — "
            "it's RAG context bloat, an ever-growing system prompt, and zero cost visibility, all "
            "stacking quietly. Swipe through 3 fixes that actually move the needle, then go build "
            "them with us. Link in bio."
        ),
        "ig_hashtags": [
            "AI", "AIagents", "DevOps", "MLOps", "TechEducation", "KORTEX", "PromptEngineering", "CloudCosts",
        ],
    }


def _generate_carousel_texts(strategy: dict, demo: bool = False) -> dict:
    """Génère `{slides: [5x {headline, body, image_prompt}], ig_caption, ig_hashtags}`. Mode démo :
    stub déterministe, aucun appel réseau vers Claude."""
    if demo:
        return _demo_carousel_content()

    response_text = call_anthropic(
        messages=[
            {
                "role": "user",
                "content": CAROUSEL_PROMPT_TEMPLATE.format(
                    topic=strategy["topic"],
                    angle=strategy["angle"],
                    domain=strategy.get("domain", ""),
                    cta_link=strategy["cta_link"],
                    visual_style=strategy.get("visual_style", "cinematic"),
                    prompt_style=strategy.get("prompt_style", "photorealistic, cinematic lighting, dramatic, 4k"),
                    cta_headline=CTA_HEADLINE,
                ),
            }
        ],
        system=CAROUSEL_SYSTEM_PROMPT,
        max_tokens=4096,
    )
    data = extract_json(response_text)
    slides = data.get("slides", [])
    if len(slides) != 5:
        raise MarketingAPIError(f"Le carrousel doit contenir exactement 5 slides, reçu {len(slides)}")
    return data


# ---------------------------------------------------------------------------
# Layout 70/30 : image (haut) + bandeau KORTEX uniforme (bas)
# ---------------------------------------------------------------------------

def _crop_to_band(img: Image.Image) -> Image.Image:
    """Recadre une image carrée (sortie fal.ai, 1080x1080 après resize) sur 1080xIMAGE_BAND_HEIGHT
    — recadrage centré verticalement pour ne pas couper le sujet de façon asymétrique."""
    img = img.resize((IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS)
    top = (IMAGE_SIZE - IMAGE_BAND_HEIGHT) // 2
    return img.crop((0, top, IMAGE_SIZE, top + IMAGE_BAND_HEIGHT))


def _cta_image_band(cta_link: str = "") -> Image.Image:
    """Fond dégradé KORTEX + grande icône "bookmark" + texte centré (jamais d'appel fal.ai) —
    remplace la photo fal.ai sur la slide CTA tout en occupant les mêmes 70% de hauteur que les
    autres slides, avec un contenu visuellement riche (pas une icône isolée sur fond vide) :
    icône bookmark (200px, trait violet épais), "Save this." en très grand blanc, "Follow
    @kortex.platform" en violet, l'URL du CTA en gris — le tout centré verticalement dans la zone."""
    img = Image.new("RGB", (IMAGE_SIZE, IMAGE_BAND_HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(img)
    for y in range(IMAGE_BAND_HEIGHT):
        t = y / IMAGE_BAND_HEIGHT
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (IMAGE_SIZE, y)], fill=(r, g, b))

    cx = IMAGE_SIZE // 2
    icon_h = 200
    icon_w = int(icon_h * 160 / 220)
    notch = int(icon_h * 55 / 220)

    save_font = ImageFont.truetype(str(ARIAL_BOLD), 80)
    follow_font = ImageFont.truetype(str(ARIAL_BOLD), 50)
    url_font = ImageFont.truetype(str(ARIAL_REGULAR), 32)

    save_text = "Save this."
    follow_text = "Follow @kortex.platform"
    url_text = cta_link.replace("https://", "").replace("http://", "").rstrip("/") if cta_link else ""

    gap_icon_save, gap_save_follow, gap_follow_url = 30, 20, 16
    save_h = save_font.size + 16
    follow_h = follow_font.size + 12
    url_h = (url_font.size + 10) if url_text else -gap_follow_url

    total_h = icon_h + gap_icon_save + save_h + gap_save_follow + follow_h + (gap_follow_url + url_h if url_text else 0)
    y = (IMAGE_BAND_HEIGHT - total_h) // 2

    # Icône bookmark, agrandie (200px), centrée horizontalement
    x0, x1 = cx - icon_w // 2, cx + icon_w // 2
    y0, y1 = y, y + icon_h
    draw.polygon(
        [(x0, y0), (x1, y0), (x1, y1), (cx, y1 - notch), (x0, y1)],
        outline=VIOLET,
        width=14,
    )
    y = y1 + gap_icon_save

    save_w = draw.textlength(save_text, font=save_font)
    draw.text((cx - save_w / 2, y), save_text, font=save_font, fill=WHITE)
    y += save_h + gap_save_follow

    follow_w = draw.textlength(follow_text, font=follow_font)
    draw.text((cx - follow_w / 2, y), follow_text, font=follow_font, fill=VIOLET)
    y += follow_h + gap_follow_url

    if url_text:
        url_w = draw.textlength(url_text, font=url_font)
        draw.text((cx - url_w / 2, y), url_text, font=url_font, fill=GREY)

    return img


def _apply_carousel_overlay(image_band: Image.Image, headline: str, domain: str, badge: str | None) -> Image.Image:
    """Compose le layout carrousel validé sur un canevas 1080x1080 :
    - `image_band` (1080xIMAGE_BAND_HEIGHT, déjà recadrée) occupe les 70% du haut, collée telle quelle
    - bandeau KORTEX fixe sur les 30% du bas : fond #0d1b3e, bordure violette 4px en haut, titre
      court (bold 52px, blanc, 1-2 lignes max), badge de position en haut à droite DU BANDEAU
      (jamais sur l'image — slides 2-4 seulement), footer domaine (gris, gauche) + wordmark KORTEX
      (droite). Une zone de 60px est réservée au badge que celui-ci soit présent ou non, pour que
      le titre démarre TOUJOURS à la même hauteur sur les 5 slides (alignement visuel au swipe)."""
    canvas = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), KORTEX_BAND_BG)
    canvas.paste(image_band, (0, 0))
    draw = ImageDraw.Draw(canvas)

    band_top = IMAGE_BAND_HEIGHT
    draw.rectangle([(0, band_top), (IMAGE_SIZE, band_top + 4)], fill=VIOLET)

    margin = 55
    content_top = band_top + 4
    badge_zone_h = 60

    if badge:
        badge_font = ImageFont.truetype(str(ARIAL_BOLD), 28)
        pad_x, pad_y = 20, 10
        text_w = draw.textlength(badge, font=badge_font)
        bx1 = IMAGE_SIZE - margin
        bx0 = bx1 - text_w - pad_x * 2
        by0 = content_top + 14
        by1 = by0 + 28 + pad_y * 2
        draw.rounded_rectangle([bx0, by0, bx1, by1], radius=(by1 - by0) / 2, fill=VIOLET)
        draw.text((bx0 + pad_x, by0 + pad_y - 2), badge, font=badge_font, fill=WHITE)

    title_font, lines = _fit_font(
        draw, headline, IMAGE_SIZE - 2 * margin, max_lines=2, start_size=52, min_size=36
    )
    line_h = title_font.size + 12
    title_y = content_top + badge_zone_h
    for line in lines:
        draw.text((margin, title_y), line, font=title_font, fill=WHITE)
        title_y += line_h

    footer_y = IMAGE_SIZE - 60
    if domain:
        dom_font = ImageFont.truetype(str(ARIAL_REGULAR), 26)
        draw.text((margin, footer_y), domain.upper(), font=dom_font, fill=GREY)

    wm_font = ImageFont.truetype(str(ARIAL_BOLD), 40)
    prefix, suffix = "KORTE", "X"
    pw = draw.textlength(prefix, font=wm_font)
    sw = draw.textlength(suffix, font=wm_font)
    wm_x = IMAGE_SIZE - margin - pw - sw
    draw.text((wm_x, footer_y - 6), prefix, font=wm_font, fill=WHITE)
    draw.text((wm_x + pw, footer_y - 6), suffix, font=wm_font, fill=VIOLET)

    return canvas


def _generate_slide_image(image_prompt: str, visual_style: str, headline: str, domain: str, badge: str | None) -> Image.Image:
    """Slide 1-4 : image fal.ai recadrée à 70% de hauteur + bandeau KORTEX uniforme. Si fal.ai est
    indisponible/échoue, retombe sur un fond dégradé simple (jamais de photo cassée) — le titre
    reste porté par le bandeau dans les deux cas, pas de double affichage."""
    img_bytes = _generate_image_fal(image_prompt, visual_style=visual_style) if FAL_API_KEY and image_prompt else None
    if img_bytes:
        image_band = _crop_to_band(Image.open(io.BytesIO(img_bytes)))
    else:
        image_band = Image.new("RGB", (IMAGE_SIZE, IMAGE_BAND_HEIGHT), BG_TOP)
    return _apply_carousel_overlay(image_band, headline, domain, badge)


def generate_carousel(strategy: dict, demo: bool = False) -> dict:
    """Orchestration complète : génère le texte des 5 slides (Claude ou stub démo), puis chaque
    image — layout 70/30 uniforme (fal.ai + bandeau pour les slides 1-4, dégradé KORTEX + icône +
    bandeau pour la slide 5/CTA, jamais d'appel fal.ai sur cette dernière).

    Retourne `{slides_data, image_paths, ig_caption, ig_hashtags}` — `slides_data` est la liste brute
    des 5 `{headline, body, image_prompt}` (utile pour logs/debug), `image_paths` les 5 fichiers PNG
    locaux dans l'ordre d'affichage du carrousel."""
    carousel_data = _generate_carousel_texts(strategy, demo=demo)
    visual_style = strategy.get("visual_style", "cinematic")
    domain = strategy.get("domain", "")
    slides = carousel_data["slides"]

    image_paths: list[str] = []
    timestamp = int(time.time())

    # Slides 1-4 : fal.ai + bandeau. Pas de badge sur la slide 1 (le hook), "2/5"-"4/5" ensuite.
    for i, slide in enumerate(slides[:4]):
        badge = f"{i + 1}/5" if i > 0 else None
        img = _generate_slide_image(slide.get("image_prompt", ""), visual_style, slide["headline"], domain, badge)
        path = GENERATED_IMAGES_DIR / f"{timestamp}_carousel_{i + 1}.png"
        img.save(path, "PNG")
        image_paths.append(str(path))

    # Slide 5 : CTA, dégradé KORTEX + icône (jamais fal.ai) + même bandeau que les autres slides.
    # Le bandeau affiche l'URL, pas CTA_HEADLINE : "Save this. Follow @kortex.platform." est déjà
    # affiché dans la zone image (voir _cta_image_band) — pas besoin de le répéter dans le bandeau.
    cta_link = strategy.get("cta_link", "")
    cta_band_title = cta_link.replace("https://", "").replace("http://", "").rstrip("/") or CTA_HEADLINE
    cta_img = _apply_carousel_overlay(
        _cta_image_band(cta_link), cta_band_title, domain, badge=None
    )
    cta_path = GENERATED_IMAGES_DIR / f"{timestamp}_carousel_5.png"
    cta_img.save(cta_path, "PNG")
    image_paths.append(str(cta_path))

    return {
        "slides_data": slides,
        "image_paths": image_paths,
        "ig_caption": carousel_data["ig_caption"],
        "ig_hashtags": carousel_data["ig_hashtags"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 2 (carrousel)")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--strategy-json", type=str, default="")
    args = parser.parse_args()

    if args.strategy_json:
        strategy = json.loads(args.strategy_json)
    elif args.demo:
        strategy = {
            "topic": "3 hidden costs draining your AI agent's budget in production",
            "format": "carousel",
            "angle": "Hidden costs of AI agents in production, for devs running agents at scale",
            "cta_link": "https://cours.aymen-automation.site",
            "domain": "AI & Automation",
            "visual_style": "infographic",
            "prompt_style": "clean infographic, technical diagram, icons, arrows, flowchart, professional, white background",
        }
    else:
        raise SystemExit("--strategy-json requis hors --demo")

    result = generate_carousel(strategy, demo=args.demo)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
