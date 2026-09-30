"""Marketing KORTEX — Agent 2 : Création de Contenu.

Reçoit la décision de l'Agent 1 (`{topic, format, angle, cta_link, image_prompt, domain}`) et
génère les textes des 3 canaux via l'API Anthropic, plus un visuel 1080x1080 via fal.ai (Flux Pro).

Pipeline image :
  1. Agent 1 fournit `image_prompt` — description visuelle riche (humains, objets, scène concrète)
  2. fal.ai Flux Pro génère l'image (qualité professionnelle, ~$0.05/image)
  3. Pillow ajoute le titre + wordmark KORTEX par-dessus en overlay semi-transparent
  4. L'image finale est sauvegardée localement puis hébergée par agent3_publisher

Fallback : si FAL_API_KEY absente ou appel échoué → template Pillow pur (fond dégradé KORTEX).
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from marketing.config import GENERATED_IMAGES_DIR, call_anthropic, extract_json

# ---------------------------------------------------------------------------
# Constantes visuelles KORTEX
# ---------------------------------------------------------------------------
IMAGE_SIZE = 1080
BG_TOP    = (13, 27, 62)    # #0d1b3e
BG_BOTTOM = (26, 5, 51)     # #1a0533
VIOLET    = (124, 58, 237)  # #7c3aed
WHITE     = (255, 255, 255)

ARIAL_BOLD    = Path(r"C:\Windows\Fonts\arialbd.ttf")
ARIAL_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")

FAL_API_KEY = os.environ.get("FAL_API_KEY", "")

# ---------------------------------------------------------------------------
# Modèles fal.ai par style visuel (choisi par agent0_director.py)
# ---------------------------------------------------------------------------
FAL_MODELS = {
    "cinematic": {
        "endpoint": "https://fal.run/fal-ai/flux-pro/v1.1",
        "payload_extra": {"output_format": "jpeg", "safety_tolerance": "2", "num_images": 1},
    },
    "minimal": {
        "endpoint": "https://fal.run/fal-ai/flux-pro/v1.1",
        "payload_extra": {"output_format": "jpeg", "safety_tolerance": "2", "num_images": 1},
    },
    "human_story": {
        "endpoint": "https://fal.run/fal-ai/flux-pro/v1.1",
        "payload_extra": {"output_format": "jpeg", "safety_tolerance": "2", "num_images": 1},
    },
    "isometric": {
        "endpoint": "https://fal.run/fal-ai/recraft-v3",
        # "vector_illustration" renvoie du SVG (content_type image/svg+xml) — Pillow ne peut pas
        # l'ouvrir (UnidentifiedImageError), confirmé par test direct. "digital_illustration"
        # renvoie un raster (WebP) tout en gardant un rendu illustration colorée/plate — le style
        # isométrique vient du texte du prompt (voir VISUAL_STYLES["isometric"]["prompt_style"]
        # dans agent0_director.py), pas de ce paramètre API.
        "payload_extra": {"style": "digital_illustration", "num_images": 1},
    },
    "infographic": {
        "endpoint": "https://fal.run/fal-ai/ideogram/v3",
        "payload_extra": {"rendering_speed": "QUALITY", "num_images": 1},
    },
}
FAL_DEFAULT_MODEL = FAL_MODELS["cinematic"]

# ---------------------------------------------------------------------------
# Prompts LLM
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are the social media copywriter for KORTEX, an online tech education platform. "
    "Your style is direct, concrete, never corporate. Write ALL content in English. "
    "Respond ONLY with a valid JSON object, no text before or after, no markdown code blocks."
)

PROMPT_TEMPLATE = """\
Sujet du jour : "{topic}"
Format : {format}
Angle éditorial : {angle}
Lien CTA à utiliser : {cta_link}

Generate content for 3 channels + an image prompt. ALL TEXT MUST BE IN ENGLISH:

1. facebook : post 300-500 mots, emojis pertinents, CTA vers {cta_link}.
2. instagram : légende ~150 mots, punchy, SANS hashtags.
3. instagram_hashtags : 8-15 hashtags (français + anglais), sans le symbole #.
4. telegram : message court Markdown (gras **), ton direct, lien {cta_link} inclus.
5. image_prompt : visual description IN ENGLISH to generate the post image.
   Visual style required: {visual_style} — {prompt_style}

   Adapt your description to match this style EXACTLY:
   - cinematic → dramatic real scene, humans, objects, cinematic lighting, photorealistic 4k
   - isometric → colorful illustration, cartoon tech characters, flat design objects, no photo
   - infographic → technical diagram with labeled boxes, arrows, icons, flowchart, white background, NO people
   - minimal → clean bright photo, white/light background, simple composition, Apple aesthetic
   - human_story → natural portrait, real person working, warm authentic light, candid

   NO text inside the image. Generate a prompt that will produce a {visual_style} image.
   Example for infographic: "Clean technical flowchart showing AI agent architecture with labeled boxes,
   arrows connecting components, icons for database/API/LLM, white background, professional diagram style"

