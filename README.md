# PDFAI – PDF Eredménykiolvasó

Tanulmányi eredmények kinyerése PDF-ből Groq (Llama) API-val; webes felület + JSON API.

**Részletes dokumentáció (követelmények, architektúra, Groq darabolás, paraméterek, nehézségek, deploy):** [DOCUMENTATION.md](DOCUMENTATION.md)

## Futtatás

- **Lokálisan:** `uvicorn app:app --host 0.0.0.0 --port 8111` (vagy `.venv` + `pip install -r requirements.txt` után).
- **Docker:** `docker compose up -d --build` → az app a **8111** porton fut.
- **Környezet:** másold a `.env.example`-t `.env`-ként, és töltsd ki a `GROQ_API_KEY`-t (és opcionálisan `PDF_DIR`, `APP_PREFIX`).

## Deploy a Synology NAS-ra (lokálból)

A NAS-ra **lokálisan** deployolunk (release.sh → deploy-nas.sh), SSH kulccsal a gépről. Nincs GitHub Actions deploy (a Synology sajátosságai miatt az korábban elbukott).

### 1. NAS előkészítés

- Docker (Synology CSOMAGKÖZPONT) és SSH (Vezérlőpult → Természethozzáférés) bekapcsolva.
- A NAS-on létrehozol egy mappát a projekthez (pl. `/volume1/docker/PDFAI`).
- Ebben a mappában klónozod a repót (egyszer), és létrehozol egy `.env` fájlt (GROQ_API_KEY, stb.) – ezt ne commitold.
- SSH kulcs: a gépeden `ssh-keygen` (vagy a NAS-on), a **publikus** kulcsot a NAS `~/.ssh/authorized_keys`-be (vagy admin felületen), a **privát** kulcsot a GitHub repo Secrets-be teszed (lásd lent).

### 2. Deploy futtatása

A projekt gyökerében: `./release.sh 1.2.16` (vagy aktuális verzió) — ez frissíti a VERSION-t, futtatja a deploy-nas.sh-t (SSH + tarball + docker compose), majd commitol és pushol. A NAS címe és útvonala a **deploy-nas.sh** env változóiban (NAS_USER, NAS_HOST, NAS_PATH) van; részletek: [DEPLOY.md](DEPLOY.md).

Az app a **8111** porton fut; a reverse proxy-t (pl. 443 → 8111) a Synology-n külön beállítod.
