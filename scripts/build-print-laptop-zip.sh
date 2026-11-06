#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Builds dist/print-laptop.zip: everything the Windows print laptop needs to run the program.
#
# Usage: scripts/build-print-laptop-zip.sh
#
# Takes the program files and the filled-in .env from app/print_laptop/ (a symlinked .env is followed),
# and leaves out the sticker template (it lives on the laptop), printed_ids.txt and caches. The zip holds
# the .env's settings, so dist/ is git-ignored. Unzip it on the laptop, then run
# "py -3.14 -m pip install --only-binary=:all: -r requirements.txt" once in that folder.

set -euo pipefail

readonly ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly SOURCE="$ROOT/app/print_laptop"
readonly STAGE="$ROOT/dist/print-laptop"
readonly ZIP="$ROOT/dist/print-laptop.zip"
readonly FILES=(print_laptop.py printer.py queue_reader.py printed_ids.py requirements.txt .env.example start-print-laptop.bat)

# Prints an error to stderr and stops the script.
# Arguments:
#   $1 - the message
# Returns:
#   Never returns; exits with status 1.
fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

# Copies the program files and the real .env into a fresh staging folder and zips it.
# Arguments:
#   None.
# Returns:
#   0 after writing dist/print-laptop.zip and printing its contents.
main() {
  [[ -f "$SOURCE/.env" ]] || fail "missing $SOURCE/.env: copy .env.example to .env there and fill it in"
  rm -rf "$STAGE" "$ZIP"
  mkdir -p "$STAGE"
  local file
  for file in "${FILES[@]}"; do
    cp "$SOURCE/$file" "$STAGE/$file"
  done
  cp -L "$SOURCE/.env" "$STAGE/.env"
  (cd "$ROOT/dist" && zip -q -r "$ZIP" print-laptop)
  rm -rf "$STAGE"
  printf 'Built %s:\n' "$ZIP"
  unzip -l "$ZIP" | sed -n '4,$p' | sed '$d' | sed '$d'
}

main "$@"
