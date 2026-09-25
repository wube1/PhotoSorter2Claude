"""Per-file analysis: hashing, EXIF (date, GPS, camera), thumbnails and paper-document detection."""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

try:  # HEIC/HEIF support (iPhone photos)
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - optional at runtime
    pass

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 250_000_000  # allow large panoramas, still guard against bombs

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
TAG_DATETIME = 306
TAG_MAKE = 271
TAG_MODEL = 272
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868

ANALYSIS_SIZE = 512


@dataclass
class MediaInfo:
    sha256: str
    taken_at: str | None
    taken_source: str
    lat: float | None
    lon: float | None
    width: int | None
    height: int | None
    camera: str | None
    doc_score: float | None
    thumb: bytes | None
    error: str | None = None


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _parse_exif_datetime(value: object) -> str | None:
    if not value:
        return None
    text = str(value).strip().strip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
        if dt.year < 1980:  # unset camera clocks
            return None
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    return None


def _to_float(value: object) -> float:
    try:
        return float(value)  # IFDRational supports float()
    except (TypeError, ValueError, ZeroDivisionError):
        num, den = value  # type: ignore[misc]
        return float(num) / float(den)


def _dms_to_deg(dms: object, ref: object) -> float | None:
    try:
        d, m, s = (_to_float(x) for x in dms)  # type: ignore[union-attr]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    deg = d + m / 60.0 + s / 3600.0
    if str(ref).upper().startswith(("S", "W")):
        deg = -deg
    return deg


def extract_exif(img: Image.Image) -> tuple[str | None, float | None, float | None, str | None]:
    """Return (taken_at, lat, lon, camera)."""
    try:
        exif = img.getexif()
    except Exception:
        return None, None, None, None
    if not exif:
        return None, None, None, None
    taken = None
    try:
        sub = exif.get_ifd(EXIF_IFD)
        taken = _parse_exif_datetime(sub.get(TAG_DATETIME_ORIGINAL)) or _parse_exif_datetime(
            sub.get(TAG_DATETIME_DIGITIZED)
        )
    except Exception:
        pass
    taken = taken or _parse_exif_datetime(exif.get(TAG_DATETIME))

    lat = lon = None
    try:
        gps = exif.get_ifd(GPS_IFD)
        if gps and 2 in gps and 4 in gps:
            lat = _dms_to_deg(gps[2], gps.get(1, "N"))
            lon = _dms_to_deg(gps[4], gps.get(3, "E"))
            if lat is not None and lon is not None:
                if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 1e-6 and abs(lon) < 1e-6):
                    lat = lon = None
    except Exception:
        lat = lon = None

    make = str(exif.get(TAG_MAKE) or "").strip().strip("\x00")
    model = str(exif.get(TAG_MODEL) or "").strip().strip("\x00")
    camera = model if make and model.lower().startswith(make.lower()) else " ".join(p for p in (make, model) if p)
    return taken, lat, lon, camera or None


def _ramp(value: float, lo: float, hi: float) -> float:
    if value <= lo:
        return 0.0
    if value >= hi:
        return 1.0
    return (value - lo) / (hi - lo)


def _document_features(img: Image.Image) -> float:
    hsv = img.convert("HSV")
    _, sat, val = hsv.split()
    total = img.width * img.height
    if total == 0:
        return 0.0
    sat_hist = sat.histogram()
    mean_sat = ImageStat.Stat(sat).mean[0]

    paper = _paper_mask(sat, val)
    paper_frac = paper.histogram()[255] / total

    gray = img.convert("L")
    g_hist = gray.histogram()
    # ink threshold relative to the paper brightness (80th percentile), so slightly blurry
    # or dim photos of a page still count their grey-ish text as ink
    acc, paper_level = 0, 255
    for level, count in enumerate(g_hist):
        acc += count
        if acc >= total * 0.8:
            paper_level = level
            break
    ink_level = max(60, min(120, int(paper_level * 0.62)))
    ink_frac = sum(g_hist[:ink_level]) / total

    edges = gray.filter(ImageFilter.FIND_EDGES)
    e_hist = edges.histogram()
    edge_frac = sum(e_hist[35:]) / total

    lowsat_frac = sum(sat_hist[:50]) / total
    # text = thin strokes: nearly every ink pixel sits on an edge. Solid dark shapes
    # (trees in snow, a car tyre) have few edge pixels per ink pixel.
    # (FIND_EDGES responds on the bright side of a stroke, so count edges *next to* ink)
    near_ink = gray.point(lambda v: 255 if v < ink_level else 0).filter(ImageFilter.MaxFilter(3))
    strong_edges = edges.point(lambda v: 255 if v > 35 else 0)
    ink_edges = Image.composite(strong_edges, Image.new("L", gray.size, 0), near_ink)
    ink_edge_frac = ink_edges.histogram()[255] / max(1, sum(g_hist[:ink_level]))

    s_paper = _ramp(paper_frac, 0.30, 0.62)
    s_edges = _ramp(edge_frac, 0.025, 0.09)
    s_colour = 1.0 - _ramp(mean_sat, 40, 95)
    s_ink = _ramp(ink_frac, 0.004, 0.03) * (1.0 - _ramp(ink_frac, 0.30, 0.50))
    s_lowsat = _ramp(lowsat_frac, 0.55, 0.85)
    s_stroke = _ramp(ink_edge_frac, 0.15, 0.35)
    parts = [(s_paper, 0.25), (s_edges, 0.2), (s_colour, 0.1), (s_ink, 0.15), (s_lowsat, 0.1), (s_stroke, 0.2)]
    score = 1.0
    for value, weight in parts:
        score *= max(value, 1e-3) ** weight
    return score


