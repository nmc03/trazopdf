"""OCR without Qt: ``ocr_file`` for batches, plus page straightening (orientation and skew).

Everything runs locally with the bundled Tesseract; nothing touches the network.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz

from .lang import _

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
MAX_SKEW = 10.0          # degrees searched on each side
DETECTION_DPI = 100      # resolution of the skew search (pure Python: keep it small)
MIN_DARK_PIXELS = 200    # below this the page has no text to measure


@dataclass
class Report:
    """Outcome of ``ocr_file``."""
    path_in: str
    path_out: str
    languages: str
    deskew: bool
    pages: int = 0               # pages recognized
    skipped: int = 0             # pages that already had a text layer
    words: int = 0               # words added
    skew: dict = field(default_factory=dict)       # page index -> degrees corrected
    rotation: dict = field(default_factory=dict)   # page index -> degrees turned (90 steps)


def available_languages(tessdata=None):
    """Language codes with a model in the bundled tessdata folder (osd excluded)."""
    folder = Path(tessdata) if tessdata else _bundled_tessdata()
    return sorted(p.name.removesuffix(".traineddata") for p in folder.glob("*.traineddata") if p.name != "osd.traineddata")


def _bundled_tessdata():
    import sys
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets" / "tessdata"


def normalize_languages(languages):
    """'spa+eng' or ['spa', 'eng'] -> 'spa+eng'; None -> let the engine choose."""
    if languages is None:
        return None
    codes = languages.split("+") if isinstance(languages, str) else list(languages)
    codes = [c.strip() for c in codes if c and c.strip()]
    if not codes or not all(re.fullmatch(r"[A-Za-z0-9_]+", c) for c in codes):
        raise ValueError(_("Elige al menos un idioma."))
    return "+".join(codes)


# ------------------------------------------------------------ straightening

def detect_skew(pixmap, max_angle=MAX_SKEW):
    """Skew of the text lines in degrees, positive when the text runs counter-clockwise.

    Projection-profile search: the angle whose horizontal projection of dark pixels
    is the most uneven (sharp text lines). Returns 0.0 when there is nothing to measure.
    """
    if pixmap.n != 1:
        pixmap = fitz.Pixmap(fitz.csGRAY, pixmap)
    width, height, data = pixmap.width, pixmap.height, pixmap.samples
    stride = pixmap.stride
    # Dark pixels: clearly below the page's typical background.
    histogram = [0] * 256
    for value in data[::7]:
        histogram[value] += 1
    total = sum(histogram)
    running, background = 0, 255
    for level in range(256):
        running += histogram[level]
        if running >= total * .5:
            background = level
            break
    threshold = background * .6
    points = []
    for y in range(height):
        row = data[y * stride:y * stride + width]
        for x, value in enumerate(row):
            if value < threshold:
                points.append((x, y))
    if len(points) < MIN_DARK_PIXELS:
        return 0.0
    if len(points) > 12000:
        step = len(points) // 12000 + 1
        points = points[::step]
    cx, cy = width / 2, height / 2
    centered = [(x - cx, y - cy) for x, y in points]

    def score(angle):
        sin, cos = math.sin(math.radians(angle)), math.cos(math.radians(angle))
        bins = {}
        for x, y in centered:
            key = int(y * cos + x * sin + height)   # y of the point after turning the page by -angle
            bins[key] = bins.get(key, 0) + 1
        return sum(count * count for count in bins.values())

    best, best_score = 0.0, score(0.0)
    angle = -max_angle
    while angle <= max_angle + 1e-9:
        value = score(angle)
        if value > best_score * 1.0001:
            best, best_score = angle, value
        angle += .5
    for fine in (.2, .05):
        centre = best
        for step in range(-5, 6):
            candidate = centre + step * fine
            value = score(candidate)
            if value > best_score:
                best, best_score = candidate, value
    # A tiny tilt is not worth resampling the page.
    return round(best, 2) if abs(best) >= .3 else 0.0


def parse_osd(text):
    """Degrees (0/90/180/270) the page must be turned clockwise to be upright, from tesseract --psm 0."""
    rotate = re.search(r"^Rotate:\s*(\d+)", text or "", re.M)
    confidence = re.search(r"^Orientation confidence:\s*([\d.]+)", text or "", re.M)
    if not rotate or (confidence and float(confidence.group(1)) < 2.0):
        return 0
    return int(rotate.group(1)) % 360


def straighten_matrix(page, matrix, run_osd, folder):
    """Matrix (page -> pixels) that also uprights and deskews the page.

    run_osd(image_path) runs ``tesseract --psm 0`` and returns a CompletedProcess.
    Returns (matrix, turn, skew): turn in degrees clockwise (multiples of 90) and
    skew in degrees as measured by detect_skew. Failures degrade to the plain matrix.
    """
    turn, skew = 0, 0.0
    low = fitz.Matrix(DETECTION_DPI / 72, DETECTION_DPI / 72)
    try:
        probe = Path(folder) / "orientation.png"
        page.get_pixmap(matrix=low, colorspace=fitz.csGRAY, alpha=False).save(probe)
        process = run_osd(probe)
        if not process.returncode:
            turn = parse_osd(process.stdout)
    except InterruptedError:
        raise
    except Exception:
        turn = 0
    upright = fitz.Matrix(matrix)
    if turn:
        upright = upright * fitz.Matrix(turn)
    try:
        skew = detect_skew(page.get_pixmap(matrix=low * fitz.Matrix(turn) if turn else low, colorspace=fitz.csGRAY, alpha=False))
    except Exception:
        skew = 0.0
    if skew:
        upright = upright * fitz.Matrix(skew)
    return upright, turn, skew


# -------------------------------------------------------------------- batch

def ocr_file(path_in, path_out, languages=None, deskew=False, progress=None, cancelled=None):
    """Make ``path_in`` (PDF or image) searchable and write it to ``path_out``.

    languages: 'spa+eng', a list of codes or None (Spanish and English when available).
    deskew: straighten the pages and detect their orientation before recognizing.
    progress(done, total) and cancelled() behave as in PDFEngine.ocr; cancelling raises
    InterruptedError and leaves no output file. Returns a Report.
    """
    from .engine import PDFEngine
    path_in, path_out = Path(path_in), Path(path_out)
    language = normalize_languages(languages)
    engine = PDFEngine()
    try:
        if path_in.suffix.lower() in IMAGE_SUFFIXES:
            engine.from_images([path_in])
        else:
            engine.open(path_in)
        engine.ocr(language, progress=progress, cancelled=cancelled, deskew=bool(deskew))
        stats = engine.ocr_stats
        skipped = engine.page_count - stats["pages"]
        data = engine._bytes()
        PDFEngine._atomic_write(path_out, data)
    finally:
        engine.dirty = False
        engine.close()
    return Report(str(path_in), str(path_out), language or "", bool(deskew), stats["pages"], skipped, stats["words"], dict(stats["skew"]), dict(stats["rotation"]))
