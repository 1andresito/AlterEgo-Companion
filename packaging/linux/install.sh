#!/bin/sh
# Installs Alter Ego for the current user (no sudo): the program goes to
# ~/.local/share/alter-ego, a launcher to the applications menu, and an
# `alter-ego` command to ~/.local/bin. Run it from the unpacked download:
#
#     ./install.sh
#
# Settings and memories live in ~/.config/alter_ego and are kept on update or uninstall.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DATA/alter-ego"
BIN="$HOME/.local/bin"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor/256x256/apps"

if [ ! -x "$HERE/AlterEgo/AlterEgo" ]; then
    echo "Can't find AlterEgo/AlterEgo next to this script. Run it from the unpacked download." >&2
    exit 1
fi

echo "Installing Alter Ego to $DEST ..."
rm -rf "$DEST"
mkdir -p "$DEST" "$BIN" "$APPS" "$ICONS"
cp -a "$HERE/AlterEgo/." "$DEST/"
ln -sf "$DEST/AlterEgo" "$BIN/alter-ego"
cp "$HERE/alter-ego.png" "$ICONS/alter-ego.png"
sed "s|@EXEC@|$DEST/AlterEgo|g" "$HERE/alter-ego.desktop" > "$APPS/alter-ego.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Done. Start Alter Ego from your applications menu, or run: alter-ego"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "(Add $BIN to your PATH to use the alter-ego command in a terminal.)" ;;
esac
