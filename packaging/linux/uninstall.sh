#!/bin/sh
# Removes what install.sh added, then asks what else should go. Nothing is removed
# without a "y": your settings and memories in ~/.config/alter_ego are kept unless you
# say so, and Ollama is its own program that other apps may use.
#
# Run from a terminal to be asked. Without a terminal (a script), only the program is removed.
# ALTER_EGO_ASK=1 asks even without a terminal (the tests use it).
set -eu

DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${ALTER_EGO_DATA_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/alter_ego}"
SPEECH="${HF_HOME:-$HOME/.cache/huggingface}/hub"
FILES="$HOME/Documents/Alter Ego"
[ -d "$HOME/Documents" ] || FILES="$HOME/Alter Ego"
MODELS="${OLLAMA_MODELS:-$HOME/.ollama/models}"

rm -rf "$DATA/alter-ego"
rm -f "$HOME/.local/bin/alter-ego" "$DATA/applications/alter-ego.desktop" "$DATA/icons/hicolor/256x256/apps/alter-ego.png"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true
echo "Alter Ego is uninstalled."

if [ ! -t 0 ] && [ "${ALTER_EGO_ASK:-}" != "1" ]; then
    echo "Your settings and memories are still in $CONFIG."
    exit 0
fi

size() { du -sh "$@" 2>/dev/null | awk '{print $1}' | tail -n 1; }
speech_models() { ls -d "$SPEECH"/models--Systran--faster-whisper-* 2>/dev/null || true; }

ALL=no
yes_answer() {  # Reads one answer; true for y/yes. A stray carriage return (Windows line ends) is ignored.
    read -r answer || answer=""
    answer=$(printf '%s' "$answer" | tr -d '\r')
    case "$answer" in y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
}
ask() {  # ask "question": yes when the user answers y, or chose everything
    if [ "$ALL" = yes ]; then return 0; fi
    printf '%s [y/N] ' "$1"
    yes_answer
}

echo
echo "What else should go? Anything you don't say yes to is kept."
printf 'Everything below (memories, downloads, speech models, saved files, Ollama models)? [y/N] '
if yes_answer; then ALL=yes; fi

if [ -d "$CONFIG" ] && ask "My memories and settings in $CONFIG (except the downloads)?"; then
    find "$CONFIG" -mindepth 1 -maxdepth 1 ! -name voices ! -name gpu -exec rm -rf {} +
    echo "  removed"
fi
if [ -d "$CONFIG/voices" ] && ask "My voice files ($(size "$CONFIG/voices"))?"; then
    rm -rf "$CONFIG/voices" "$CONFIG/gpu"
    rmdir "$CONFIG" 2>/dev/null || true
    echo "  removed"
fi
if [ -n "$(speech_models)" ] && ask "My speech-recognition models ($(speech_models | xargs du -shc 2>/dev/null | tail -n 1 | awk '{print $1}'))?"; then
    speech_models | while read -r folder; do rm -rf "$folder"; done
    echo "  removed"
fi
if [ -d "$FILES" ] && ask "Files I saved for you in $FILES ($(size "$FILES"))?"; then
    rm -rf "$FILES"
    echo "  removed"
fi
if [ -d "$MODELS" ] && ask "Ollama's AI models in $MODELS, for every program that uses Ollama ($(size "$MODELS"))?"; then
    rm -rf "$MODELS"
    echo "  removed"
fi

if command -v ollama >/dev/null 2>&1; then
    echo
    echo "Ollama itself is still installed (it needs administrator rights to remove)."
    echo "To remove it: https://github.com/ollama/ollama/blob/main/docs/linux.md#uninstall"
fi
