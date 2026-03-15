# NAS deploy (lokálból – nincs secret a Gitben)

A deploy **lokálisan** futtatható, arról a gépről, ahonnan SSH-val eléred a NAS-t. **Sem jelszó, sem SSH kulcs nem kerül a repóba.** A hitelesítés a gépen lévő SSH kulccsal történik. Feltöltés **SSH pipe-pal** (tar), mert a Synology SCP sokszor nem tud írni pl. `/volume1/` alá.

A bevált minta (változók, release.sh és deploy-nas.sh lépései): [NAS-DEPLOY-PATTERN.md](NAS-DEPLOY-PATTERN.md).

---

## Mit kell előkészíteni

1. **NAS:** Docker (CSOMAGKÖZPONT) és SSH (Vezérlőpult → Természethozzáférés) bekapcsolva.
2. **Projekt mappa a NAS-on (egyszer):** Hozz létre egy üres mappát (pl. `/volume1/docker/PDFAI`), és ebben hozz létre egy **`.env`** fájlt (GROQ_API_KEY, stb.) – a `.env`-t nem töltjük fel, csak a kódot. Opcionálisan hozz létre egy **`pdf/`** almappát az alapértelmezett PDF-ekhez (a script is létrehozza, ha hiányzik).
3. **SSH kulcs a gépeden:** A **publikus** kulcs legyen a NAS `~/.ssh/authorized_keys`-ében, hogy jelszó nélkül be tudd lépni.

---

## Változók (deploy-nas.sh)

| Változó     | Jelentése | Alapértelmezett (ezen a projekten) |
|-------------|-----------|-------------------------------------|
| `NAS_USER`  | SSH felhasználó a NAS-on | `sitkeitamas` |
| `NAS_HOST`  | NAS hostname vagy IP | `dsm.sitkeitamas.hu` |
| `NAS_PATH`  | A projekt mappája a NAS-on (abszolút útvonal) | `/volume1/docker/PDFAI` |

Mindegyik felülírható env változóval.

---

## Deploy (csak feltöltés + indulás)

A projekt gyökerében:

```bash
chmod +x deploy-nas.sh
./deploy-nas.sh
```

Ha más NAS vagy útvonal:

```bash
NAS_HOST=nas.local NAS_USER=admin NAS_PATH=/volume1/docker/PDFAI ./deploy-nas.sh
```

A script: tarballot készít (app.py, Dockerfile, docker-compose.yml, static/, templates/, .env.example, VERSION ha van), **pipe-pal** feltölti a NAS **NAS_PATH** mappájába, majd a NAS-on futtatja a `docker compose up -d --build`-ot. Az app a **8111** porton fut.

---

## Release (verzió kirakás + deploy + git)

Egy parancsból: VERSION fájl frissítése → deploy NAS-ra → commit + tag + push.

```bash
chmod +x release.sh
./release.sh 1.0.0
```

Lépések: `VERSION` → `1.0.0`, `./deploy-nas.sh`, majd `git add VERSION`, `git commit -m "Bump VERSION to 1.0.0"`, `git tag -a v1.0.0 -m "v1.0.0"`, `git push origin main`, `git push origin v1.0.0`. A NAS adatait a **deploy-nas.sh** env / alapértelmezettje adja, a release.sh nem kapja paraméterként.

---

## 404 – „A keresett oldal nem található” (transcript.sitkeitamas.hu)

Ha a böngészőben **transcript.sitkeitamas.hu** (vagy más domain) a Synology 404 oldalt mutatja, a **reverse proxy** nincs beállítva, vagy a konténer nem fut.

**1. Konténer fut a NAS-on?**

SSH-val a NAS-ra, majd:

```bash
cd /volume1/docker/PDFAI
docker compose ps
```

Ha az `app` (pdfai) nem „Up”, indítsd: `docker compose up -d --build`.

**2. Reverse proxy a Synologyon**

A domain (pl. **transcript.sitkeitamas.hu**) a NAS-ra mutat, de a kérést tovább kell irányítani a PDFAI konténerre (port **8111**).

- **DSM:** Vezérlőpult → **Bejelentkezési portál** (vagy **Application Portal**) → **Reverse Proxy**.
- **Új szabály:**  
  - Forrás: **Név** pl. „PDFAI”, **Hostname** = `transcript.sitkeitamas.hu`, port 443 (HTTPS) vagy 80 (HTTP).  
  - Cél: **Célhely** = `http://localhost:8111` (vagy `http://127.0.0.1:8111`).  
- Ha a címed **alútvonalas** (pl. `https://transcript.sitkeitamas.hu/pdfai/`), a Célhely legyen `http://localhost:8111/pdfai`, és a NAS-on a projekt `.env`-jében add meg: **APP_PREFIX=/pdfai**.

**3. Gyökér vs. alútvonal**

- **Gyökér:** `https://transcript.sitkeitamas.hu` → Cél: `http://localhost:8111`, APP_PREFIX üres (vagy nincs .env beállítás).
- **Alútvonal:** `https://transcript.sitkeitamas.hu/pdfai/` → Cél: `http://localhost:8111`, a konténer .env: `APP_PREFIX=/pdfai`.

Mentés után a böngészőben érdemes kemény frissítés (Ctrl+F5), és ellenőrizni, hogy a konténer tényleg fut (`docker compose ps`).

---

## Ellenőrzőlista

- [ ] Nincs jelszó/token/privát kulcs a repóban.
- [ ] Deploy lokálból fut, SSH kulcs a gépen (`~/.ssh/`).
- [ ] **NAS_PATH** a projekt saját mappájára van állítva (ha több projekt megy ugyanarra a NAS-ra).

---

## GitHub Actions (eltávolítva)

A korábbi **Deploy to NAS** workflow (push → SSH a NAS-ra) el lett távolítva: a Synology sajátosságai miatt az automata deploy rendszeresen elbukott. A deploy kizárólag **lokálisan** futtatható (release.sh + deploy-nas.sh).
