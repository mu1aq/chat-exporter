#!/bin/sh
# Install dependencies into a local .venv (Linux and macOS).
# After this finishes, run the tool with:  ./.venv/bin/python chat2file.py <share-url>
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if command -v python3 >/dev/null 2>&1; then
    PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    PYTHON=$(command -v python)
else
    echo "Python was not found. Install Python 3.10 or newer." >&2
    exit 127
fi

VENV="$PROJECT_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON" -m venv "$VENV"
fi
VENV_PY="$VENV/bin/python"

"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -e "$PROJECT_DIR[browser]"
"$VENV_PY" -m playwright install chromium

echo "Done. Run:  $VENV_PY $PROJECT_DIR/chat2file.py <share-url>"
