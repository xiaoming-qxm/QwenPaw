#!/usr/bin/env bash
# Build a full wheel package including the latest console frontend.
# Run from repo root: bash scripts/wheel_build.sh
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DIST_DIR="${DIST_DIR:-$REPO_ROOT/dist}"
case "$DIST_DIR" in
  /*) ;;
  *)
    echo "[wheel_build] DIST_DIR must be absolute" >&2
    exit 2
    ;;
esac

CONSOLE_DIR="$REPO_ROOT/console"
CONSOLE_DEST="$REPO_ROOT/src/qwenpaw/console"

mkdir -p "$DIST_DIR"
DIST_DIR="$(cd "$DIST_DIR" && pwd -P)"
case "$DIST_DIR" in
  /|"$REPO_ROOT")
    echo "[wheel_build] DIST_DIR points at an unsafe output directory" >&2
    exit 2
    ;;
  "$REPO_ROOT"/*)
    if [ "$DIST_DIR" != "$REPO_ROOT/dist" ]; then
      echo "[wheel_build] DIST_DIR must not overlap repository sources" >&2
      exit 2
    fi
    ;;
esac

echo "[wheel_build] Building console frontend..."
(cd "$CONSOLE_DIR" && npm ci)
(cd "$CONSOLE_DIR" && npm run build)

echo "[wheel_build] Copying console/dist/* -> src/qwenpaw/console/..."
rm -rf "$CONSOLE_DEST"/*

mkdir -p "$CONSOLE_DEST"
cp -R "$CONSOLE_DIR/dist/"* "$CONSOLE_DEST/"

echo "[wheel_build] Bundling website docs into package..."
DOCS_SRC="$REPO_ROOT/website/public/docs"
DOCS_DEST="$REPO_ROOT/src/qwenpaw/docs"
rm -rf "$DOCS_DEST"
mkdir -p "$DOCS_DEST"
cp "$DOCS_SRC/"*.md "$DOCS_DEST/"

echo "[wheel_build] Building wheel + sdist..."
python3 -m pip install --quiet build
rm -rf "$DIST_DIR"/*
python3 -m build --outdir "$DIST_DIR" .

echo "[wheel_build] Done. Wheel(s) in: $DIST_DIR/"
