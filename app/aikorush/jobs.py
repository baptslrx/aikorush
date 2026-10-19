"""Le traitement : copie renommée, proxys ProRes, audio séparé, silences (marqueurs + rapport)."""
from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import quoteattr

from .probe import Clip, fmt_duration

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class Options:
    copy: bool = True
    proxy: bool = True
    audio: bool = True
    silences: bool = True
    threshold_db: int = -35
    min_silence: float = 1.0


@dataclass
class Result:
    done: int = 0
    silences: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    out_dir: Path | None = None


class Cancelled(Exception):
    pass


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def plan_steps(clips: list[Clip], opt: Options) -> list[tuple[Clip, str]]:
    steps: list[tuple[Clip, str]] = []
    for c in clips:
        if not c.selected:
            continue
        if opt.copy:
            steps.append((c, "copy"))
        if opt.proxy and c.kind == "video":
            steps.append((c, "proxy"))
        if opt.audio and c.kind == "video" and c.has_audio:
            steps.append((c, "audio"))
        if opt.silences and c.has_audio:
            steps.append((c, "silence"))
    return steps


def needed_space(clips: list[Clip], opt: Options) -> int:
    total = 0
    for c in clips:
        if not c.selected:
            continue
        if opt.copy:
            total += c.size
        if opt.proxy and c.kind == "video":
            # ProRes Proxy ≈ 45 Mb/s en 1080p25
            total += int(c.duration * 45_000_000 / 8 * (min(c.height or 1080, 1080) / 1080) ** 2)
        if opt.audio and c.kind == "video" and c.has_audio:
            total += int(c.duration * 48_000 * 3 * max(1, c.audio_channels))
    return total


