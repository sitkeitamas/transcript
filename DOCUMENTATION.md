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
- **Web UI:** statikus fájlok (`static/index.html`, `static/styles.css`, `static/js/app.js`). A böngésző csak az **/api/** végpontokat hívja (fetch). Nincs szerver oldali render (Jinja), minden adat API-ból jön. Layout: teljes szélesség (pl. max-width 1400px); 900px felett az alapértelmezett elemzés és a feltöltés két oszlopban jelenik meg. Nincs automatikus görgetés az eredményekhez.
- **Válaszkezelés:** a process-default és upload hívásoknál a válasz először szövegként jön (`response.text()`), majd `JSON.parse`; ha nem JSON (pl. hibaoldal), a felület a HTTP státusz és a szöveg alapján jelez hibát („The string did not match the expected pattern” elkerülése).
- **Reverse proxy (opcionális):** pl. Synology 443 → `http://backend:8111`. Egy külső port (HTTPS 443), egy belső port (8111).

### Végpontok
| Végpont | Metódus | Jelentés |
|---------|---------|----------|
| `/` | GET | Statikus `index.html` (a JS betölti az API adatokat). |
| `/static/*` | GET | CSS, JS, egyéb statikus fájlok. |
| `/api/health` | GET | Egyszerű health check (JSON: status, service, **version**). A verzió a `VERSION` fájlból jön. |
| `/api/models` | GET | Elérhető Groq modellek és alapértelmezett modell (a felület modellválasztóhoz). |
| `/api/logs` | GET | Utolsó N log sor (memóriában), a webfelület Log paneljához. |
| `/api/default-pdf-info` | GET | Van-e alapértelmezett PDF a `pdf/` mappában (fájlnév vagy null). |
| `/api/process-default` | POST | A `pdf/` mappában lévő első PDF feldolgozása; query: opcionális `model`. Válasz: ugyanaz a struktúra, mint az upload (+ `model_used`). |
| `/api/upload` | POST | Feltöltött PDF feldolgozása (multipart: `file`, opcionális `label`, `model`). Válasz: JSON (+ `model_used`, tokenhasználat, rate limit). |
| `/api/history` | GET | Feldolgozási előzmény (processed.json utolsó N bejegyzés) az összehasonlításhoz. Query: `limit` (alap 30). |
| `/api/default-pdf` | GET | Alapértelmezett PDF fájl kiszolgálása (megnyitás/letöltés). |

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
  "error": "string | null",
  "model_used": "string | null",
  "usage_total_tokens": "number | null",
  "rate_limit_remaining_tokens": "number | null",
  "doc_url": "string | null"
}
```
- Ha hiba volt: `error` kitöltve, a többi lehet üres. A **429** (rate limit) esetén a felület barátságos magyar üzenetet mutat (várj, vagy válassz magasabb limitű modellt).
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
| `LOG_LEVEL` | nem | `INFO` | Log szint: `DEBUG`, `INFO`, `WARNING`, `ERROR`. A logok stdout-ra mennek (Docker: `docker logs`) és a webfelület Log panelja az utolsó ~200 sort lekéri az `/api/logs`-ból. |

### Verzió és verziószámozás
- A **VERSION** fájl első sora adja az alkalmazás verzióját (pl. `1.2.14`). Az `/api/health` ezt adja vissza; a webfelület a fejlécben megjeleníti (pl. „v1.2.14”). Ha nincs VERSION fájl, a backend `dev`-ot ad.
- **Verziószámozás:** verzió.változat.javítás. A javítás (harmadik szám) növekszik: 1.2.9 → 1.2.10 → 1.2.11 (nem 1.3.0). A középső szám csak nagyobb változáskor nő.

### Logolás
- **Backend:** Python `logging`; szint a `LOG_LEVEL` env-ből. Üzenetek: indulás/zárás feldolgozás (process-default, upload), használt modell, PDF szöveghossz, chunkok száma, 429 rate limit, hibák.
- **Memóriapuffer:** az utolsó 200 log sor tárolódik; a **GET /api/logs** ezt adja vissza (`{"lines": ["...", ...]}`).
- **Webfelület:** a lap alján a **Log** gombra kattintva megjelenik a log panel; a **↻** gombbal frissíthető.

### Feldolgozási előzmény (tesztelési történet)
- **Minden** futtatás (alapértelmezett PDF elemzés és feltöltés is) eredménye belekerül a **data/processed.json** fájlba (időbélyeg, forrás, doc_label, modell, hallgató, intézmény, rekordszám, hiba, teljes result lista).
- **Sikertelen futások** (Groq hiba, PDF kinyerés, timeout, stb.) a **data/failure_log.jsonl** fájlba kerülnek (JSONL: egy sor = egy JSON). Cél: finomhangolás bemenete, ne találgatás. A Groq válaszból (státusz, rate limit header-ek, response snippet) és a futás adataiból (doc_label, modell, error_type) minden sikertelen futás rögzítve. Részletes szabály és **folyamat** (mindig a log együttes átnézése a további lépés előtt): [FAILURE-LOG.md](FAILURE-LOG.md).
- A lista legfeljebb **500** bejegyzés (régebbiek törlődnek). A fájl a konténerben **/app/data** alatt van; Docker volume **./data:/app/data** miatt a host (NAS) **data/** mappájában marad.
- **Minden deploy során** (lokális **deploy-nas.sh** és a GitHub Actions deploy is) a jelenlegi **data/processed.json** másolódik **data/archive/processed_YYYYMMDD_HHMMSS.json** néven, így megmarad a teljes tesztelési történet deployonként.
- **Összehasonlítás:** a webfelület az Eredmények alatt „Összehasonlítás korábbi futtatással” szekcióval kínálja a **GET /api/history** alapján egy korábbi futtatás kiválasztását; az „Összehasonlítás” gomb soronkénti eltérést mutat (pl. osztályzat most vs. korábbi).

### Tokenhasználat és rate limit a felületen
- A feldolgozás után az eredmény meta részében megjelenik: **Felhasznált tokenek** (összesen, prompt, válasz) és **Maradék lehetőség** (token/perc, kérés maradt), ha a Groq válasz és header-ek ezt adják.

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

## 5.1 Hibaelhárítás: „Nem sikerült szöveget kinyerni a PDF-ből”

### A hibaüzenet

Ha ezt látod a felületen:

> *A PDF-ből nem sikerült szöveget kinyerni (pypdf, pdfplumber, PyMuPDF és az OCR próba sem adott szöveget, vagy az OCR nincs telepítve). Ha a PDF szkennelt/képalapú: telepítsd a tesseract-et és a pdf2image-ot a szerverre, vagy küldj be egy már szöveges (pl. OCR-elt) PDF-et.*

jelentése: egyik szövegkinyerő sem adott használható szöveget (sem pypdf, sem pdfplumber, sem PyMuPDF, sem az OCR).

### Gyakori okok

1. **Szkennelt vagy csak képalapú PDF** – a fájlban nincs „igazi” szövegréteg, csak képek. Ilyenkor az **OCR** (Tesseract) tud segíteni, ha a szerveren telepítve van.
2. **OCR nincs telepítve** – a Python csomagok (pdf2image, pytesseract) a `requirements.txt`-ben vannak, de az OCR futtatásához a **rendszerben** is kell:
   - **tesseract-ocr** (és opcionálisan **tesseract-ocr-hun** magyarhoz),
   - **poppler-utils** (a pdf2image a `pdftoppm` programot használja).
3. **Sérült vagy jelszóval védett PDF** – ilyenkor a kinyerés vagy az OCR is meghiúsulhat.

### Megoldás: OCR engedélyezése Dockerben

A **Dockerfile** alapból telepíti a tesseract-et és a poppler-t, így az OCR a konténerben elérhető. Ha régebbi image-d van, építsd újra:

```bash
docker compose build --no-cache
docker compose up -d
```

Ha saját Dockerfile-t használsz, győződj meg róla, hogy az `apt-get install` tartalmazza: `tesseract-ocr`, `tesseract-ocr-hun`, `poppler-utils`.

### Megoldás: lokál futtatás (venv)

- **macOS (Homebrew):** `brew install tesseract tesseract-lang poppler`
- **Debian/Ubuntu:** `sudo apt-get install tesseract-ocr tesseract-ocr-hun poppler-utils`
- **Windows:** telepítsd a [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) és a [Poppler Windows binárisokat](https://github.com/osber/poppler-windows/releases), és add hozzá őket a PATH-hoz.

Ezután a `pip install -r requirements.txt` (pdf2image, pytesseract) már tudja használni az OCR-t.

### Alternatíva

Ha nem akarsz OCR-t a szerveren: a szkennelt PDF-et külső eszközzel (pl. Adobe, online OCR) alakítsd szöveges PDF-vé, és azt töltsd fel.

### Log

Ha az OCR próba sikertelen, a **Log** panel (vagy a szerver log) tartalmazza a konkrét hibát (pl. „tesseract not found”, „poppler not installed”), ami segít a telepítésben.

---

## 5.2 Layout detection az OCR előtt (trükk a jobb transcript felismeréshez)

A legtöbb naiv pipeline: **PDF → OCR → szöveg**, és abból próbálunk strukturált adatot nyerni. A hibák gyakran abból adódnak, hogy az OCR nem tudja, hogy *mi* az adott régió: táblázat, fejléc, oszlop, jegyzet stb.

**Erősebb megközelítés:**

- **PDF → layout detection → OCR (régiónként) → strukturált rekordok**

A layout detection megmondja: ez egy *table*, ez egy *text block*, ez *title*, *figure*, *list*. Az OCR (vagy a szövegkinyerés) ezekkel a címkékkel tud külön kezelni régiókat, így pontosabb a táblázat cellák és a fejléc/footer szétválasztása.

**Transcriptnél ez konkrétan azt jelenti:** a dokumentum régióit felismerjük, pl.:

- **COURSE TABLE** (tárgyak, kredit, osztályzat)
- **GPA SUMMARY**
- **TRANSFER CREDIT TABLE**
- fejléc / footer / jegyzet

Ezek után régiónként (pl. „csak a COURSE TABLE blokk”) futtatjuk az OCR-t vagy a szövegkinyerést, és a Groq-nak már jelzett blokkokat adunk („ez a tárgytáblázat”, „ez a GPA összesítő”), ami segíthet a helyes mezők kitöltésében.

**Eszközök (open source):**

- **LayoutParser** – layout elemzés, különböző backend modellekkel.
- **Detectron2** (Facebook) – objektumdetektálás, layout modellekhez is használják.
- **PubLayNet** modellek – dokumentumlayoutra tanítva, felismerik pl.: *table*, *text block*, *title*, *figure*, *list*.

**Miért nem „ágyúféleség”?** A layout detection **csökkenti az LLM-függőséget**: kevesebb szöveg megy a modellnek (csak a releváns blokkok, pl. course table), gyorsabb és olcsóbb a futtatás, kevésbé érzékeny a rate limitre. Ha a táblázat struktúrája (sorok, oszlopok) kiderül, a cellák kinyerése részben **determinisztikus** (rule-based) is lehet, az LLM csak a tisztázatlan vagy szabad szövegű mezőknél kell. Összefoglalva: nem csak minőség, hanem **kevesebb/látékonyabb LLM használat** – lassú és drága helyett inkább layout + kisebb, célzott prompt.

**Jelenlegi állapot:** A PDFAI most a 5. szakasz szerint kinyeri a szöveget (pypdf → pdfplumber → PyMuPDF → OCR), layout detection **nincs** beépítve. Ez a szakasz a koncepciót dokumentálja egy **későbbi fejlesztés** (vagy kísérlet) számára: jobb minőség *és* kisebb LLM-függőség érdekében érdemes kipróbálni egy layout-detection lépést az OCR előtt, régiónként szöveget nyerni, és csak a releváns blokkokat (címkével) a Groq-nak adni, vagy a táblázatot rule-baseden feldolgozni.

---

## 5.3 Table-aware OCR (a második trükk)

**Transcript = táblázat.** Ha sima OCR fut az oldalon, a kimenet lapos szöveg: `cell1 cell2 cell3 cell1 cell2 cell3` – a sor/oszlop/cella struktúra elvész, az LLM vagy a rule-based logika nehezebben tudja értelmezni.

**Table-aware megközelítés:** ne az egész oldalt OCR-öljük, hanem:

1. **Table detection** – hol van a táblázat.
2. **Cell segmentation** – sorok, oszlopok, cellák felismerése.
3. **OCR per cell** – cellánként futtatjuk az OCR-t; a kimenet már **row / column / cell** struktúrában marad.

Így a transcript adatai (tárgy, kód, kredit, osztályzat) cella-szinten kaphatók, determinisztikusan vagy minimális LLM-mel.

**Eszközök (open source):**

- **Camelot** – táblázat kinyerés (lattice / stream).
- **Tabula** – táblázat kinyerés.
- **pdfplumber** – már a pipeline-ban van; táblázat kinyerést is tud (`extract_tables()`), jelenleg főleg szöveghez használjuk.
- **OCR alapú, táblázatra:** PaddleOCR table mode, Microsoft Table Transformer.

**Tipikus pipeline:**

```
PDF page
   ↓
table detection
   ↓
cell segmentation
   ↓
OCR per cell
```

Tapasztalati megállapítás: ez a lépés a táblázatos transcript hibák **nagy részét** (nagyságrendileg ~95%) megoldja, mert a struktúra megmarad.

**Implementálandók listáján:** layout detection (5.2) és table-aware OCR (5.3) együtt – előbb layout (hol a „course table” blokk), aztán a blokkon belül table detection → cell segmentation → OCR per cell; a cella-szintű kimenet pedig csökkenti az LLM terhet vagy teljesen rule-based rekordra alakítható.

---

## 5.4 Bounding box OCR és további trükkök (implementálandók)

A következő ötletek egy determinisztikus, LLM-nélküli (vagy minimális LLM) pipeline részei; összegyűjtve a 3.–12. trükk, költség és egy gyakorlati tanács.

### 3. Harmadik trükk: bounding box OCR

- **Sima OCR:** csak `text`.
- **Jobb OCR:** `text + bounding box` (x, y), pl. `{ "text": "Child Psychology", "x": 120, "y": 350 }`.
- **Miért jó:** row grouping (hasonló y → ugyanaz a sor), column grouping; így rekonstruálható a táblázat. Egyszerű szabály: ha y koordináta hasonló → ugyanaz a sor.

### 4. Negyedik trükk: column clustering

- Transcriptben jellemzően: **COURSE | CODE | TERM | CREDIT | GRADE**.
- Ha van bounding box: összes **x** koordináta → **K-means clustering** → oszlophatárok. Pl. x = [120, 140, 150] → column 1, x = [350, 360] → column 2, x = [550] → column 3. Így **LLM nélkül** rekonstruálható a táblázat.

### 5. Ötödik trükk: regex-alapú mezőfelismerés

- Transcript mezők nagyon standardek; regex-el **nagyon stabil** extraction:
  - **Kurzuskód:** `[A-Z]{2,4}\s?\d{3}` vagy `[A-Z]{3,4}\s?\d{5}`
  - **Kredit:** `\d(\.\d)?`
  - **Osztályzat:** `A|A-|B\+|B|B-|C\+|PA|CR`
  - **Félév:** `(Autumn|Fall|Spring|Winter)\s?\d{4}`

### 6. Hatodik trükk: dictionary matching

- Transcript tárgynevek gyakran ismétlődnek; lehet **dictionary** (pl. CALCULUS I, INTRO TO ACCOUNTING I). OCR fuzzy match: „CALCULUS 1”, „CALCULUS l”, „CALCULUS I” → mind ugyanaz. **Eszköz:** rapidfuzz.

### 7. Hetedik trükk: transfer table felismerés

- Sok transcript: **Original Course | Equivalent**. Szabály: ha egy sorban **két kurzuskód** van → transfer table (pl. PSYC 20651 | PSY 333). Pipeline: `if count(course_code) > 1: mark_as_transfer`.

### 8. Nyolcadik trükk: page segmentation

- Transcript oldal tipikus: **header** / **course table** / **footer**. Footer sokszor: „Page 1 of 3”. Regex: `Page \d+ of \d+` → kidobható.

### 9. Kilencedik trükk: sor validáció

- Egy valid transcript sor általában **legalább 3 mezőt** tartalmaz (pl. course, credit, grade). Ha az OCR sor pl. csak „CALCULUS” → **dobjuk**.

### 10. Tizedik trükk: determinisztikus pipeline

- Nagyon stabil lánc:
  ```
  PDF
   ↓
  page image
   ↓
  layout detection
   ↓
  table detection
   ↓
  cell segmentation
   ↓
  OCR per cell
   ↓
  regex parsing
   ↓
  row validation
   ↓
  CSV
  ```
  **LLM:** 0 vagy csak QA (quality check).

### 11. Költség (tipikus)

- **LLM pipeline:** 1000 transcript ≈ **$20–80**.
- **OCR (determinisztikus) pipeline:** 1000 transcript ≈ **$1–3**.

### 12. Gyakorlati trükk: OCR output hash

- **Hash-eld** az OCR kimenetet: `sha256(text)`. Ha két futás hash-e **különbözik** → az OCR kimenet változott → segít debugolni (regresszió, flaky OCR).

---

Ezek a trükkök (5.2, 5.3, 5.4) az **implementálandók** listáján vannak. A **LLM-mentes transcript pipeline** (toolchain, ~200 soros példa, OCR összehasonlítás, preprocessing, hash) és az **elfogadott lépések / stratégia** (nincs kódváltoztatás a main PDFAI-ban; kísérlet = fork vagy külön projekt; visszahozatal csak meggyőző eredmény esetén) a **[TRANSCRIPT-PIPELINE-REFERENCE.md](TRANSCRIPT-PIPELINE-REFERENCE.md)** fájlban van dokumentálva.

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
- **test_pdf_folder.py:** a **pdf/** mappában lévő legfeljebb **3** PDF sorban feldolgozása alapbeállításokkal (alapértelmezett modell). Használat: `python test_pdf_folder.py`. Kilépés: 0 = mind sikeres, 1 = hiba vagy nincs GROQ_API_KEY. A **release.sh** induláskor megkérdezi: „Fusson a PDF könyvtár teszt?” — ha **y**, futtatja ezt a scriptet; ha a teszt hibázik, a release megszakad (nem deployol, nem commitol).

---

## 7. Deploy (NAS, lokálból)

### Folyamat
A deploy **nem** fut GitHub Actions-ban (a Synology sajátosságai miatt az automata deploy el lett távolítva). Lokálisan futtatod:

1. **release.sh** (verzió + deploy + git): `./release.sh 1.2.15` — kérdezi a pdf/ tesztet, frissíti a VERSION-t, meghívja a **deploy-nas.sh**-t, majd commit + tag + push.
2. **deploy-nas.sh**: tarball (kód, Dockerfile, static, stb.) SSH pipe-pal feltölti a NAS **NAS_PATH** mappájába, archiválja a data/processed.json-t, majd `docker compose up -d --build`.

### Változók (deploy-nas.sh, env felülírja)
- **NAS_USER** – SSH felhasználó (alap: pl. sitkeitamas).
- **NAS_HOST** – NAS hostname vagy IP (pl. dsm.sitkeitamas.hu).
- **NAS_PATH** – Projekt mappa a NAS-on (pl. /volume1/docker/PDFAI).

### NAS előkészítés
- Docker (Synology csomag) és SSH engedélyezve.
- A projekt mappa a NAS-on (egyszer létrehozva), benne **.env** (GROQ_API_KEY, stb.) – ezt nem töltjük fel a scripttel.
- SSH kulcs: a **publikus** kulcs a NAS `authorized_keys`-ében, a **privát** a gépeden (~/.ssh/); semmi nem kerül a repóba.

---

## 8. Összefoglaló

- **Követelmény:** PDF → strukturált adat (hallgató, intézmény, tárgyak), webfelület + egy port, Docker, autodeploy NAS-ra.
- **Architektúra:** FastAPI egy porton (8111); statikus UI + JSON API; reverse proxy opcionális.
- **Paraméterek:** .env (GROQ_*, PDF_DIR, APP_PREFIX, LOG_LEVEL); belső limitek (4000 kar/chunk, 50k kar összesen).
- **Verzió:** VERSION fájl, verzió.változat.javítás (pl. 1.2.14); release.sh kérdezi a pdf/ teszt futtatását.
- **Groq darabolás:** 4k kar chunkok, sortörésnél vágás, chunkok között 30 s delay; 413/429 miatt így alakult; 429-nél barátságos hibaüzenet; tokenhasználat és maradék limit az eredményeknél.
- **Előzmény és összehasonlítás:** data/processed.json, deploy során archive; GET /api/history, webfelületen soronkénti eltérés korábbi futtatással.
- **PDF szövegkinyerés:** pypdf → pdfplumber → PyMuPDF → OCR (tesseract + poppler a Dockerfile-ban); hibaelhárítás: 5.1.
- **Deploy:** Csak lokális release.sh (VERSION, opcionális teszt, deploy-nas.sh, commit, tag, push); nincs GitHub Actions deploy.
