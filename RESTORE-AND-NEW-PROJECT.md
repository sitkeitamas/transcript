# Tag és visszaállítás / új projekt indítása

## Mi van most

- **Commit:** `Stable pre-experiment` (failure log, deploy removal, transcript pipeline reference, docs).
- **Tag:** `stable/pre-experiment` – erre az állapotra mindig vissza lehet állni.

A taget **lokálisan** létrehoztuk. Ha a repót pusholod, a taget is pushold (lásd lent).

---

## 1. Tag pusholása (ha a repó már remote-on van)

Ha a változtatásokat és a taget is fel akarod tenni a jelenlegi GitHub repóba:

```bash
cd /Users/sitkeitamas/Documents/GitHub/PDFAI
git push origin main
git push origin stable/pre-experiment
```

Ha a tag neve tartalmazza a `/`-t, egyes gépeken a push így megy:  
`git push origin "stable/pre-experiment"`

---

## 2. Hogyan állítod vissza erre az állapotra (később)

Ha később (pl. egy sikertelen kísérlet után) **ebbe a repóba** vissza akarsz állni erre a stabil verzióra:

**A) Csak a kódot állítod vissza (a working directory tiszta lesz):**

```bash
cd /path/to/PDFAI
git fetch origin
git checkout stable/pre-experiment
```

Ekkor „detached HEAD” állapotban vagy: a repo a tag pontján áll, nincs aktív branch. Ha ezen a ponton folytatni akarod a munkát (új commitok):

```bash
git checkout -b main-restored
# vagy: git checkout -b main
# majd dolgozol, commitolsz, és ha ezt akarod az új main-ként: git branch -f main main-restored
```

**B) A main branch teljes visszaállítása a tagre (main = tag állapot):**

```bash
cd /path/to/PDFAI
git fetch origin
git checkout main
git reset --hard stable/pre-experiment
```

Figyelem: a `main` lokálisan a tag pontjára áll; minden azt követő commit **lokálisan** elvész, amíg nem pusholsz (és akkor a remote main felülíródik, ha force push-t használsz). Csak akkor csináld, ha tényleg ezt az állapotot akarod main-ként.

---

## 3. Új projekt indítása a kísérlethez (másik könyvtár, esetleg másik GitHub)

Cél: az **új feature-ök** (pl. LLM-mentes pipeline, PaddleOCR) egy **külön projektben** legyenek, hogy a jelenlegi PDFAI beton stabil maradjon.

### A) Új könyvtár + ugyanaz a GitHub repo (branch)

1. **Másik mappába klónozod a repót** (pl. kísérlethez):

```bash
cd ~/Documents/GitHub   # vagy ahova szoktál
git clone https://github.com/sitkeitamas/PDFAI.git PDFAI-experiment
cd PDFAI-experiment
```

2. **Kísérleti branch** – itt dolgozol az új feature-ökkel; a `main` érintetlen marad:

```bash
git checkout -b experiment/llm-free-pipeline
# innen: pip install paddleocr ..., reference pipeline kipróbálása, stb.
git add ...
git commit -m "..."
git push -u origin experiment/llm-free-pipeline
```

A `main` továbbra is a stabil tag körül marad; a kísérlet a `experiment/llm-free-pipeline` branch-en van.

### B) Új könyvtár + **másik** GitHub repo (teljesen külön projekt)

1. **Új üres repo a GitHubon** (pl. `PDFAI-experiment` vagy `transcript-ocr-pipeline`). Ne inicializáld README-mel (üres repo).

2. **Klónozod a jelenlegi PDFAI-t egy új mappába:**

```bash
cd ~/Documents/GitHub
git clone https://github.com/sitkeitamas/PDFAI.git PDFAI-experiment
cd PDFAI-experiment
```

3. **A `stable/pre-experiment` tagból indul a kísérlet** (opcionális, de tiszta kezdet):

```bash
git checkout stable/pre-experiment
git checkout -b main
```

4. **Új remote:** a klónt a **másik** GitHub repóhoz kötöd, és oda pusholod:

```bash
git remote rename origin origin-pdfai
git remote add origin https://github.com/sitkeitamas/PDFAI-experiment.git
git push -u origin main
git push origin stable/pre-experiment
```

Ettől kezdve a **PDFAI-experiment** mappa a **másik** repo `main` branch-jét követi; a kísérleti változtatásokat itt commitolod és pusholod. Az eredeti PDFAI repo változatlan marad.

5. **Ha később meggyőző az eredmény** és vissza akarod hozni valamit a fő PDFAI-ba: cherry-pick, vagy manuális másolás a fő repóba, vagy merge – akkor egyeztetés alapján.

---

## Rövid összefoglaló

| Cél | Parancs / lépés |
|-----|------------------|
| Tag pusholása | `git push origin main` majd `git push origin stable/pre-experiment` |
| Visszaállás erre az állapotra (csak nézés) | `git checkout stable/pre-experiment` |
| Main kemény visszaállítása a tagre | `git checkout main` → `git reset --hard stable/pre-experiment` |
| Kísérlet ugyanabban a repóban (branch) | Klón → `git checkout -b experiment/llm-free-pipeline` → dolgozol, push branch |
| Kísérlet **másik** GitHub repóban | Klón → remote átnevezés + új origin → push main + tag az új repóba |

A tag neve: **`stable/pre-experiment`**.
