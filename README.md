# PDFAI – PDF Eredménykiolvasó

Tanulmányi eredmények kinyerése PDF-ből Groq (Llama) API-val; webes felület + JSON API.

**Részletes dokumentáció (követelmények, architektúra, Groq darabolás, paraméterek, nehézségek, deploy):** [DOCUMENTATION.md](DOCUMENTATION.md)

## Futtatás

- **Lokálisan:** `uvicorn app:app --host 0.0.0.0 --port 8111` (vagy `.venv` + `pip install -r requirements.txt` után).
- **Docker:** `docker compose up -d --build` → az app a **8111** porton fut.
- **Környezet:** másold a `.env.example`-t `.env`-ként, és töltsd ki a `GROQ_API_KEY`-t (és opcionálisan `PDF_DIR`, `APP_PREFIX`).

## Autodeploy a Synology NAS-ra (GitHub → NAS)

Push a `main` branchre (vagy a workflow manuális indítása) után a GitHub Action SSH-val belép a NAS-ra, lehúzza a legújabb kódot és újraindítja a containert.

### 1. NAS előkészítés

- Docker (Synology CSOMAGKÖZPONT) és SSH (Vezérlőpult → Természethozzáférés) bekapcsolva.
- A NAS-on létrehozol egy mappát a projekthez (pl. `/volume1/docker/PDFAI`).
- Ebben a mappában klónozod a repót (egyszer), és létrehozol egy `.env` fájlt (GROQ_API_KEY, stb.) – ezt ne commitold.
- SSH kulcs: a gépeden `ssh-keygen` (vagy a NAS-on), a **publikus** kulcsot a NAS `~/.ssh/authorized_keys`-be (vagy admin felületen), a **privát** kulcsot a GitHub repo Secrets-be teszed (lásd lent).

### 2. GitHub repository Secrets

A repo **Settings → Secrets and variables → Actions** alatt add hozzá:

| Secret neve | Jelentése |
|-------------|-----------|
| `NAS_HOST` | A NAS címe (pl. `192.168.1.10` vagy `nas.local`) |
| `NAS_USER` | SSH felhasználó (pl. `admin` vagy a te user) |
| `NAS_SSH_PRIVATE_KEY` | Az SSH privát kulcs teljes tartalma (amivel a NAS-ra be tudsz lépni) |
| `NAS_PROJECT_PATH` | (Opcionális) A projekt mappa teljes útvonala a NAS-on (pl. `/volume1/docker/PDFAI`). Ha üres, a workflow a `~/PDFAI`-t használja. |

### 3. Push és deploy

- A kód pusholása a **main** branchre automatikusan elindítja a deployt.
- Vagy: **Actions** fül → **Deploy to NAS** → **Run workflow**.

A workflow a NAS-on ezt futtatja: `git fetch && git reset --hard origin/main`, majd `docker compose up -d --build` (vagy `docker-compose`, ha az van). Az app a **8111** porton fut; a reverse proxy-t (pl. 443 → 8111) a Synology-n külön beállítod.