def _paper_mask(sat: Image.Image, val: Image.Image) -> Image.Image:
    """White where a pixel is bright and nearly colourless (paper)."""
    low_sat = sat.point(lambda s: 255 if s < 50 else 0)
    bright = val.point(lambda v: 255 if v > 25 else 0)
    return Image.composite(low_sat, Image.new("L", sat.size, 0), bright)


def document_score(rgb: Image.Image) -> float:
    """Heuristic 0..1: how much this image looks like a photo/scan of a paper document.

    Paper documents are dominated by bright, colourless pixels (the paper) with a moderate
    amount of dark ink arranged in many small, sharp strokes (text) -> high edge density.
    The page is usually photographed on a table, so the same features are also measured
    inside the bounding box of the largest paper-like region.
    """
    img = rgb.copy()
    img.thumbnail((ANALYSIS_SIZE, ANALYSIS_SIZE))
    if img.width < 8 or img.height < 8:
        return 0.0
    whole = _document_features(img)

    hsv = img.convert("HSV")
    _, sat, val = hsv.split()
    # remove specks/text holes so the bbox follows the sheet, not stray bright pixels
    mask = _paper_mask(sat, val).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(9))
    bbox = mask.getbbox()
    cropped = 0.0
    if bbox:
        x0, y0, x1, y1 = bbox
        coverage = (x1 - x0) * (y1 - y0) / (img.width * img.height)
        if coverage < 0.97 and (x1 - x0) > 16 and (y1 - y0) > 16:
            cropped = _document_features(img.crop(bbox)) * _ramp(coverage, 0.12, 0.3)
    return round(max(whole, cropped), 3)


def make_jpeg_preview(path: Path, size: int) -> bytes:
    with Image.open(path) as img:
        if img.format == "JPEG":
            img.draft("RGB", (size, size))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        return buf.getvalue()


def analyze(path: Path, thumb_size: int, detect_documents: bool) -> MediaInfo:
    """Full analysis of one file. Never raises: errors are returned in MediaInfo.error."""
    try:
        digest = sha256_file(path)
    except OSError as exc:
        return MediaInfo("", None, "mtime", None, None, None, None, None, None, None, error=f"read failed: {exc}")

    taken = lat = lon = camera = None
    width = height = None
    doc = None
    thumb = None
    error = None
    try:
        with Image.open(path) as img:
            width, height = img.size
            taken, lat, lon, camera = extract_exif(img)
            if img.format == "JPEG":
                # decode at reduced resolution: much faster and ~1/16 of the memory
                img.draft("RGB", (max(thumb_size, ANALYSIS_SIZE) * 2, max(thumb_size, ANALYSIS_SIZE) * 2))
            work = ImageOps.exif_transpose(img)
            work = work.convert("RGB")
            work.thumbnail((ANALYSIS_SIZE * 2, ANALYSIS_SIZE * 2))
            if detect_documents:
                doc = document_score(work)
            thumb_img = work.copy()
            thumb_img.thumbnail((thumb_size, thumb_size), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            thumb_img.save(buf, "WEBP", quality=78, method=4)
            thumb = buf.getvalue()
            if img.getexif().get(0x0112, 1) in (5, 6, 7, 8):  # rotated 90°: report displayed size
                width, height = height, width
    except Exception as exc:  # corrupt / unsupported file
        error = f"cannot read image: {exc.__class__.__name__}: {exc}"
        log.warning("Cannot analyse %s: %s", path, exc)

    source = "exif"
    if not taken:
        source = "mtime"
        try:
            taken = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        except OSError:
            taken = None
    return MediaInfo(digest, taken, source, lat, lon, width, height, camera, doc, thumb, error)
