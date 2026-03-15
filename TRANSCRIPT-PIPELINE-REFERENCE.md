# LLM-mentes transcript pipeline – referencia és elfogadott lépések

Ez a dokumentum **referencia**. A jelenlegi PDFAI (Groq + pypdf/pdfplumber/PyMuPDF/Tesseract) **változatlan marad**, beton stabil.

**A ~200 soros Python pipeline kódja (1:1 referencia):** [reference/transcript_pipeline_reference.py](reference/transcript_pipeline_reference.py) A következők csak dokumentáltak; a kísérlet **forkban vagy külön projektben** történhet, és csak meggyőző eredmény esetén kerülhet szóba visszahozatal vagy integráció.

---

## 1. Az anyag összefoglalása (bejövő anyag alapján)

### 1.1 Ajánlott open-source toolchain

- **pdf2image** → PDF → image  
- **PaddleOCR** → OCR + bounding box  
- **scikit-learn** → oszlop clustering (K-means)  
- **rapidfuzz** → fuzzy course name cleanup  
- **pandas** → strukturált kimenet  
- **opencv-python** → image preprocessing  

Függőség: `paddleocr`, `pdf2image`, `pillow`, `pandas`, `scikit-learn`, `rapidfuzz`, `opencv-python`; Linux: `poppler-utils`, Mac: `poppler`.

### 1.2 Cél pipeline

```
PDF → OCR (bounding box) → layout / row grouping → column clustering → regex parsing → row validation → CSV
```

LLM nélkül. A ~200 soros Python példa: pdf2image → PaddleOCR (box) → y alapú row grouping → K-means oszlop → regex (course code, grade, credit) → rapidfuzz course name → valid sorok → DataFrame/CSV.

### 1.3 OCR engine összehasonlítás (transcript)

- **PaddleOCR:** legjobb open source; bounding box, kis font, layout-barát; ~0.7 s/oldal CPU; 94–97% pontosság.  
- **Tesseract:** stabil, gyors; gyenge table struktúra, zajos bounding box; 85–90%.  
- **EasyOCR:** egyszerű; kurzuskódokat gyengébben kezeli; 88–92%.

### 1.4 Optimalizáció

- **Image preprocessing** (pl. `cv2.adaptiveThreshold`) jelentősen javítja az OCR-t (állítólag ~10× gyorsabb/hatékonyabb).  
- **OCR output hash** (pl. sha256): ha két futás hash-e különbözik → OCR kimenet változott → debug.

### 1.5 Nagyon nagy mennyiség (100k+ transcript)

- **layoutparser + table-transformer** → 95–98% pontosság LLM nélkül.

---

## 2. Elfogadható lépések – mit tartunk jó ötletnek

A következőket **elfogadjuk** mint valid, jól dokumentált irányt; **nem** változtatunk a jelenlegi PDFAI kódján miattuk.

| Lépés / ötlet | Elfogadva? | Megjegyzés |
|---------------|------------|------------|
| Bounding box OCR (text + x, y) | Igen | Row/column grouping alapja; rekonstruálható a táblázat. |
| Row grouping (hasonló y → ugyanaz a sor) | Igen | Egyszerű, determinisztikus. |
| Column clustering (x koordináták → K-means → oszlopok) | Igen | LLM nélkül táblázat. |
| Regex-alapú mezőfelismerés (kurzuskód, kredit, osztályzat, félév) | Igen | Nagyon stabil; a docban már szerepeltek a minták. |
| Dictionary + fuzzy match (rapidfuzz) tárgynevekhez | Igen | CALCULUS 1 / l / I → egy forma. |
| Sor validáció (pl. legalább code + credit) | Igen | Zaj sorok kidobása. |
| Transfer table felismerés (két kurzuskód egy sorban) | Igen | mark_as_transfer. |
| Page segmentation (header/table/footer, Page 1 of 3 kidobás) | Igen | Zaj csökkentés. |
| OCR output hash (sha256) debughoz | Igen | Regresszió / flaky OCR felismerés. |
| Image preprocessing (adaptive threshold stb.) | Igen | Pontosság/gyorsaság. |
| PaddleOCR mint első számú OCR transcriptre | Igen | Referencia szerint legjobb; **de** új, nagy függőség – csak kísérletben. |
| Teljes determinisztikus pipeline (PDF → … → CSV, LLM 0 vagy csak QA) | Igen | Célképek; kísérletben. |
| layoutparser + table-transformer 100k+ esetén | Igen | Későbbi, nagy volumenre. |

---

## 3. Mit nem csinálunk most (hogy stabil maradjon a jelenlegi rendszer)

- **Nem** építjük be a PaddleOCR-t, scikit-learn-t, rapidfuzz-et, opencv-t a **jelenlegi PDFAI** alkalmazásba (app.py, requirements.txt, Dockerfile).  
- **Nem** cseréljük le a jelenlegi szövegkinyerési láncot (pypdf → pdfplumber → PyMuPDF → Tesseract OCR).  
- **Nem** írunk a meglévő pipeline-ba új branch-et (pl. „ha PaddleOCR van, akkor…”); a jelenlegi PDFAI **egyértelműen** Groq + meglévő extractor.  
- **Nem** kötelező a 200 soros pipeline kódját a repóba commitolni; lehet külön gist, külön repo vagy fork.

---

## 4. Hogyan kísérleteznénk (elfogadott stratégia)

- **Fork vagy külön projekt:** A kísérlet **nem** a main PDFAI-ban történik. Lehet egy **fork** (pl. PDFAI-transcript-ocr) vagy egy teljesen külön repo, ahol szabadon lehet: paddleocr, pdf2image, scikit-learn, rapidfuzz, opencv, a 200 soros pipeline, saját venv, saját Docker.  
- **Értékelés:** Csak akkor kerül szóba visszahozatal / integráció, ha az eredmény **meggyőző** (pl. sok transcripton stabilan jobb vagy legalább hasonló minőség, kevesebb LLM, olcsóbb).  
- **Dokumentáció:** A jelenlegi DOCUMENTATION.md (5.2, 5.3, 5.4) és ez a TRANSCRIPT-PIPELINE-REFERENCE.md együtt adják a referenciát; a 200 soros pipeline és a toolchain **itt vagy a forkban** dokumentált, nem a main app kódjában.  
- **Stabilitás:** A main PDFAI továbbra is egyértelmű célkörnyezet: Groq + meglévő extractor; a failure log, fallback tervek, layout/table trükkök docja továbbra is erre a pipeline-ra vonatkozik, amíg nem döntünk mást.

---

## 5. Rövid összefoglaló

- **Elfogadott:** bounding box OCR, row/column grouping, regex mezők, fuzzy dictionary, validáció, transfer table, page segmentation, hash, preprocessing, PaddleOCR mint referencia, determinisztikus pipeline és layout/table-transformer nagy volumenre – **mind dokumentáció és későbbi / forkos kísérlet szintjén**.  
- **Nem most:** a fenti ötletek beépítése a **jelenlegi** PDFAI-ba; nincs új dependency, nincs pipeline csere.  
- **Hogyan:** fork (vagy külön projekt) → saját toolchain + pipeline → mérés → ha meggyőző, akkor lehet integrációt vagy visszahozatalt megbeszélni.

A 200 soros pipeline **1:1 referencia-ként** a repóban van: [reference/transcript_pipeline_reference.py](reference/transcript_pipeline_reference.py). A main PDFAI ezt nem használja; kísérlethez / forkhoz másolható.
