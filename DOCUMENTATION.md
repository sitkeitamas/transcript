# PDFAI – Teljes dokumentáció

## 1. Követelmények

### Funkcionális
- PDF feltöltés vagy alapértelmezett PDF (a `pdf/` mappából) feldolgozása.
- A PDF-ből kinyerni: **hallgató neve**, **intézmény**, és tárgyonként: **tárgy neve**, **kód**, **félév**, **kredit**, **osztályzat** (ahol ezek elérhetők).
- Eredmény megjelenítése **táblázatosan** és **nyers JSON**-ként a webfelületen.
- Több dokumentum eredménye ugyanabban a standard elrendezésben (egy oldal, ugyanaz a táblázat + JSON blokk).
- Egy porton szolgáltatás (web UI + API), hogy reverse proxy (pl. Synology NAS, 443) mögé lehessen tenni.

### Nem funkcionális
- Groq (Llama) API használata a strukturált kinyeréshez; ingyenes / limitált tierrel is használható.
- Dockerrel futtatható; lokálisan és NAS-on ugyanaz a port (8111).
- Autodeploy: GitHub push → NAS frissítés (SSH + git pull + docker compose up).

---

## 2. Architektúra

### Rétegek
- **Backend (FastAPI):** egy folyamat, egy port (8111). Szolgálja a **statikus webfelületet** (HTML, CSS, JS) és a **JSON API**-t.
- **Web UI:** statikus fájlok (`static/index.html`, `static/styles.css`, `static/js/app.js`). A böngésző csak az **/api/** végpontokat hívja (fetch). Nincs szerver oldali render (Jinja), minden adat API-ból jön.
- **Reverse proxy (opcionális):** pl. Synology 443 → `http://backend:8111`. Egy külső port (HTTPS 443), egy belső port (8111).

### Végpontok
| Végpont | Metódus | Jelentés |
|---------|---------|----------|
| `/` | GET | Statikus `index.html` (a JS betölti az API adatokat). |
| `/static/*` | GET | CSS, JS, egyéb statikus fájlok. |
| `/api/health` | GET | Egyszerű health check (JSON). |
| `/api/default-pdf-info` | GET | Van-e alapértelmezett PDF a `pdf/` mappában (fájlnév vagy null). |
| `/api/process-default` | POST | A `pdf/` mappában lévő első PDF feldolgozása; válasz: ugyanaz a struktúra, mint az upload. |
| `/api/upload` | POST | Feltöltött PDF feldolgozása (multipart: `file`, opcionális `label`). Válasz: JSON. |

### API válasz struktúra (ProcessResponse)
```json
{
  "result": [
    { "course_name": "", "course_code": "", "term": "", "credits": null, "grade": "" }
  ],
  "student_name": "string | null",
  "institution": "string | null",
  "doc_label": "string | null",
  "raw_json": "string | null",
  "error": "string | null"
}
```
- Ha hiba volt: `error` kitöltve, a többi lehet üres.
- A webfelület ebből a JSON-ból rajzolja a táblázatot és a nyers JSON blokkot.

### CORS
- CORS engedélyezve (pl. `allow_origins=["*"]`), hogy ha a UI máshol fut, az is hívhassa az API-t. Egy porton (reverse proxy) same-origin, így nem kötelező a külön origin.

### Path prefix (pl. Synology /pdfai)
- Ha a backend nem a gyökér alatt fut, hanem pl. `https://nas.local/pdfai/`, akkor a **.env**-ben: `APP_PREFIX=/pdfai`. Az app ekkor a `/pdfai` alatt van mountolva; a böngészőben a `location.pathname` alapján az `app.js` automatikusan az `/pdfai/api/...` útvonalat használja.

---

## 3. Paraméterek

### Környezeti változók (.env)

| Változó | Kötelező | Alapérték | Jelentés |
|---------|----------|-----------|----------|
| `GROQ_API_KEY` | igen | – | Groq API kulcs (console.groq.com). |
| `GROQ_MODEL` | nem | `llama-3.1-8b-instant` | Groq modell neve (pl. `llama-3.3-70b-versatile`). |
| `GROQ_DELAY_BETWEEN_REQUESTS` | nem | `30` | Másodperc várakozás **chunkok között** (rate limit miatt). |
| `PDF_DIR` | nem | – | Ha a szerver nem találja a `pdf/` mappát, itt megadható a teljes útvonal (alapértelmezett PDF mappája). |
| `APP_PREFIX` | nem | – | Reverse proxy path prefix (pl. `/pdfai`). |

### Belső konstansok (app.py)
- **MAX_PDF_CHARS_PER_REQUEST** = 4000 (kb. 4k karakter / kérés).
- **MAX_PDF_TEXT_TOTAL** = 50 000 (a kinyert PDF szöveg max hossza; ennél hosszabb szöveget csonkoljuk).

---

## 4. Groq darabolás: miért, hogyan, nehézségek

### Miért darabolunk?
- A **Groq API** korlátozza a **kérés méretét** (HTTP 413 Payload Too Large), és a **percenkénti kérésszámot** (HTTP 429 Too Many Requests).
- Egy nagy PDF kinyert szövege (pl. 20–50 ezer karakter) nem fér bele egy kérésbe biztonságosan, és sok kérés egymás után 429-et okozhat.

### Hogyan darabolunk?
1. **Szövegkinyerés:** a PDF-ből először szöveget nyerünk ki (lásd lent: pypdf → pdfplumber → PyMuPDF → OCR).
2. **Csonkolás:** ha a szöveg hosszabb, mint **MAX_PDF_TEXT_TOTAL** (50 000 karakter), csak az első 50k karaktert vesszük.
3. **Chunkolás:** a maradék szöveget **MAX_PDF_CHARS_PER_REQUEST** (4000) karakteres darabokra vágjuk. A vágást **sortörésnél** végezzük (ha lehet), ne szó közepén.
4. **Kérések:** minden chunkra egy **chat completion** kérés megy a Groq-hoz. Ugyanaz a **system prompt** (JSON séma), a user üzenetben: „A dokumentum szövege (rész 1/N): …”.
5. **Várakozás:** chunkok között **GROQ_DELAY_BETWEEN_REQUESTS** másodpercet várunk (alap 30), hogy ne üssük meg a percenkénti limitet.
6. **Összefésülés:** a válaszokból a `records` listákat összeolvasztjuk; a `student_name` és `institution` értékeket az első nem üres válaszból vesszük.

### Miért pont így?
- **413:** a korábbi tapasztalat szerint túl nagy user message (pl. 8k+ karakter) már 413-at adott; 4000 karakteres chunk + rövid system prompt biztonságos.
- **429:** ingyenes / alacsony tieren gyakran 2 kérés/perce a limit; 30 s delay ≈ 2 kérés/perc. Magasabb limitnál csökkenthető (pl. 5 s).
- **Sortörésnél vágás:** a modellnek tisztább a bemenet, ha a chunk nem tör el egy sort középen.

### Nehézségek és javasolt út
- **Rate limit (429):** hosszú PDF = sok chunk = sok várakozás. Megoldás: növelni a **GROQ_DELAY** csak akkor, ha továbbra is 429 jön; ha a limitet felnyomtad, csökkenthető (pl. 5–10 s), így gyorsabb a feldolgozás.
- **413:** ha még mindig 413-at kapsz, csökkentsd a **MAX_PDF_CHARS_PER_REQUEST**-et (pl. 2000), vagy a `.env`-ben állíts be egy kisebb értéket (ha ezt később konfigurálhatóvá tesszük).
- **Szkennelt PDF:** ha a PDF csak kép, a szövegkinyerés üres. Ekkor az **OCR** (Tesseract + pdf2image) próbálkozik; ehhez a NAS-on / gépen legyen **poppler** és **tesseract** (és opcionálisan **tesseract-lang**). Ha nincs OCR, a felhasználónak ezt jelezzük.
- **Titkosított PDF:** AES titkosított PDF-hez a **cryptography** csomag kell (requirements.txt-ben benne van).
- **Hosszú feldolgozás:** a webfelület 10 percig vár a **POST /api/process-default** válaszára (fetch timeout); ha több chunk van, a feldolgozás ennél tovább tarthat. Járható út: növelni a timeout-ot, vagy később háttérfeladat + polling.

---

## 5. PDF szövegkinyerés (sorrend)

1. **pypdf** – alap kinyerés.
2. **pdfplumber** – táblázatos / nehéz layoutnál gyakran jobb.
3. **PyMuPDF (fitz)** – sok „nehéz” PDF-nél erősebb.
4. **OCR (pdf2image + pytesseract)** – ha egyik sem ad szöveget (szkennelt PDF). Nyelv: `hun+eng`, fallback `eng`.

Ha egyik sem ad szöveget, hibaüzenet: a PDF valószínűleg csak kép, vagy sérült.

---

## 6. Futtatás

### Lokál (venv)
```bash
cd /path/to/PDFAI
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# .env létrehozása, GROQ_API_KEY kitöltése
uvicorn app:app --host 0.0.0.0 --port 8111
```
- Böngésző: `http://localhost:8111`

### Docker
```bash
docker compose up -d --build
```
- Port: **8111** (nem 8000). Böngésző: `http://localhost:8111`

### Teszt scriptek
- **test_performance.py:** alapértelmezett PDF feldolgozása mérésekkel (chunk idő, delay, összes idő). Paraméterek a .env-ből.
- **test_groq_limit.py:** Groq limit tesztelése különböző chunk méretekkel (régi, opcionális).

---

## 7. Deploy (NAS, GitHubon át)

### Folyamat
1. Push a **main** branchre (vagy manuális **Run workflow** a **Deploy to NAS** workflow-ra).
2. GitHub Actions: **webfactory/ssh-agent** betölti a **NAS_SSH_PRIVATE_KEY** titkot.
3. SSH a NAS-ra: **NAS_USER@NAS_HOST**.
4. A **NAS_PROJECT_PATH** (vagy `~/PDFAI`) mappában: `git fetch origin && git reset --hard origin/main`, majd `docker compose up -d --build` (vagy `docker-compose`).

### Szükséges GitHub Secrets
- **NAS_HOST** – NAS címe (IP vagy hostname).
- **NAS_USER** – SSH felhasználó.
- **NAS_SSH_PRIVATE_KEY** – SSH privát kulcs teljes szövege.
- **NAS_PROJECT_PATH** (opcionális) – a repo mappája a NAS-on (pl. `/volume1/docker/PDFAI`).

### NAS előkészítés
- Docker (Synology csomag) és SSH engedélyezve.
- A projekt mappa klónozva (egyszer), benne **.env** (GROQ_API_KEY, stb.) – ezt ne commitoljuk.
- SSH kulcs: a privát a GitHub Secret, a publikus a NAS `authorized_keys`-ben.

---

## 8. Összefoglaló

- **Követelmény:** PDF → strukturált adat (hallgató, intézmény, tárgyak), webfelület + egy port, Docker, autodeploy NAS-ra.
- **Architektúra:** FastAPI egy porton (8111); statikus UI + JSON API; reverse proxy opcionális.
- **Paraméterek:** .env (GROQ_*, PDF_DIR, APP_PREFIX); belső limitek (4000 kar/chunk, 50k kar összesen).
- **Groq darabolás:** 4k kar chunkok, sortörésnél vágás, chunkok között 30 s delay; 413/429 miatt így alakult; nehézségek: rate limit, szkennelt PDF, hosszú futás.
- **Deploy:** GitHub Actions SSH-val a NAS-ra, git pull + docker compose up; a legutolsó verzió minden eddig leszedett (feldolgozott) fájlt a standard elrendezésben konvertálja és jeleníti meg.
