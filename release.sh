#!/usr/bin/env bash
# Release: VERSION frissítése → deploy NAS-ra → git commit + tag + push.
# Verziószám: verzió.változat.javítás (pl. 1.2.9 → 1.2.10 → 1.2.11; a javítás növekszik, nem 1.3.0).
# Használat: ./release.sh <verzió> [commit üzenet...]
#   pl. ./release.sh 1.2.11
#   pl. ./release.sh 1.2.11 429 barátságos hibaüzenet
# Induláskor megkérdezi: „Fusson a PDF könyvtár teszt?” — ha y, futtatja a test_pdf_folder.py-t
# (pdf/ első 3 PDF alapbeállításokkal); ha a teszt hibázik, a release megszakad.
# Ha megadsz üzenetet, az lesz a commit (és tag) szövege; különben: "Bump VERSION to <verzió>".
# A NAS_USER, NAS_HOST, NAS_PATH a deploy-nas.sh env-jéből / alapértelmezettből jön.

set -e

if [ -z "${1:-}" ]; then
  echo "Használat: $0 <verzió> [commit üzenet...]"
  echo "  pl. $0 1.0.0"
  echo "  pl. $0 1.0.0 Modellválasztó és Groq limit megjelenítés"
  exit 1
fi

V="$1"
shift
COMMIT_MSG="$*"
if [ -z "$COMMIT_MSG" ]; then
  COMMIT_MSG="Bump VERSION to $V"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Fusson a PDF könyvtár teszt (pdf/ első 3 fájl alapbeállításokkal)? (y/N)"
read -r RUN_TEST
if [ "$RUN_TEST" = "y" ] || [ "$RUN_TEST" = "Y" ]; then
  if ! python test_pdf_folder.py; then
    echo "A teszt hibát jelzett. Release megszakítva."
    exit 1
  fi
  echo "Teszt OK, folytatás."
fi

echo "$V" > VERSION
echo "VERSION -> $V"

./deploy-nas.sh

git add VERSION
git commit -m "$COMMIT_MSG"
git tag -a "v${V}" -m "$COMMIT_MSG"
git push origin main
git push origin "v${V}"

echo "Done: v${V} deployed, committed, tagged, pushed."
