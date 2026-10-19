"""Test automatique d'AikoRush : vrais clips générés, traitement complet, captures de la fenêtre."""
from __future__ import annotations

import faulthandler
import os
import subprocess
import time
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from aikorush import theme  # noqa: E402
from aikorush.jobs import Options, Runner, ffmpeg_exe  # noqa: E402
from aikorush.probe import assign_names, find_media, probe  # noqa: E402
from aikorush.ui import MainWindow  # noqa: E402

failures: list[str] = []


def check(cond: bool, what: str):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=Test::{what}")


def ff(*args):
    subprocess.run([ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True,
                   stdin=subprocess.DEVNULL, timeout=120)


def step(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def make_rushes(d: Path):
    card = d / "CARTE" / "PRIVATE" / "M4ROOT" / "CLIP"
    card.mkdir(parents=True)
    # Sony : la caméra et la date sont dans le XML à côté du fichier
    ff("-f", "lavfi", "-i", "testsrc=duration=6:size=1920x1080:rate=25", "-f", "lavfi",
       "-i", "sine=frequency=440:duration=6", "-af", "volume=enable='between(t,2,4)':volume=0", "-shortest",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(card / "C0001.MP4"))
    (card / "C0001M01.XML").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.00">'
        '<CreationDate value="2026-10-19T14:03:22+02:00"/><Device manufacturer="Sony" modelName="ILCE-7SM3"/>'
        '</NonRealTimeMeta>', encoding="utf-8")
    # iPhone : modèle dans les métadonnées QuickTime
    ff("-f", "lavfi", "-i", "testsrc2=duration=4:size=1280x720:rate=30", "-f", "lavfi",
       "-i", "sine=frequency=330:duration=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-movflags", "use_metadata_tags", "-metadata", "com.apple.quicktime.model=iPhone 15 Pro",
       "-metadata", "creation_time=2026-10-19T15:10:00Z", str(d / "IMG_4521.MOV"))
    # Enregistreur audio
    ff("-f", "lavfi", "-i", "sine=frequency=220:duration=5", "-af",
       "volume=enable='between(t,1,2.5)':volume=0", str(d / "ZOOM0001.WAV"))
    # Un aperçu à ignorer
    (d / "CARTE" / "PRIVATE" / "M4ROOT" / "THMBNL").mkdir()
    (d / "CARTE" / "PRIVATE" / "M4ROOT" / "THMBNL" / "C0001T01.JPG").write_bytes(b"x")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # Si quelque chose bloque, on affiche où (tous les fils) et on s'arrête au bout de 8 minutes
    faulthandler.dump_traceback_later(480, exit=True)
    step("démarrage")
    app = QApplication(sys.argv)
    step("Qt prêt")
    shots = ROOT / "screenshots"
    shots.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "Tournage NTO"
        src.mkdir()
        step("création des rushs de test")
        make_rushes(src)

        step("analyse")
        files = find_media([src])
        check(sorted(f.name for f in files) == ["C0001.MP4", "IMG_4521.MOV", "ZOOM0001.WAV"],
              f"fichiers trouvés : {[f.name for f in files]}")
        clips = [probe(f) for f in files]
        by = {c.path.name: c for c in clips}
        for c in clips:
            print(f"  {c.path.name}: {c.kind} {c.duration:.2f}s {c.fps} {c.width}x{c.height} "
                  f"caméra={c.camera} date={c.created} audio={c.audio_streams} {c.error}")
        check(by["C0001.MP4"].camera == "A7SIII", "caméra Sony reconnue (A7SIII)")
        check(by["C0001.MP4"].created.strftime("%Y-%m-%d %H:%M") == "2026-10-19 14:03", "date Sony lue dans le XML")
        check(by["IMG_4521.MOV"].camera.startswith("iPhone15"), "iPhone reconnu")
        check(by["ZOOM0001.WAV"].camera == "ZOOM" and by["ZOOM0001.WAV"].kind == "audio", "enregistreur Zoom reconnu")
        check(abs(by["C0001.MP4"].duration - 6) < 0.2, "durée lue")
        assign_names(clips)
        check(by["C0001.MP4"].new_name == "2026-10-19_A7SIII_001", f"nom : {by['C0001.MP4'].new_name}")

        step("fenêtre")
        for dark in (True, False):
            theme.is_dark = lambda dark=dark: dark
            step(f"fenêtre {'sombre' if dark else 'claire'}")
            w = MainWindow()
            w.apply_theme()
            w.out_dir = Path(tmp) / "Tournage NTO - AikoRush"
            w._scanned([probe(f) for f in files])
            w.resize(940, 600)
            w.show()
            app.processEvents()
            w.grab().save(str(shots / f"fenetre-{'sombre' if dark else 'clair'}.png"))
            if dark:
                w._set_state("running")
                w._progress(0.42, "Proxy · 2026-10-19_A7SIII_001")
                app.processEvents()
                w.grab().save(str(shots / "fenetre-en-cours.png"))
                w2 = MainWindow()
                w2.resize(940, 600)
                w2.show()
                app.processEvents()
                w2.grab().save(str(shots / "fenetre-vide.png"))
                w2.close()
            w.close()

        step("traitement")
        out = Path(tmp) / "Sortie"
        done = threading.Event()
        res = {}
        Runner(clips, Options(), out, lambda f, t: None, lambda r: (res.setdefault("r", r), done.set())).start()
        done.wait(600)
        r = res["r"]
        print("  erreurs :", r.errors)
        check(not r.errors, "aucune erreur")
        check((out / "Rushs" / "2026-10-19_A7SIII_001.MP4").exists(), "rush copié et renommé")
        check((out / "Rushs" / "2026-10-19_ZOOM_001.WAV").exists(), "audio Zoom copié et renommé")
        proxy = out / "Rushs" / "Proxy" / "2026-10-19_A7SIII_001.mov"
        check(proxy.exists(), "proxy créé dans Rushs/Proxy")
        if proxy.exists():
            import av

            with av.open(str(proxy)) as c:
                v = c.streams.video[0]
                print(f"  proxy : {v.codec_context.name} {v.codec_context.width}x{v.codec_context.height}")
                check(v.codec_context.name == "prores", "proxy en ProRes")
                check(v.codec_context.height == 1080, "proxy en 1080p maximum")
        check((out / "Audio" / "2026-10-19_A7SIII_001.wav").exists(), "audio séparé en WAV")
        sil = r.silences.get("2026-10-19_A7SIII_001", [])
        print("  silences Sony :", sil)
        check(len(sil) == 1 and abs(sil[0][0] - 2) < 0.2 and abs(sil[0][1] - 4) < 0.2, "silence repéré (2 s → 4 s)")
        check(len(r.silences.get("2026-10-19_ZOOM_001", [])) == 1, "silence repéré dans l'audio Zoom")
        fcp = out / "Silences" / "Timeline Resolve (marqueurs).fcpxml"
        check(fcp.exists(), "timeline Resolve créée")
        if fcp.exists():
            root = ET.parse(fcp).getroot()
            check(len(root.findall(".//marker")) >= 2, "marqueurs dans la timeline")
            check(len(root.findall(".//asset-clip")) == 3, "les 3 rushs dans la timeline")
        check((out / "Silences" / "Silences.csv").exists(), "tableau des silences")
        check((out / "Silences" / "Rapport.txt").exists(), "rapport")
        check((out / "Lisez-moi.txt").exists(), "Lisez-moi")
        check((src / "CARTE" / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001.MP4").exists(), "original intact")

    print("\nCaptures :", ", ".join(sorted(p.name for p in shots.glob("*.png"))))
    if failures:
        print("\nÉCHECS :\n" + "\n".join(failures))
        return 1
    print("\nTout est OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        tb = traceback.format_exc()
        print(tb)
        if os.environ.get("GITHUB_ACTIONS"):
            print("::error title=Erreur fatale::" + " | ".join(tb.strip().splitlines()[-6:]))
        sys.exit(1)
