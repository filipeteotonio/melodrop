#!/bin/bash
# Double-click this file in Finder to start Melodrop.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

for tool in yt-dlp ffmpeg deno; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "Melodrop needs $tool. Install Homebrew first: https://brew.sh"
      read -r -p "Press Enter to close."
      exit 1
    fi
    echo "Installing $tool with Homebrew..."
    brew install "$tool" || exit 1
  fi
done

exec python3 -m melodrop "$@"
