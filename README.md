# AikoRush

Glisse un dossier de rushs (carte SD, disque, dossier de tournage) : AikoRush les range et les prépare pour le montage. **Tes originaux ne sont jamais modifiés.**

Le thème s'adapte au système : fenêtre **noire** en mode sombre, **blanche** en mode clair, avec un accent **bleu clair**, comme AikoRoue et AikoPipette.

## Ce qu'il fait

| Option | Résultat (dans « *Ton dossier* - AikoRush ») |
|---|---|
| **Copier et renommer** | `Rushs/2026-10-19_A7SIII_001.MP4`, avec la date de tournage, la caméra et un numéro par jour et par caméra |
| **Proxys ProRes** | `Rushs/Proxy/2026-10-19_A7SIII_001.mov` en ProRes Proxy (1080p max). DaVinci Resolve les relie tout seul |
| **Audio séparé** | `Audio/2026-10-19_A7SIII_001.wav` en WAV 48 kHz / 24 bits (une piste par fichier si la caméra en enregistre plusieurs) |
| **Repérer les silences** | `Silences/Timeline Resolve (marqueurs).fcpxml` : une timeline avec tous les rushs et **un marqueur sur chaque silence** · `Silences.csv` et `Rapport.txt` : la liste des silences |

- **Caméra reconnue automatiquement** : Sony (A7SIII, FX3…), iPhone, GoPro, DJI, Insta360, Zoom, Blackmagic, Canon, Lumix. Double-clic dans la colonne « Caméra » pour la renommer : les noms se recalculent.
- **Réglages des silences** : seuil (−35 dB par défaut) et durée minimale (1 s par défaut).
- **Avant de lancer**, AikoRush vérifie qu'il y a assez de place sur le disque. Tu peux **annuler** à tout moment : ce qui est terminé est conservé.

### Dans DaVinci Resolve
1. Importe le dossier **Rushs**. Les proxys sont reliés automatiquement : *Playback → Proxy Handling → Prefer Proxies*.
2. *File → Import → Timeline…* → `Silences/Timeline Resolve (marqueurs).fcpxml` pour avoir les marqueurs de silence.

## Téléchargements

Chaque envoi sur `main` compile les trois versions. Pour publier : **Actions → Publier une version** (numéro de la compilation + version).

| Système | Fichier |
|---|---|
| Windows 10/11 | `AikoRush-Windows-Setup.exe` (ou la version portable) |
| Mac (Apple Silicon) | `AikoRush-Mac.zip` — au premier lancement : Réglages Système → Confidentialité et sécurité → Ouvrir quand même |
| Linux x86_64 | `AikoRush-Linux-x86_64.tar.gz` → `./installer.sh` |

## Code

`app/` (Python, Qt, PyAV, ffmpeg) — `python -m aikorush` · `app/tests/smoke.py` : test complet sur de vrais clips générés.
