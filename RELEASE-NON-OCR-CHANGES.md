# Nem-OCR módosítások az 1.2.3 utáni release-ekből

A kód most **v1.2.3** állapotban van (OCR/PDF kinyerés változtatások nélkül).

---

## 1. Futtatási időbélyegek a history-ban

**Mit csinált (a későbbi verzióban):** A `run_history` minden bejegyzésébe bekerült: **started_at**, **ended_at**, **duration_sec**.

**Az 1.2.3-ban:** Nincs `run_history` – nincs `processed.json`, nincs `by_hash`, a futtatásokat nem tároljuk. Az időbélyegeknek nincs hová kerülniük. Ha később visszavezeted a „tárolt előzmény” logikát (OCR nélkül), akkor ott meg lehet adni a started_at / ended_at / duration_sec mezőket is.

**Összefoglalva:** 1. most nem megcsinálható, mert nincs history. Később, ha lesz tárolt előzmény, akkor bele lehet tenni az időbélyegeket.

---

## 2. Várakozási szöveg: „néhány percig” — **MEGCSINÁLVA**

A loading overlay szövege most: **„Ez hosszú PDF-nél néhány percig is eltarthat (Groq rate limit). Ne zárd be a lapot.”**  
Frissítve: `static/index.html`, `templates/index.html`.

---

## 3. LLM válasz normalizálás (rekord + prompt) — **MEGCSINÁLVA**

**Probléma:** A modell néha rossz formátumot ad: pl. **osztalyzat** a **grade** helyett, vagy **beágyazott records** (records tömbben még egy records). Emiatt a táblázatban elcsúsznak a mezők (kredit a félév oszlopban, osztályzat üres).

**Mit csinál a 3.:** A backend **normalizálja** a választ: elfogadja az `osztalyzat` mezőt is, kiflattendeli a beágyazott listát, és minden sort fix oszlopokra (course_name, course_code, term, credits, grade) kényszerít. Így a táblázat mindig helyes oszlopokkal jelenik meg, még ha a modell mást ad is.

**Röviden:** Ha a modell néha félreírja a JSON-t vagy más mezőnevet használ, a 3. ezt kijavítja a megjelenés előtt. Nélküle ilyen hibáknál rossz/eltolt sorok látszhatnak.

---

## 4. DEPLOY.md: 404 / reverse proxy szekció — **Már benne van**

**Probléma:** Ha a transcript.sitkeitamas.hu címen 404-et kapsz („A keresett oldal nem található”), a Synology a kérést nem a PDFAI konténerhez (8111) továbbítja.

**Mit csinál a 4.:** A **DEPLOY.md**-be bekerül egy rövid **hibaelhárító szekció**: hogy ellenőrizd, fut-e a konténer, és hogyan állítsd be a **Reverse Proxy**-t a DSM-ben (transcript.sitkeitamas.hu → localhost:8111). Csak dokumentáció, segít, ha később megint 404-et látsz.

**Röviden:** Segédlet a 404 és a NAS reverse proxy beállításához; nem változtat a programon.

---

## Összefoglaló

| # | Módosítás              | Státusz / mire jó |
|---|------------------------|-------------------|
| 1 | Futtatási időbélyegek  | 1.2.3-ban nincs history, később lehet |
| 2 | „néhány percig” szöveg| **Kész** |
| 3 | Rekord normalizálás   | **Kész** (app.py: _normalize_record, _flatten_and_normalize_records, prompt) |
| 4 | 404 / reverse proxy   | **Kész** (DEPLOY.md-ben már szerepel a szekció) |