Réponds avec EXACTEMENT ce format JSON :
{{
  "facebook": "...",
  "instagram": "...",
  "instagram_hashtags": ["...", "..."],
  "telegram": "...",
  "image_prompt": "..."
}}
"""

# ---------------------------------------------------------------------------
# Génération textes
# ---------------------------------------------------------------------------

def _demo_content() -> dict:
    return {
        "facebook": "[DEMO] Post Facebook.",
        "instagram": "[DEMO] Légende Instagram.",
        "instagram_hashtags": ["formation", "IA", "productivite"],
        "telegram": "[DEMO] Message Telegram.",
        "image_prompt": (
            "Clean technical flowchart showing AI agent workflow: labeled boxes for "
            "Input/LLM/Tool/Output connected by arrows, icons for database and API, "
            "white background, professional infographic style, no people"
        ),
    }


def generate_texts(strategy: dict, demo: bool = False) -> dict:
    if demo:
        return _demo_content()
    response_text = call_anthropic(
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(
            topic=strategy["topic"],
            format=strategy["format"],
            angle=strategy["angle"],
            cta_link=strategy["cta_link"],
            visual_style=strategy.get("visual_style", "cinematic"),
            prompt_style=strategy.get("prompt_style", "photorealistic, cinematic lighting, dramatic, 4k"),
        )}],
        system=SYSTEM_PROMPT,
        max_tokens=4096,
    )
    return extract_json(response_text)


# ---------------------------------------------------------------------------
# fal.ai Flux Pro
# ---------------------------------------------------------------------------

def _generate_image_fal(image_prompt: str, visual_style: str = "cinematic") -> bytes | None:
    """Appelle le modèle fal.ai correspondant à `visual_style` (voir FAL_MODELS), retourne les
    bytes de l'image ou None si échec."""
    if not FAL_API_KEY:
        return None
    try:
        import urllib.request
        import json as _json

        model_cfg = FAL_MODELS.get(visual_style, FAL_DEFAULT_MODEL)
        payload = {"prompt": image_prompt, "image_size": "square_hd"}
        payload.update(model_cfg["payload_extra"])

        req = urllib.request.Request(
            model_cfg["endpoint"],
            data=_json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = _json.loads(resp.read().decode("utf-8"))

        # Recraft et Ideogram peuvent retourner l'image différemment
        images = result.get("images") or result.get("image") or []
        if isinstance(images, dict):
            images = [images]
        if not images:
            raise ValueError(f"No images in response: {result}")
        image_url = images[0].get("url") or images[0].get("image_url", "")

        with urllib.request.urlopen(image_url, timeout=30) as img_resp:
            return img_resp.read()

    except Exception as exc:
        print(f"[agent2] fal.ai échec ({visual_style}): {exc} — fallback Pillow", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Overlay Pillow
# ---------------------------------------------------------------------------

def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_font(draw, text, max_width, max_lines, start_size=72, min_size=36):
    size = start_size
    while size > min_size:
        font = ImageFont.truetype(str(ARIAL_BOLD), size)
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
        size -= 4
    font = ImageFont.truetype(str(ARIAL_BOLD), min_size)
    return font, _wrap_text(draw, text, font, max_width)


def _apply_overlay(img: Image.Image, title: str, domain: str = "") -> Image.Image:
    """Bandeau sombre en bas avec titre + wordmark KORTEX. band_h dynamique."""
    W, H = img.size
    margin = 55
    footer_h = 80
    padding = 28

    # --- Mesure du titre d'abord (sur un draw temporaire) ---
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    max_w = W - 2 * margin
    title_font, lines = _fit_font(tmp_draw, title, max_w, max_lines=3, start_size=62, min_size=34)
    line_h = title_font.size + 14
    block_h = line_h * len(lines)

    # band_h dynamique selon le contenu réel
    band_h = max(block_h + padding * 2 + footer_h, 240)

    # --- Calque overlay (dégradé + ligne violette) ---
    img = img.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)

    for y in range(H - band_h, H):
        t = (y - (H - band_h)) / band_h
        alpha = int(160 + 80 * t)
        draw_ov.line([(0, y), (W, y)], fill=(8, 3, 22, alpha))

    draw_ov.rectangle(
        [(margin, H - band_h + 4), (W - margin, H - band_h + 7)],
        fill=(124, 58, 237, 230),
    )

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # --- Titre ---
    text_y = H - band_h + 4 + padding
    for line in lines:
        draw.text((margin + 2, text_y + 2), line, font=title_font, fill=(0, 0, 0, 200))
        draw.text((margin, text_y), line, font=title_font, fill=WHITE)
        text_y += line_h

    # --- Footer ---
    footer_y = H - 68
    if domain:
        dom_font = ImageFont.truetype(str(ARIAL_REGULAR), 26)
        draw.text((margin, footer_y), domain.upper(), font=dom_font, fill=(180, 180, 210))

    wm_font = ImageFont.truetype(str(ARIAL_BOLD), 44)
    prefix, suffix = "KORTE", "X"
    pw = draw.textlength(prefix, font=wm_font)
    sw = draw.textlength(suffix, font=wm_font)
    wm_x = W - margin - pw - sw
    draw.text((wm_x, footer_y - 4), prefix, font=wm_font, fill=WHITE)
    draw.text((wm_x + pw, footer_y - 4), suffix, font=wm_font, fill=VIOLET)

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Fallback Pillow pur
# ---------------------------------------------------------------------------

def _pillow_fallback(title: str, domain: str = "") -> Image.Image:
    img = Image.new("RGB", (IMAGE_SIZE, IMAGE_SIZE), BG_TOP)
    draw = ImageDraw.Draw(img)

    # Dégradé vertical
    for y in range(IMAGE_SIZE):
        t = y / IMAGE_SIZE
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (IMAGE_SIZE, y)], fill=(r, g, b))

    margin = 80
    max_w = IMAGE_SIZE - 2 * margin
    title_font, lines = _fit_font(draw, title, max_w, max_lines=5, start_size=80, min_size=40)
    line_h = title_font.size + 16
    block_h = line_h * len(lines)
    y = (IMAGE_SIZE - block_h) // 2 - 60

    for line in lines:
        lw = draw.textlength(line, font=title_font)
        draw.text(((IMAGE_SIZE - lw) // 2, y), line, font=title_font, fill=WHITE)
        y += line_h

    bar_y = IMAGE_SIZE - 150
    draw.rectangle([(margin, bar_y), (IMAGE_SIZE - margin, bar_y + 3)], fill=VIOLET)

    wm_font = ImageFont.truetype(str(ARIAL_BOLD), 48)
    prefix, suffix = "KORTE", "X"
    pw = draw.textlength(prefix, font=wm_font)
    sw = draw.textlength(suffix, font=wm_font)
    wm_x = (IMAGE_SIZE - pw - sw) // 2
    draw.text((wm_x, IMAGE_SIZE - 115), prefix, font=wm_font, fill=WHITE)
    draw.text((wm_x + pw, IMAGE_SIZE - 115), suffix, font=wm_font, fill=VIOLET)

    return img


# ---------------------------------------------------------------------------
# Génération image finale
# ---------------------------------------------------------------------------

def generate_image_card(
    title: str,
    image_prompt: str = "",
    domain: str = "",
    visual_style: str = "cinematic",
) -> Path:
    filename = f"{int(time.time())}.png"
    image_path = GENERATED_IMAGES_DIR / filename

    if FAL_API_KEY and image_prompt:
        print(f"[agent2] Appel fal.ai ({visual_style})…", file=sys.stderr)
        img_bytes = _generate_image_fal(image_prompt, visual_style=visual_style)
        if img_bytes:
            base_img = Image.open(io.BytesIO(img_bytes)).resize(
                (IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS
            )
            final_img = _apply_overlay(base_img, title, domain)
            final_img.save(image_path, "PNG")
            print(f"[agent2] ✓ Image {visual_style} : {image_path}", file=sys.stderr)
            return image_path
        print(f"[agent2] {visual_style} KO → fallback Pillow", file=sys.stderr)

    final_img = _pillow_fallback(title, domain)
    final_img.save(image_path, "PNG")
    return image_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def create_content(strategy: dict, demo: bool = False) -> dict:
    texts = generate_texts(strategy, demo=demo)
    image_prompt = texts.get("image_prompt", strategy.get("image_prompt", ""))
    visual_style = strategy.get("visual_style", "cinematic")
    image_path = generate_image_card(
        title=strategy["topic"],
        image_prompt=image_prompt,
        domain=strategy.get("domain", ""),
        visual_style=visual_style,
    )
    return {
        "fb_text": texts["facebook"],
        "ig_caption": texts["instagram"],
        "ig_hashtags": texts["instagram_hashtags"],
        "tg_text": texts["telegram"],
        "image_path": str(image_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Marketing KORTEX — Agent 2")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--strategy-json", type=str, default="")
    args = parser.parse_args()

    if args.strategy_json:
        strategy = json.loads(args.strategy_json)
    elif args.demo:
        strategy = {
            "topic": "Why 73% of AI agents fail silently in production",
            "format": "tip",
            "angle": "Coûts cachés des agents IA en production",
            "cta_link": "https://cours.aymen-automation.site",
            "domain": "AI & Automation",
            "visual_style": "isometric",
        }
    else:
        raise SystemExit("--strategy-json requis hors --demo")

    content = create_content(strategy, demo=args.demo)
    print(json.dumps(content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()