# Sikertelen futások naplója és finomhangolás

A sikertelen futtatások (Groq hiba, PDF kinyerés, időtúllépés, stb.) **strukturáltan** kerülnek a **data/failure_log.jsonl** fájlba. Cél: ne találgassunk – minden további lépés (prompt, modell, chunk, delay) legyen **a log alapján** döntött.

---

## 1. Mit logolunk sikertelen futáskor?

Mielőtt továbblépünk (és újra próbálkozunk), a következőket tároljuk.

### Minden sikertelen futásnál (endpoint: process-default / upload)

| Mező | Jelentés |
|------|----------|
| `timestamp` | ISO időbélyeg (UTC). |
| `source` | `default` vagy `upload`. |
| `doc_label` | Dokumentum neve / címke. |
| `model_used` | Használt Groq modell (vagy null ha már előtte elbukott). |
| `error_type` | Kategória: lásd lent. |
| `error_message` | A kivétel szövege (felhasználónak is látható). |

**error_type** értékek (automatikusan a hibaüzenetből / kontextusból):

- **groq_429** – Rate limit (429 Too Many Requests).
- **groq_http** – Egyéb Groq HTTP hiba (4xx/5xx).
- **pdf_extract** – Nem sikerült szöveget kinyerni a PDF-ből (vagy OCR hiba).
- **json_parse** – A válasz nem volt értelmezhető JSON.
- **timeout** – Időtúllépés / hálózat.
- **unknown** – Egyéb kivétel.

### Ha a hiba a Groq híváskor keletkezik (429 vagy 4xx/5xx)

Ezeket **a Groq válaszból / header-ekből** írjuk a logba (a fenti sor mellé vagy helyette egy részletesebb sor):

| Mező | Jelentés – mit kérdezünk „a Groq-tól” (a válaszból) |
|------|------------------------------------------------------|
| `status_code` | HTTP státusz (429, 502, 503, stb.). |
| `retry_after_sec` | 429 esetén: a `Retry-After` header (meddig várjunk). |
| `rate_limit_remaining_tokens` | `x-ratelimit-remaining-tokens` (maradék token/perc). |
| `rate_limit_limit_tokens` | `x-ratelimit-limit-tokens` (limit érték). |
| `rate_limit_remaining_requests` | `x-ratelimit-remaining-requests`. |
| `rate_limit_limit_requests` | `x-ratelimit-limit-requests`. |
| `response_snippet` | A válasz body első ~500 karaktere (Groq hibaüzenet, stack trace nélkül). |
| `chunk_index` | Hányadik chunknál történt (1-based). |
| `total_chunks` | Összesen hány chunk (mennyire hosszú a PDF). |
| `pdf_text_length` | A kinyert PDF szöveg hossza (karakter). |

Így utólag látjuk: limit miatt bukott-e, melyik chunknál, milyen üzenettel jött a Groq, és mennyi maradék volt – **finomhangolás bemeneteként** használható (pl. delay növelés, más modell, rövidebb chunk).

---

## 2. Hol van a log?

- **Fájl:** `data/failure_log.jsonl`  
  - Egy sor = egy JSON objektum (JSONL).  
  - A `data/` mappa a Docker volume miatt a hoston (NAS-on) is megmarad.  
  - A fájl **nem** kerül gitbe (`.gitignore`: `data/`).

---

## 3. Folyamat: hogyan biztosítjuk, hogy minden további lépés előtt ezt a logot kielemezzük?

### Szabály (közös megállapodás)

- **Minden olyan lépés előtt**, ami a futások minőségét vagy stabilitását érinti (prompt módosítás, más modell, chunk méret, delay, új Groq tier), **kötelező**:
  1. Megnyitni a **data/failure_log.jsonl** (vagy az utolsó N sort).
  2. **Közösen** (akivel együtt finomhangoltok) átnézni az utolsó sikertelen bejegyzéseket.
  3. Rögzíteni: mi a **minta** (pl. mindig 429 a 2. chunknál; vagy „üres válasz” 70B-nél), és **milyen tanulság** vezet a következő lépéshez (pl. „növeljük a delay-t”, „átváltunk Compoundra”).
  4. Csak **ez után** megtenni a következő változtatást (kód / .env / prompt).

### Gyakorlati checklist (pl. release / finomhangolás előtt)

