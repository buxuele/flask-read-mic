#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "这个入口给 macOS 用。Windows 请双击 just_run.bat。"
  exit 1
fi

exec ./client/just_run.sh