class Runner:
    """Exécute les étapes dans un fil séparé ; `progress(fraction, texte)` et `finished(Result)`."""

    def __init__(self, clips: list[Clip], opt: Options, out_dir: Path,
                 progress: Callable[[float, str], None], finished: Callable[[Result], None]):
        self.clips = [c for c in clips if c.selected]
        self.opt = opt
        self.out_dir = out_dir
        self.progress = progress
        self.finished = finished
        self._cancel = threading.Event()
        self._proc: subprocess.Popen | None = None
        self.result = Result(out_dir=out_dir)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self):
        self._cancel.set()
        if self._proc and self._proc.poll() is None:
            self._proc.kill()

    # ------------------------------------------------------------ organisation

    def rush_path(self, c: Clip) -> Path:
        if self.opt.copy:
            return self.out_dir / "Rushs" / (c.new_name + c.path.suffix)
        return c.path

    def base_name(self, c: Clip) -> str:
        return c.new_name if self.opt.copy else c.path.stem

    def proxy_path(self, c: Clip) -> Path:
        # Resolve relie tout seul les proxys rangés dans un dossier « Proxy » à côté des rushs
        return self.rush_path(c).parent / "Proxy" / (self.base_name(c) + ".mov")

    def _run(self):
        steps = plan_steps(self.clips, self.opt)
        total = max(1, len(steps))
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            for i, (clip, step) in enumerate(steps):
                if self._cancel.is_set():
                    raise Cancelled
                label = {"copy": "Copie", "proxy": "Proxy", "audio": "Audio", "silence": "Silences"}[step]
                name = self.base_name(clip)

                def sub(f: float, i=i, label=label, name=name):
                    self.progress((i + max(0.0, min(1.0, f))) / total, f"{label} · {name}")

                sub(0)
                try:
                    getattr(self, f"_step_{step}")(clip, sub)
                except Cancelled:
                    raise
                except Exception as e:  # une erreur sur un fichier n'arrête pas les autres
                    self.result.errors.append(f"{clip.path.name} ({label}) : {e}")
                if step == plan_steps([clip], self.opt)[-1][1]:
                    self.result.done += 1
            if self.opt.silences:
                self._write_reports()
            self._write_readme()
            self.progress(1.0, "Terminé")
        except Cancelled:
            self.result.errors.insert(0, "Annulé")
        except Exception as e:
            self.result.errors.insert(0, f"Erreur : {e}")
        self.finished(self.result)

    # ------------------------------------------------------------ étapes

    def _step_copy(self, c: Clip, sub):
        dest = self.rush_path(c)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size == c.size:
            return  # déjà copié (relance après interruption)
        tmp = dest.with_name(dest.name + ".partial")
        size = max(1, c.size)
        copied = 0
        with open(c.path, "rb") as src, open(tmp, "wb") as out:
            while True:
                if self._cancel.is_set():
                    out.close()
                    tmp.unlink(missing_ok=True)
                    raise Cancelled
                chunk = src.read(8 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                sub(copied / size)
        shutil.copystat(c.path, tmp)
        if tmp.stat().st_size != c.size:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("copie incomplète")
        os.replace(tmp, dest)

    def _step_proxy(self, c: Clip, sub):
        dest = self.proxy_path(c)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._ffmpeg(["-i", str(self.rush_path(c)), "-map", "0:v:0", "-map", "0:a?",
                      "-vf", "scale=-2:'min(1080,ih)'", "-c:v", "prores_ks", "-profile:v", "0",
                      "-vendor", "apl0", "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s16le",
                      "-map_metadata", "0", "-map_chapters", "-1"],
                     dest, c.duration, sub)

    def _step_audio(self, c: Clip, sub):
        folder = self.out_dir / "Audio"
        folder.mkdir(parents=True, exist_ok=True)
        src = str(self.rush_path(c))
        for k in range(c.audio_streams):
            suffix = "" if c.audio_streams == 1 else f"_piste{k + 1}"
            dest = folder / f"{self.base_name(c)}{suffix}.wav"
            self._ffmpeg(["-i", src, "-map", f"0:a:{k}", "-vn", "-c:a", "pcm_s24le", "-ar", "48000"],
                         dest, c.duration, lambda f, k=k: sub((k + f) / c.audio_streams))

    def _step_silence(self, c: Clip, sub):
        threshold, minimum = self.opt.threshold_db, self.opt.min_silence
        cmd = [ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(self.rush_path(c)), "-map", "0:a:0",
               "-af", f"silencedetect=noise={threshold}dB:d={minimum}", "-progress", "pipe:2",
               "-f", "null", "-"]
        out = self._exec(cmd, c.duration, sub)
        found: list[tuple[float, float]] = []
        start = None
        for line in out.splitlines():
            m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
            if m:
                start = max(0.0, float(m.group(1)))
                continue
            m = re.search(r"silence_end:\s*([\d.]+)", line)
            if m and start is not None:
                found.append((start, float(m.group(1))))
                start = None
        if start is not None and c.duration > start:
            found.append((start, c.duration))
        self.result.silences[self.base_name(c)] = found

    # ------------------------------------------------------------ ffmpeg

    def _ffmpeg(self, args: list[str], dest: Path, duration: float, sub):
        tmp = dest.with_name(dest.stem + ".partial" + dest.suffix)
        cmd = [ffmpeg_exe(), "-hide_banner", "-nostats", "-y", *args, "-progress", "pipe:2", str(tmp)]
        try:
            self._exec(cmd, duration, sub)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, dest)

    def _exec(self, cmd: list[str], duration: float, sub) -> str:
        """Lance ffmpeg, suit la progression, renvoie sa sortie d'erreur (utile pour silencedetect)."""
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                      encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        lines: list[str] = []
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    t = int(line.split("=", 1)[1]) / 1_000_000
                    if duration > 0:
                        sub(t / duration)
                except ValueError:
                    pass
            elif not re.match(r"^[a-z_]+=", line):
                lines.append(line)
        code = self._proc.wait()
        if self._cancel.is_set():
            raise Cancelled
        if code != 0:
            err = [l.strip() for l in lines if l.strip()]
            raise RuntimeError(err[-1] if err else f"ffmpeg a échoué ({code})")
        sub(1.0)
        return "".join(lines)

    # ------------------------------------------------------------ rapports

    def _write_reports(self):
        clips = [c for c in self.clips if self.base_name(c) in self.result.silences]
        if not clips:
            return
        folder = self.out_dir / "Silences"
        folder.mkdir(parents=True, exist_ok=True)

        # Tableau (s'ouvre dans Excel / Numbers / Sheets — séparateur « ; » pour Excel en français)
        with open(folder / "Silences.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Fichier", "Début", "Fin", "Durée (s)"])
            for c in clips:
                for a, b in self.result.silences[self.base_name(c)]:
                    w.writerow([self.base_name(c), tc(a), tc(b), f"{b - a:.1f}".replace(".", ",")])

        # Rapport lisible
        lines = ["AikoRush — passages silencieux",
                 f"Seuil : {self.opt.threshold_db} dB, durée minimale : {self.opt.min_silence:g} s", ""]
        for c in clips:
            sil = self.result.silences[self.base_name(c)]
            total = sum(b - a for a, b in sil)
            pct = 100 * total / c.duration if c.duration else 0
            lines.append(f"{self.base_name(c)} — {fmt_duration(c.duration)}, {len(sil)} silence(s), "
                         f"{fmt_duration(total)} de silence ({pct:.0f} %)")
            for a, b in sil:
                lines.append(f"    {tc(a)} → {tc(b)}  ({b - a:.1f} s)")
            lines.append("")
        (folder / "Rapport.txt").write_text("\n".join(lines), encoding="utf-8")

        # Timeline DaVinci Resolve avec un marqueur sur chaque silence
        (folder / "Timeline Resolve (marqueurs).fcpxml").write_text(self._fcpxml(clips), encoding="utf-8")

    def _fcpxml(self, clips: list[Clip]) -> str:
        formats: dict[tuple, str] = {}
        res, spine = [], []
        offset = Fraction(0)
        seq_format = None
        for n, c in enumerate(clips, 1):
            fps = c.fps if c.kind == "video" else Fraction(25)
            fd = Fraction(1) / fps
            key = (fps, c.width or 1920, c.height or 1080)
            if key not in formats:
                fid = f"r{len(formats) + 1}"
                formats[key] = fid
                res.append(f'    <format id="{fid}" frameDuration="{rt(fd)}" width="{key[1]}" height="{key[2]}"/>')
            fid = formats[key]
            seq_format = seq_format or fid
            dur = snap(Fraction(c.duration).limit_denominator(100000), fd)
            src = self.rush_path(c).resolve().as_uri()
            name = quoteattr(self.base_name(c))
            has_v = "1" if c.kind == "video" else "0"
            res.append(f'    <asset id="a{n}" name={name} start="0s" duration="{rt(dur)}" hasVideo="{has_v}" '
                       f'hasAudio="{1 if c.has_audio else 0}" format="{fid}" audioSources="1" '
                       f'audioChannels="{c.audio_channels}" audioRate="48000">\n'
                       f'      <media-rep kind="original-media" src={quoteattr(src)}/>\n    </asset>')
            markers = []
            for a, b in self.result.silences.get(self.base_name(c), []):
                start = snap(Fraction(a).limit_denominator(100000), fd)
                length = max(fd, snap(Fraction(b - a).limit_denominator(100000), fd))
                markers.append(f'        <marker start="{rt(start)}" duration="{rt(length)}" '
                               f'value={quoteattr(f"Silence {b - a:.1f} s")}/>')
            body = ("\n" + "\n".join(markers) + "\n      ") if markers else ""
            spine.append(f'      <asset-clip ref="a{n}" name={name} offset="{rt(offset)}" start="0s" '
                         f'duration="{rt(dur)}" format="{fid}" tcFormat="NDF">{body}</asset-clip>')
            offset += dur
        title = quoteattr(f"AikoRush — {self.out_dir.name}")
        return "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<!DOCTYPE fcpxml>",
            '<fcpxml version="1.9">',
            "  <resources>", *res, "  </resources>",
            '  <library>', f'   <event name={title}>', f'    <project name={title}>',
            f'     <sequence format="{seq_format}" duration="{rt(offset)}" tcStart="0s" tcFormat="NDF">',
            "      <spine>",
            *spine,
            "      </spine>", "     </sequence>", "    </project>", "   </event>", "  </library>",
            "</fcpxml>", ""])

    def _write_readme(self):
        lines = ["AikoRush — dossier préparé", ""]
        if self.opt.copy:
            lines += ["• Rushs/ : tes rushs copiés et renommés (date_caméra_numéro). Les originaux n'ont pas bougé."]
        if self.opt.proxy:
            lines += ["• Rushs/Proxy/ : les proxys ProRes Proxy, même nom que les rushs.",
                      "  DaVinci Resolve les relie tout seul : importe le dossier Rushs, puis dans le menu",
                      "  Playback → Proxy Handling → Prefer Proxies. (Si besoin : clic droit sur les clips →",
                      "  Link Proxy Media… → choisir le dossier Proxy.)"]
        if self.opt.audio:
            lines += ["• Audio/ : l'audio de chaque rush en WAV 48 kHz / 24 bits."]
        if self.opt.silences:
            lines += ["• Silences/Silences.csv : la liste des silences (s'ouvre dans Excel).",
                      "• Silences/Rapport.txt : le même résumé, fichier par fichier.",
                      "• Silences/Timeline Resolve (marqueurs).fcpxml : dans Resolve, File → Import → Timeline…",
                      "  → choisir ce fichier. Tu obtiens une timeline avec tous les rushs et un marqueur",
                      "  sur chaque passage silencieux."]
        if self.result.errors:
            lines += ["", "Problèmes rencontrés :"] + [f"  - {e}" for e in self.result.errors]
        (self.out_dir / "Lisez-moi.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tc(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def snap(t: Fraction, frame: Fraction) -> Fraction:
    """Arrondit au début d'image le plus proche (FCPXML l'exige)."""
    return Fraction(round(t / frame)) * frame


def rt(t: Fraction) -> str:
    t = Fraction(t)
    return f"{t.numerator}s" if t.denominator == 1 else f"{t.numerator}/{t.denominator}s"