- [ ] Megnyitva a `data/failure_log.jsonl` (vagy `tail -n 50 data/failure_log.jsonl`).
- [ ] Átnézve az utolsó sikertelen futások: `error_type`, `error_message`, Groq mezők (`status_code`, rate limit, `response_snippet`).
- [ ] Kiemelve a ismétlődő minták (pl. ugyanaz a modell, ugyanolyan hosszú PDF).
- [ ] Leírva 1–2 mondatban a tanulság és a **következő lépés** (mit változtatunk és miért).
- [ ] Csak ezután: kód / .env / prompt módosítás, majd teszt.

Ezt érdemes rögzíteni egy rövid jegyzetben is (pl. „2025-03-12: failure log alapján delay 30→45, modell 8B→Compound; ok: 429 a 2. chunknál, limit 6K TPM”).

---

## 4. Intelligens alterválaszok (fallback) – tervezett, későbbi implementáció

Cél: a **lerohadás** és a nyers hiba helyett – **mindig logolva** – **automatikus, intelligens alternatív válasz**: ha van értelmes fallback, futtassuk le azt, és azt adjuk vissza a felhasználónak (a sikertelent továbbra is rögzítjük a failure_log-ban).

**Jelenleg nincs implementálva;** ez a szekció csak a koncepciót és a későbbi lépés célját dokumentálja. A megvalósítás egy későbbi feladat lesz.

### Példa: rate limit (429) + másik modell

- **Hiba:** Groq 429 (rate limit) a kiválasztott modellnél.
- **Fallback:** Ha van másik, pl. magasabb limitű modell (GROQ_MODELS listában), akkor:
  1. A 429-et **logoljuk** (failure_log.jsonl) a meglévő mezőkkel.
  2. **Ne** adjunk hibát a felhasználónak.
  3. Válasszunk egy **alternatív modellt** (pl. magasabb TPM, vagy a lista következő eleme), és **futtassuk le újra** ugyanazzal a PDF-fel (ugyanaz a szöveg, chunkok).
  4. Ha ez sikeres → azt az eredményt adjuk vissza (opcionálisan jelezve a felületen, hogy „rate limit miatt [X] modell helyett [Y] modell futott”).
  5. Ha az alternatíva is hibázik → akkor logoljuk azt is, és csak ezután adjunk hibát.

Így a felhasználó sok esetben eredményt kap a hiba helyett, a rendszer pedig tanul (log alapján látjuk, melyik modellnél gyakori a 429).

### Egyéb lerohadás-típusok – alterválaszok idővel

A következőket később, lépésről lépésre lehet fallback logikával kiegészíteni (mindig logolva a sikertelent):

| Hiba / lerohadás | Lehetséges fallback (terv) |
|------------------|----------------------------|
| **429 rate limit** | Másik modell (pl. magasabb TPM) választása, újrafuttatás. |
| **Egyéb Groq HTTP (5xx, timeout)** | Rövid várakozás + egy retry; ha van másik modell, azt is kipróbálni. |
| **Üres / rossz JSON válasz** (chunknál) | Ugyanaz a chunk másik modelllel újra; vagy chunk méret csökkentése és újra. |
| **PDF szövegkinyerés sikertelen** | OCR bekapcsolása / más engine (ha még nem próbáltuk), vagy egyértelmű hibaüzenet + „tölts fel szöveges PDF-et”. |
| **Időtúllépés** (egy chunknál) | Retry ugyanazzal a modelllel; ha ismét timeout, másik modell. |

A sorrend és a konkrét szabályok (max retry, melyik modellre váltunk) a failure_log elemzése és a tapasztalat alapján dőlnek el; a doc ezt a irányt rögzíti.

### Implementációs megjegyzés (később)

- A fallback lépések **mindig** írjanak a failure_log-ba (mi bukott, miért váltottunk, mire).
- A felület jelezze, ha fallback miatt más modell futott (opcionális, de ajánlott az átláthatóság miatt).
- Egy későbbi lépésben ebből a dokumentációból implementálunk: először pl. csak a 429 + másik modell esetét, majd a többi típust igény és log alapján.

---

## 5. Rövid összefoglaló

- **Sikertelen futás** → mindig egy bejegyzés a `data/failure_log.jsonl`-ba (futás szintű + ha Groq hiba, akkor Groq válasz/header részletek).
- **Továbblépés előtt** → log együttes átnézése, minta + tanulság, majd a változtatás; így a finomhangolás **nem találgatás**, hanem **log-alapú**.
- **Később:** intelligens alterválaszok (pl. 429 → másik modell, újrafuttatás; egyéb hibákra hasonló fallback-ok), mindig logolva – a koncepció a 4. szakaszban van dokumentálva, implementáció későbbi lépés.
