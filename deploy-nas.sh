
#!/usr/bin/env bash
# NAS deploy – lokálból futtandó. Nincs jelszó/token/privát kulcs a scriptben.
# SSH kulcs: ~/.ssh/ (pl. id_ed25519). A NAS-on a publikus kulcs legyen az authorized_keys-ben.
#
# Változók (env felülírja): NAS_USER, NAS_HOST, NAS_PATH. Konténer neve: pdfai.

set -e

NAS_USER="${NAS_USER:-sitkeitamas}"
NAS_HOST="${NAS_HOST:-dsm.sitkeitamas.hu}"
NAS_PATH="${NAS_PATH:-/volume1/docker/PDFAI}"
CONTAINER_NAME="${CONTAINER_NAME:-pdfai}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Deploy -> ${NAS_USER}@${NAS_HOST}:${NAS_PATH}"

# data/pdf almappa a NAS-on (az app a pdf/ mappát használja alapértelmezett PDF-hez)
ssh -o StrictHostKeyChecking=accept-new "${NAS_USER}@${NAS_HOST}" "mkdir -p ${NAS_PATH}/pdf"

# Feltöltés: tarball pipe (Synology SCP sokszor nem tud írni pl. /volume1/ alá)
# COPYFILE_DISABLE=1: macOS xattr ne kerüljön a tar-ba (a NAS tar nem ismeri)
FILES="app.py requirements.txt Dockerfile docker-compose.yml static templates .env.example"
[ -f VERSION ] && FILES="$FILES VERSION"
COPYFILE_DISABLE=1 tar czf - \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '.venv' \
  --exclude '*__pycache__*' \
  --exclude '*.pyc' \
  -C "$SCRIPT_DIR" \
  $FILES | ssh -o StrictHostKeyChecking=accept-new "${NAS_USER}@${NAS_HOST}" "cd ${NAS_PATH} && tar xzf -"

# Archiválás: redeploy előtt a jelenlegi data/ tartalma archive-ba (törlés/felülírás helyett)
ssh -o StrictHostKeyChecking=accept-new "${NAS_USER}@${NAS_HOST}" "mkdir -p ${NAS_PATH}/data/archive && [ -f ${NAS_PATH}/data/processed.json ] && cp ${NAS_PATH}/data/processed.json ${NAS_PATH}/data/archive/processed_\$(date +%Y%m%d_%H%M%S).json; true"

# Újraépítés és indulás (konténer neve: pdfai)
ssh -o StrictHostKeyChecking=accept-new "${NAS_USER}@${NAS_HOST}" "export PATH=/usr/local/bin:/usr/bin:\$PATH; cd ${NAS_PATH} && (docker compose up -d --build 2>/dev/null || docker-compose up -d --build)"

echo "Done."
