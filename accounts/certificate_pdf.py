"""Génération du PDF d'attestation — ReportLab (pur Python, aucune dépendance système), pas
WeasyPrint : WeasyPrint a besoin de Pango/Cairo/GDK-Pixbuf, non installables via `pip install -r
requirements.txt` seul sur le runtime Python natif de Render (voir render.yaml — pas de Dockerfile
ni d'étape d'installation système). ReportLab s'installe et s'exécute sans rien de plus.

Design Phase 3 (2026-08-13) : remplace l'ancien bandeau dégradé par une identité « certificat
papier » — fond chaud, double cadre violet/magenta avec repères d'angle, sceau central. Signature
de `render_certificate_pdf` INCHANGÉE (accounts/certificate_routes.py ne change pas).

Ce module ne connaît que la mise en page — il ne touche à aucune base de données et ne valide
aucune éligibilité (voir accounts/certificate_routes.py pour ça)."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

PAGE_SIZE = landscape(A4)

_PAPER = colors.HexColor("#faf9f5")
_VIOLET = colors.HexColor("#7F77DD")
_VIOLET_DARK = colors.HexColor("#4B3F99")
_MAGENTA = colors.HexColor("#D4537E")
_INK = colors.HexColor("#2c2c2a")
_MUTED = colors.HexColor("#6b6862")

_OUTER_MARGIN = 1.0 * cm
_INNER_MARGIN = 1.4 * cm


def _spaced(text: str) -> str:
    """Insère une espace entre chaque caractère — approxime des « petites capitales espacées » :
    ReportLab n'a ni petites capitales ni letter-spacing natif sur `drawString`."""
    return " ".join(text)


def _fit_font_size(c: canvas.Canvas, text: str, font: str, max_size: int, max_width: float) -> int:
    """Réduit la taille de police jusqu'à ce que `text` tienne dans `max_width` — le nom d'un
    apprenant ou le titre d'un cours peuvent être longs, jamais tronqués ni débordant du cadre."""
    size = max_size
    while size > 10 and c.stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _draw_corner_marks(c: canvas.Canvas, x0: float, y0: float, x1: float, y1: float) -> None:
    """Petits repères d'angle (façon carte d'imprimerie), juste à l'extérieur du cadre — purement
    décoratif, voir la demande explicite de design."""
    tick = 0.35 * cm
    gap = 0.12 * cm
    c.setStrokeColor(_MAGENTA)
    c.setLineWidth(1.1)
    for corner_x, dir_x in ((x0, -1), (x1, 1)):
        for corner_y, dir_y in ((y0, -1), (y1, 1)):
            ox, oy = corner_x + dir_x * gap, corner_y + dir_y * gap
            c.line(ox, oy, ox + dir_x * tick, oy)
            c.line(ox, oy, ox, oy + dir_y * tick)


def _draw_frame(c: canvas.Canvas, width: float, height: float) -> None:
    """Double cadre : extérieur épais violet, filet intérieur fin magenta, avec repères d'angle
    autour du cadre extérieur."""
    outer = (_OUTER_MARGIN, _OUTER_MARGIN, width - _OUTER_MARGIN, height - _OUTER_MARGIN)
    inner = (_INNER_MARGIN, _INNER_MARGIN, width - _INNER_MARGIN, height - _INNER_MARGIN)

    c.setStrokeColor(_VIOLET)
    c.setLineWidth(3)
    c.rect(outer[0], outer[1], outer[2] - outer[0], outer[3] - outer[1], stroke=1, fill=0)

    c.setStrokeColor(_MAGENTA)
    c.setLineWidth(0.75)
    c.rect(inner[0], inner[1], inner[2] - inner[0], inner[3] - inner[1], stroke=1, fill=0)

    _draw_corner_marks(c, *outer)


