#!/bin/sh
# Removes what install.sh added. Your settings and memories in ~/.config/alter_ego
# are kept; delete that folder too if you want them gone.
set -eu

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$DATA/alter-ego"
rm -f "$HOME/.local/bin/alter-ego" "$DATA/applications/alter-ego.desktop" "$DATA/icons/hicolor/256x256/apps/alter-ego.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
echo "Alter Ego is uninstalled. Your settings and memories are still in ~/.config/alter_ego."
