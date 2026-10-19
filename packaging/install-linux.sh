#!/bin/bash
# Installe AikoRush pour l'utilisateur courant (pas besoin de sudo)
set -e
cd "$(dirname "$0")"
DEST="$HOME/.local/share/aikorush"
mkdir -p "$DEST" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
pkill -x AikoRush 2>/dev/null || true
rm -rf "$DEST/app"
cp -r AikoRush "$DEST/app"
cp AikoRush/_internal/assets/icon-256.png "$HOME/.local/share/icons/hicolor/256x256/apps/aikorush.png" 2>/dev/null || true
cat > "$HOME/.local/share/applications/aikorush.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=AikoRush
Comment=Préparation des rushs
Exec=$DEST/app/AikoRush
Icon=aikorush
Categories=Utility;
DESK
echo "✓ AikoRush installé. Lance-le depuis ton menu d'applications (ou : $DEST/app/AikoRush)"
if ! ldconfig -p 2>/dev/null | grep -q libxcb-cursor; then
  echo "ℹ Si l'appli ne démarre pas : sudo apt install libxcb-cursor0"
fi
nohup "$DEST/app/AikoRush" >/dev/null 2>&1 &
