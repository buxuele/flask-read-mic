#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"

if ! ls /opt/homebrew/lib/libportaudio*.dylib >/dev/null 2>&1 && ! ls /usr/local/lib/libportaudio*.dylib >/dev/null 2>&1; then
  echo "缺少 portaudio，先执行：brew install portaudio"
  exit 1
fi

PYTHON=/opt/homebrew/bin/python3.14
[[ -x $PYTHON ]] || PYTHON=$(command -v python3)

if [[ ! -x .venv/bin/python ]]; then
  $PYTHON -m venv .venv
fi

HASH=$(shasum -a 256 requirements.txt | awk '{print $1}')
if [[ ! -f .venv/.reqhash || "$(cat .venv/.reqhash)" != "$HASH" ]]; then
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
  echo "$HASH" > .venv/.reqhash
fi

if [[ ! -f .env ]]; then
  echo "缺少 .env，先执行：cp .env.example .env，再填入 ASR_URL 与 ASR_KEY"
  exit 1
fi

mkdir -p logs
exec .venv/bin/python src/app.py