def _draw_seal(c: canvas.Canvas, center_x: float, center_y: float) -> None:
    """Sceau central : cercle magenta plein, cercle intérieur violet fin, coche violette —
    élément décoratif signalant l'authenticité ; la vérification réelle reste l'URL publique
    imprimée en pied de page, jamais ce sceau."""
    outer_r = 1.15 * cm
    inner_r = 0.85 * cm

    c.setFillColor(_MAGENTA)
    c.circle(center_x, center_y, outer_r, stroke=0, fill=1)

    c.setStrokeColor(_VIOLET)
    c.setLineWidth(1.2)
    c.circle(center_x, center_y, inner_r, stroke=1, fill=0)

    c.setStrokeColor(_VIOLET)
    c.setLineWidth(2.6)
    c.setLineCap(1)
    c.line(center_x - 0.42 * cm, center_y - 0.02 * cm, center_x - 0.12 * cm, center_y - 0.32 * cm)
    c.line(center_x - 0.12 * cm, center_y - 0.32 * cm, center_x + 0.48 * cm, center_y + 0.38 * cm)


def render_certificate_pdf(
    learner_name: str, course_title: str, issued_at: str, verify_url: str, certificate_id: str
) -> bytes:
    """Retourne les octets d'un PDF d'une page (paysage) — design Phase 3 (2026-08-13) : fond
    papier chaud, double cadre violet/magenta avec repères d'angle, sceau central, nom de
    l'apprenant en violet foncé. `issued_at` est déjà formaté en chaîne lisible par l'appelant.
    Le titre du cours (`course_title`) est celui figé à l'émission de l'attestation (voir
    accounts/certificates.py::issue_certificate), jamais relu depuis le cours courant."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=PAGE_SIZE)
    width, height = PAGE_SIZE

    c.setFillColor(_PAPER)
    c.rect(0, 0, width, height, stroke=0, fill=1)

    _draw_frame(c, width, height)

    content_width = width - 2 * _INNER_MARGIN - 1.2 * cm

    c.setFillColor(_VIOLET)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, height - 2.6 * cm, _spaced("AI EDU PLATFORM"))

    c.setStrokeColor(_MAGENTA)
    c.setLineWidth(1.5)
    c.line(width / 2 - 1.1 * cm, height - 3.05 * cm, width / 2 + 1.1 * cm, height - 3.05 * cm)

    c.setFillColor(_INK)
    c.setFont("Times-Bold", 30)
    c.drawCentredString(width / 2, height - 4.7 * cm, "Attestation de réussite")

    c.setFillColor(_MUTED)
    c.setFont("Times-Italic", 14)
    c.drawCentredString(width / 2, height - 6.1 * cm, "délivrée à")

    c.setFillColor(_VIOLET_DARK)
    name_size = _fit_font_size(c, learner_name, "Times-Bold", 28, content_width)
    c.setFont("Times-Bold", name_size)
    c.drawCentredString(width / 2, height - 7.6 * cm, learner_name)

    c.setFillColor(_MUTED)
    c.setFont("Times-Italic", 13.5)
    c.drawCentredString(width / 2, height - 9.0 * cm, "pour avoir terminé et réussi l'examen du cours")

    c.setFillColor(_INK)
    title_size = _fit_font_size(c, course_title, "Times-Bold", 17, content_width)
    c.setFont("Times-Bold", title_size)
    c.drawCentredString(width / 2, height - 10.2 * cm, course_title)

    _draw_seal(c, width / 2, height - 12.6 * cm)

    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 9.5)
    c.drawString(_INNER_MARGIN + 0.3 * cm, _INNER_MARGIN + 0.35 * cm, f"Délivrée le {issued_at}")
    c.drawRightString(
        width - _INNER_MARGIN - 0.3 * cm,
        _INNER_MARGIN + 0.35 * cm,
        f"Vérifier : {verify_url} — certificat n° {certificate_id}",
    )

    c.showPage()
    c.save()
    return buffer.getvalue()
