"""Analyse des rushs : type, durée, cadence, date de tournage et caméra."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mxf", ".m4v", ".mts", ".m2ts", ".avi", ".mkv", ".insv", ".3gp"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aif", ".aiff", ".flac", ".bwf"}
SKIP_DIRS = {"proxy", "proxies", "thmbnl", "thumbnails", ".trash", "__macosx", "cacheclip", "optimized media"}

SONY_MODELS = {
    "ILCE-7SM3": "A7SIII", "ILCE-7SM2": "A7SII", "ILCE-7M4": "A7IV", "ILCE-7M3": "A7III", "ILCE-7CM2": "A7CII",
    "ILCE-7C": "A7C", "ILCE-7RM5": "A7RV", "ILCE-7RM4": "A7RIV", "ILCE-1": "A1", "ILCE-9M3": "A9III",
    "ILCE-6400": "A6400", "ILCE-6600": "A6600", "ILCE-6700": "A6700", "ILME-FX3": "FX3", "ILME-FX30": "FX30",
    "ILME-FX6": "FX6", "ZV-E10": "ZVE10", "ZV-E10M2": "ZVE10II", "ZV-E1": "ZVE1", "ZV-1": "ZV1",
}


@dataclass
class Clip:
    path: Path
    kind: str                       # "video" ou "audio"
    duration: float = 0.0           # secondes
    fps: Fraction = Fraction(25)
    width: int = 0
    height: int = 0
    audio_streams: int = 0
    audio_channels: int = 2
    created: datetime = field(default_factory=datetime.now)
    camera: str = "CAM"
    new_name: str = ""              # sans extension
    selected: bool = True
    error: str = ""
    tags: dict = field(default_factory=dict, repr=False)

    @property
    def has_audio(self) -> bool:
        return self.audio_streams > 0

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


def find_media(paths: list[Path]) -> list[Path]:
    """Tous les fichiers vidéo/audio des dossiers glissés (sous-dossiers compris)."""
    found: list[Path] = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if any(part.lower() in SKIP_DIRS for part in f.relative_to(p).parts[:-1]):
                    continue
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS:
                    found.append(f)
        elif p.is_file() and p.suffix.lower() in VIDEO_EXTS | AUDIO_EXTS:
            found.append(p)
    return found


def clean_camera(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "", name or "")
    return name[:14] or "CAM"


def _sony_xml(path: Path) -> tuple[str | None, datetime | None]:
    for cand in (path.with_name(path.stem + "M01.XML"), path.with_name(path.stem + "M01.xml")):
        if cand.exists():
            try:
                root = ET.parse(cand).getroot()
                model = created = None
                for el in root.iter():
                    tag = el.tag.split("}")[-1]
                    if tag == "Device":
                        model = el.attrib.get("modelName")
                    elif tag == "CreationDate":
                        v = el.attrib.get("value", "")
                        try:
                            created = datetime.fromisoformat(v)
                        except ValueError:
                            pass
                if model:
                    model = SONY_MODELS.get(model, model)
                return model, created
            except Exception:
                return None, None
    return None, None


def _camera_from_tags(tags: dict[str, str], path: Path) -> str | None:
    t = {k.lower(): str(v) for k, v in tags.items()}
    for key in ("com.apple.quicktime.model", "model", "com.android.model", "device_model",
                "com.blackmagic-design.camera.model"):
        if t.get(key):
            make = t.get("com.apple.quicktime.make") or t.get("make") or t.get("com.android.manufacturer") or ""
            model = t[key]
            if make and make.lower() not in model.lower() and make.lower() not in ("apple",):
                model = f"{make} {model}"
            return SONY_MODELS.get(model, model)
    blob = " ".join(t.values()).lower()
    if "gopro" in blob or re.match(r"G[HXL]\d{6}", path.stem, re.I):
        return "GoPro"
    if "dji" in blob or path.stem.upper().startswith("DJI_"):
        return "DJI"
    if "insta360" in blob or path.suffix.lower() == ".insv":
        return "Insta360"
    if "zoom" in blob or re.match(r"ZOOM\d{4}", path.stem, re.I):
        return "ZOOM"
    if "blackmagic" in blob:
        return "BMPCC"
    if "canon" in blob:
        return "Canon"
    if "panasonic" in blob or "lumix" in blob:
        return "Lumix"
    return None


def _parse_date(v: str | None) -> datetime | None:
    if not v:
        return None
    if ";" in v:  # valeur en double (« 2026-10-19T15:10:00.000000Z;2026-10-19T15:10:00Z »)
        for part in v.split(";"):
            d = _parse_date(part)
            if d:
                return d
        return None
    v = v.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"):
        try:
            d = datetime.fromisoformat(v) if fmt is None else datetime.strptime(v[:19], fmt)
            if d.year < 2000:  # date « 1904 » ou « 1970 » des appareils non réglés
                return None
            return d.astimezone() if d.tzinfo else d
        except ValueError:
            continue
    return None


def _is_cover(stream) -> bool:
    """Vraie piste vidéo ou simple image de couverture (pochette) ?"""
    try:
        return bool(int(stream.disposition) & 0x0400)  # AV_DISPOSITION_ATTACHED_PIC
    except Exception:
        return False


def probe(path: Path) -> Clip:
    import av

    kind = "audio" if path.suffix.lower() in AUDIO_EXTS else "video"
    clip = Clip(path=path, kind=kind)
    tags: dict[str, str] = {}
    try:
        with av.open(str(path)) as c:
            tags.update({k: v for k, v in (c.metadata or {}).items()})
            if c.duration:
                clip.duration = c.duration / 1_000_000
            video = None
            for s in c.streams:
                for k, v in (s.metadata or {}).items():
                    tags.setdefault(k, v)
                if s.type == "video" and video is None and not _is_cover(s):
                    video = s
                elif s.type == "audio":
                    clip.audio_streams += 1
                    try:
                        clip.audio_channels = s.codec_context.channels or clip.audio_channels
                    except Exception:
                        pass
            if video is not None and kind == "video":
                rate = video.average_rate or video.guessed_rate or Fraction(25)
                clip.fps = Fraction(rate).limit_denominator(1001)
                clip.width = video.codec_context.width
                clip.height = video.codec_context.height
                if not clip.duration and video.duration and video.time_base:
                    clip.duration = float(video.duration * video.time_base)
            elif kind == "video":
                clip.kind = "audio"
    except Exception as e:  # fichier illisible : on le signale mais on ne bloque pas les autres
        clip.error = f"illisible ({type(e).__name__})"
        clip.selected = False

    clip.tags = tags
    sony_model, sony_date = _sony_xml(path)
    created = sony_date or _parse_date(tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate")
                                       or tags.get("date"))
    if created is None:
        try:
            created = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            created = datetime.now()
    clip.created = created.replace(tzinfo=None) if created.tzinfo else created
    clip.camera = clean_camera(sony_model or _camera_from_tags(tags, path) or
                               ("AUDIO" if clip.kind == "audio" else "CAM"))
    return clip


def assign_names(clips: list[Clip]) -> None:
    """2026-10-19_A7SIII_001 : numérotation par jour et par caméra, dans l'ordre de tournage."""
    counters: dict[tuple[str, str], int] = {}
    for c in sorted(clips, key=lambda c: (c.created, c.path.name)):
        if not c.selected:
            c.new_name = ""
            continue
        day = c.created.strftime("%Y-%m-%d")
        key = (day, c.camera)
        counters[key] = counters.get(key, 0) + 1
        c.new_name = f"{day}_{c.camera}_{counters[key]:03d}"


def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
