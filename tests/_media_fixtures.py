"""Générateurs de fichiers PNG/PDF minimaux mais valides, pour les tests d'upload — stdlib
uniquement (pas de dépendance à Pillow ou autre lib d'image), pas un fichier de test lui-même
(préfixé `_`, non collecté par pytest)."""

import struct
import zlib


def make_minimal_png(width: int = 4, height: int = 4, rgb: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """Construit un PNG RGB 8 bits valide (signature + IHDR/IDAT/IEND corrects), sans dépendance
    externe — suffisant pour passer une vraie validation de magic bytes et être décodé comme une
    vraie image (couleur unie, pas de texte)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8 bits/canal, couleur RGB
    raw_scanlines = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    idat = zlib.compress(raw_scanlines)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# Police 5x7 minimale (façon afficheur LED), juste assez de glyphes pour composer une courte
# tentative d'injection lisible par un modèle de vision — pas une vraie bibliothèque de rendu de
# texte, seulement ce qu'il faut pour ce test précis, sans dépendance externe (Pillow indisponible
# sur cette machine au moment d'écrire ce test, disque plein).
_FONT_5X7 = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def make_text_image_png(text: str, scale: int = 8) -> bytes:
    """Rend `text` (glyphes disponibles dans _FONT_5X7 uniquement) en pixels NOIRS sur fond BLANC
    dans un vrai PNG valide — du texte réellement dessiné pixel par pixel, pas une métadonnée, donc
    lisible par un modèle de vision comme n'importe quelle image contenant du texte."""
    glyphs = [_FONT_5X7[ch.upper()] for ch in text]
    rows, cols_per_glyph, gap = 7, 5, 1
    width = sum(cols_per_glyph + gap for _ in glyphs) - gap
    height = rows

    grid = [[0] * width for _ in range(height)]
    x_offset = 0
    for glyph in glyphs:
        for y, row in enumerate(glyph):
            for x, bit in enumerate(row):
                if bit == "1":
                    grid[y][x_offset + x] = 1
        x_offset += cols_per_glyph + gap

    scaled_width, scaled_height = width * scale, height * scale
    scanlines = bytearray()
    for y in range(scaled_height):
        scanlines.append(0)  # filtre "None"
        src_y = y // scale
        for x in range(scaled_width):
            src_x = x // scale
            on = grid[src_y][src_x] == 1
            scanlines.extend((0, 0, 0) if on else (255, 255, 255))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", scaled_width, scaled_height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(scanlines))
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def make_minimal_pdf(text_lines: list[str]) -> bytes:
    """Construit un PDF valide à une page avec du texte RÉEL et extractible (police Helvetica
    standard, syntaxe PDF écrite à la main) — pas une image de texte, du vrai texte PDF, sans
    dépendance externe."""
    content_lines = ["BT", "/F1 14 Tf", "50 700 Td"]
    for i, line in enumerate(text_lines):
        if i > 0:
            content_lines.append("0 -20 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"({escaped}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        b"5 0 obj\n<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream\nendobj\n",
    ]

    pdf = b"%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj
    xref_offset = len(pdf)
    pdf += b"xref\n0 %d\n" % (len(objects) + 1)
    pdf += b"0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode("ascii")
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref_offset)
    return pdf
