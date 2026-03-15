import asyncio
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from fastapi import FastAPI, File, UploadFile, Form, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

from dotenv import load_dotenv
import httpx
from pypdf import PdfReader

# .env betöltése mindig az app.py mappájából (projekt gyökér)
load_dotenv(Path(__file__).resolve().parent / ".env")

# Logolás: szint env-ből (DEBUG, INFO, WARNING, ERROR), alapértelmezett INFO
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pdfai")

# In-memory log buffer a felület számára (utolsó N sor)
LOG_BUFFER_MAX = 200
_log_buffer: List[str] = []


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            _log_buffer.append(msg)
            while len(_log_buffer) > LOG_BUFFER_MAX:
                _log_buffer.pop(0)
        except Exception:
            pass


_buffer_handler = BufferHandler()
_buffer_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
logger.addHandler(_buffer_handler)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
# Másodperc várakozás chunkok között (429 elkerülésére; pl. 2 RPM = 30 s, magasabb limit = 2–5 s)
GROQ_DELAY_BETWEEN_REQUESTS = int(os.getenv("GROQ_DELAY_BETWEEN_REQUESTS", "30"))

# Groq: egy kérésben max PDF-szöveg (karakter); magasabb rate limit mellett nagyobb chunk = gyorsabb
MAX_PDF_CHARS_PER_REQUEST = 4_000
# Teljes PDF szöveg max hossza (feleslegesen hosszú OCR nem terheli az API-t)
MAX_PDF_TEXT_TOTAL = 50_000

# Groq modellek (ugyanaz az API). Alapértelmezett = GROQ_MODEL env.
# limit_label: felhasználható token/perc (TPM) vagy egyéb limit megjelenítéshez
GROQ_MODELS = [
    {"id": "llama-3.1-8b-instant", "label": "Llama 3.1 8B Instant", "limit_label": "6K TPM"},
    {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B Versatile", "limit_label": "12K TPM"},
    {"id": "groq/compound", "label": "Groq Compound", "limit_label": "70K TPM"},
    {"id": "groq/compound-mini", "label": "Groq Compound Mini", "limit_label": "70K TPM"},
]


# Feldolgozási előzmény: data/processed.json (lista), minden deploy előtt archive-ba másoljuk.
# Docker: mountoljuk ./data -> /app/data, így a NAS-on a host data/ megmarad.
_DATA_ROOT = Path(__file__).resolve().parent
DATA_DIR = _DATA_ROOT / "data"
PROCESSED_FILE = DATA_DIR / "processed.json"
PROCESSED_HISTORY_MAX = 500  # max ennyi bejegyzés marad, régebbiek törlődnek
FAILURE_LOG_FILE = DATA_DIR / "failure_log.jsonl"  # sikertelen futások (finomhangolás bemenete)


def _append_failure_log(entry: dict) -> None:
    """Egy sikertelen futás bejegyzését hozzáfűzi a data/failure_log.jsonl-hez (JSONL: egy sor = egy JSON)."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(FAILURE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
        logger.debug("Failure log: %s", entry.get("error_type", "?"))
    except Exception as e:
        logger.warning("Failure log írás sikertelen: %s", e)


def _infer_error_type(error_message: str) -> str:
    """Hibaüzenet alapján error_type kategória (failure_log és finomhangolás)."""
    msg = (error_message or "").lower()
    if "429" in msg and ("too many" in msg or "limit" in msg):
        return "groq_429"
    if "nem sikerült szöveget" in msg or "pdf-ből nem" in msg or "ocr" in msg or "pdf extract" in msg:
        return "pdf_extract"
    if "json" in msg or "expected pattern" in msg or "nem érvényes" in msg:
        return "json_parse"
    if "timeout" in msg or "időtúllépés" in msg or "abort" in msg:
        return "timeout"
    if "502" in msg or "503" in msg or "5" in msg[:3] or "4" in msg[:3]:
        return "groq_http"
    return "unknown"


def _append_processed_entry(
    *,
    source: str,
    started_at: datetime,
    duration_sec: float,
    doc_label: Optional[str],
    model_used: Optional[str],
    student_name: Optional[str],
    institution: Optional[str],
    result: List[Any],
    error: Optional[str],
) -> None:
    """Egy feldolgozási lépés eredményét hozzáfűzi a data/processed.json-hoz (tesztelési előzmény)."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ended_at = datetime.now(timezone.utc)
        entry = {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_sec": round(duration_sec, 2),
            "source": source,
            "doc_label": doc_label,
            "model_used": model_used,
            "student_name": student_name,
            "institution": institution,
            "result_count": len(result),
            "error": error,
            "result": [dict(r) for r in result],
        }
        history: List[dict] = []
        if PROCESSED_FILE.exists():
            try:
                history = json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                history = []
        if not isinstance(history, list):
            history = []
        history.append(entry)
        if len(history) > PROCESSED_HISTORY_MAX:
            history = history[-PROCESSED_HISTORY_MAX:]
        PROCESSED_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("Előzmény mentve: %s, %d rekord", source, len(result))
    except Exception as e:
        logger.warning("Előzmény mentése sikertelen: %s", e)


def _get_version() -> str:
    """VERSION fájl első sora, vagy 'dev' ha nincs."""
    vpath = Path(__file__).resolve().parent / "VERSION"
    if vpath.exists():
        return vpath.read_text(encoding="utf-8").strip().splitlines()[0].strip() or "dev"
    return "dev"


app = FastAPI(title="PDF Eredménykiolvasó")

# CORS: egy porton (pl. 443 reverse proxy) a UI és API same-origin; más origin is engedélyezhető
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API válasz modell
class ProcessResponse(BaseModel):
    result: list
    student_name: Optional[str]
    institution: Optional[str]
    doc_label: Optional[str]
    raw_json: Optional[str]
    error: Optional[str]
    model_used: Optional[str] = None
    doc_url: Optional[str] = None  # ha alapértelmezett PDF, link megnyitásra/letöltésre
    # Groq tokenhasználat és maradék limit (a válasz usage + rate limit header-ekből)
    usage_total_tokens: Optional[int] = None
    usage_prompt_tokens: Optional[int] = None
    usage_completion_tokens: Optional[int] = None
    rate_limit_remaining_tokens: Optional[int] = None
    rate_limit_remaining_requests: Optional[int] = None
    rate_limit_limit_tokens: Optional[int] = None
    rate_limit_limit_requests: Optional[int] = None


app.mount("/static", StaticFiles(directory="static"), name="static")


class GradeRecord(dict):
    """Egyszerű típus annotáció a jegyekhez."""


def _normalize_text(s: str) -> str:
    """Üres vagy csak whitespace = nincs szöveg."""
    return (s or "").strip()


def _ensure_str(val: Any) -> Optional[str]:
    """Groq néha objektumot ad (pl. institution: {name, url}); stringet várunk."""
    if val is None:
        return None
    if isinstance(val, str):
        return val.strip() or None
    if isinstance(val, dict):
        return (val.get("name") or val.get("title") or "").strip() or str(val)
    return str(val)


def _normalize_record(r: Any) -> GradeRecord:
    """Rekord normalizálása: elfogadott mezőnevek (grade/osztalyzat, stb.) → fix séma."""
    if not isinstance(r, dict):
        return GradeRecord({"course_name": "", "course_code": "", "term": "", "credits": None, "grade": ""})
    get = lambda *keys: next((r.get(k) for k in keys if r.get(k) is not None and str(r.get(k)).strip() != ""), None)
    course_name = get("course_name", "name", "course", "tárgy")
    course_code = get("course_code", "code", "kód")
    term = get("term", "félév", "semester")
    credits_raw = get("credits", "kredit")
    credits = None
    if credits_raw is not None:
        try:
            credits = float(credits_raw) if isinstance(credits_raw, (int, float)) else float(str(credits_raw).replace(",", ".").strip())
        except (ValueError, TypeError):
            credits = str(credits_raw).strip() or None
    grade = get("grade", "osztalyzat", "osztályzat")
    return GradeRecord({
        "course_name": (course_name or "").strip() if course_name else "",
        "course_code": (course_code or "").strip() if course_code else "",
        "term": (term or "").strip() if term else "",
        "credits": credits,
        "grade": (grade or "").strip() if grade else "",
    })


def _flatten_and_normalize_records(parsed: dict) -> List[GradeRecord]:
    """A parsed JSON-ból kiveszi a records listát; ha van beágyazott records, kiflattendeli; minden rekordot normalizál."""
    raw = parsed.get("records")
    if not raw or not isinstance(raw, list):
        return []
    out: List[GradeRecord] = []
    for item in raw:
        if isinstance(item, dict) and item.get("records") and isinstance(item["records"], list):
            for sub in item["records"]:
                out.append(_normalize_record(sub))
        else:
            out.append(_normalize_record(item))
    return out


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    PDF bájtaiból kinyeri a szöveget. Több módszert próbál (pypdf → pdfplumber → PyMuPDF).
    Ha a PDF szkennelt (csak kép), egyik sem ad szöveget – ilyenkor OCR kellene.
    """
    buf = io.BytesIO(file_bytes)

    # 1) pypdf
    try:
        reader = PdfReader(buf)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        text = "\n".join(parts).strip()
        if _normalize_text(text):
            return text
    except Exception:
        pass

    # 2) pdfplumber (gyakran jobb táblázatos / nehéz layoutnál)
    try:
        import pdfplumber
        buf.seek(0)
        with pdfplumber.open(buf) as pdf:
            parts = []
            for page in pdf.pages:
                ptext = (page.extract_text() or "") if page else ""
                parts.append(ptext)
            text = "\n".join(parts).strip()
            if _normalize_text(text):
                return text
    except Exception:
        pass

    # 3) PyMuPDF (fitz) – sok PDF-nél erősebb kinyerés
    try:
        import fitz  # pymupdf
        buf.seek(0)
        doc = fitz.open(stream=buf.read(), filetype="pdf")
        parts = []
        for page in doc:
            parts.append(page.get_text() or "")
        doc.close()
        text = "\n".join(parts).strip()
        if _normalize_text(text):
            return text
    except Exception:
        pass

    # 4) OCR (szkennelt PDF): pdf2image + pytesseract – csak ha telepítve van (tesseract + poppler a rendszeren)
    _ocr_tried = False
    _ocr_error: Optional[str] = None
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
        _ocr_tried = True
        images = convert_from_bytes(file_bytes, dpi=150)
        parts = []
        for img in images:
            try:
                parts.append(pytesseract.image_to_string(img, lang="hun+eng"))
            except pytesseract.TesseractError:
                parts.append(pytesseract.image_to_string(img, lang="eng"))
        text = "\n".join(parts).strip()
        if _normalize_text(text):
            return text
    except ImportError as e:
        _ocr_error = "OCR könyvtárak nincsenek telepítve: " + str(e)
        logger.info("OCR kihagyva (import hiba): %s", e)
    except Exception as e:
        _ocr_error = str(e)
        logger.warning("OCR próba sikertelen: %s", e)

    if _ocr_error:
        logger.warning("PDF szövegkinyerés sikertelen (OCR: %s). Használd szöveges PDF-et vagy telepítsd tesseract+poppler-t.", _ocr_error)

    return ""


def _extract_json_from_response(text: str) -> dict:
    """A válasz szövegből kinyeri a JSON blokkot (code block vagy raw)."""
    text = text.strip()
    # ```json ... ``` blokk
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        return json.loads(m.group(1).strip())
    # Egyetlen { ... } blokk
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    return json.loads(text)


def _get_default_pdf_path() -> Optional[Path]:
    """A pdf/ mappa első (abc szerint) PDF fájljának útvonala, vagy None."""
    # 1) Ha meg van adva környezeti változó, azt használjuk
    env_dir = os.getenv("PDF_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.is_dir():
            pdfs = sorted(p.glob("*.pdf")) or sorted(p.glob("*.PDF"))
            if pdfs:
                return pdfs[0]
        if p.is_file() and p.suffix.lower() == ".pdf":
            return p

    # 2) app.py mappája mellett pdf/ vagy PDF/
    base = Path(__file__).resolve().parent
    for name in ("pdf", "PDF"):
        pdf_dir = base / name
        if pdf_dir.is_dir():
            pdfs = sorted(pdf_dir.glob("*.pdf")) or sorted(pdf_dir.glob("*.PDF"))
            if pdfs:
                return pdfs[0]

    # 3) CWD és szülő mappák
    for cwd in (Path.cwd(), Path.cwd().resolve()):
        for name in ("pdf", "PDF"):
            pdf_dir = cwd / name
            if pdf_dir.is_dir():
                pdfs = sorted(pdf_dir.glob("*.pdf")) or sorted(pdf_dir.glob("*.PDF"))
                if pdfs:
                    return pdfs[0]

    # 4) Felfelé menve keressük meg a pdf mappát (pl. más mappából indították az appot)
    current = base
    for _ in range(10):
        for name in ("pdf", "PDF"):
            pdf_dir = current / name
            if pdf_dir.is_dir():
                pdfs = sorted(pdf_dir.glob("*.pdf")) or sorted(pdf_dir.glob("*.PDF"))
                if pdfs:
                    return pdfs[0]
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _parse_int_header(headers: Any, key: str) -> Optional[int]:
    v = headers.get(key) if hasattr(headers, "get") else None
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


async def call_groq_with_pdf_bytes(file_bytes: bytes, model: Optional[str] = None) -> Tuple[List[GradeRecord], Optional[str], Optional[str], dict]:
    """
    PDF bájtaiból kinyeri a szöveget és Groq API-val strukturált adatot kér.
    model: használandó modell (pl. llama-3.1-8b-instant); None = GROQ_MODEL.
    Visszaadja: (records, student_name, institution, usage_info).
    usage_info: total_tokens, prompt_tokens, completion_tokens, rate_limit_remaining_tokens, stb.
    """
    used_model = (model or GROQ_MODEL).strip() or GROQ_MODEL
    logger.info("Groq feldolgozás indul, modell=%s", used_model)
    if not GROQ_API_KEY:
        logger.error("Hiányzik a GROQ_API_KEY")
        raise RuntimeError("Hiányzik a GROQ_API_KEY környezeti változó.")

    pdf_text = extract_text_from_pdf(file_bytes)
    if not pdf_text:
        logger.warning("PDF-ből nem sikerült szöveget kinyerni")
        raise RuntimeError(
            "A PDF-ből nem sikerült szöveget kinyerni (pypdf, pdfplumber, PyMuPDF és az OCR próba sem adott szöveget, vagy az OCR nincs telepítve). "
            "Ha a PDF szkennelt/képalapú: telepítsd a tesseract-et és a pdf2image-ot a szerverre, vagy küldj be egy már szöveges (pl. OCR-elt) PDF-et."
        )

    logger.info("PDF szöveg hossza: %d karakter, chunkok: %d", len(pdf_text), (len(pdf_text) + MAX_PDF_CHARS_PER_REQUEST - 1) // MAX_PDF_CHARS_PER_REQUEST if len(pdf_text) > MAX_PDF_CHARS_PER_REQUEST else 1)
    if len(pdf_text) > MAX_PDF_TEXT_TOTAL:
        pdf_text = pdf_text[:MAX_PDF_TEXT_TOTAL]

    system_prompt = (
        "Tanulmányi eredmény dokumentum szövege. Kinyerni: hallgató neve, intézmény, és minden tárgyra: "
        "tárgy neve, kód, félév, kredit, osztályzat. "
        "A válasz CSAK az alábbi formátumú JSON legyen. A 'records' egy SIMA tömb: minden tárgy egy külön objektum, NINCS beágyazott 'records'. "
        "Mezőnevek ANGOLUL: course_name, course_code, term, credits, grade (ne használj osztalyzat vagy más nevet). "
        "Példa:\n"
        '{"student_name":null,"institution":null,"records":[{"course_name":"","course_code":"","term":"","credits":null,"grade":""}]}'
    )

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    # Hosszú szöveg darabolása (413 Payload Too Large elkerülésére)
    chunks: List[str] = []
    if len(pdf_text) <= MAX_PDF_CHARS_PER_REQUEST:
        chunks.append(pdf_text)
    else:
        start = 0
        while start < len(pdf_text):
            end = start + MAX_PDF_CHARS_PER_REQUEST
            if end < len(pdf_text):
                # Sortörésnél vágjuk, ne szó közepén
                last_nl = pdf_text.rfind("\n", start, end + 1)
                if last_nl > start:
                    end = last_nl + 1
            chunks.append(pdf_text[start:end])
            start = end

    all_records: List[GradeRecord] = []
    student_name: Optional[str] = None
    institution: Optional[str] = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    last_remaining_tokens: Optional[int] = None
    last_remaining_requests: Optional[int] = None
    last_limit_tokens: Optional[int] = None
    last_limit_requests: Optional[int] = None

    async with httpx.AsyncClient(timeout=120) as client:
        for i, chunk in enumerate(chunks):
            user_content = f"A dokumentum szövege (rész {i + 1}/{len(chunks)}):\n\n{chunk}\n\nAdd vissza a kért JSON-t."
            payload = {
                "model": used_model,
                "max_tokens": 2000,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            }
            # 429 esetén egyszer újrapróbáljuk várakozás után
            for attempt in range(2):
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning("Groq 429 rate limit, várakozás %d s (chunk %d/%d)", wait, i + 1, len(chunks))
                    if attempt == 0:
                        await asyncio.sleep(wait)
                        continue
                    # Sikertelen futás log (Groq 429) – finomhangolás bemenete
                    try:
                        body_snippet = (resp.text() or "")[:500]
                    except Exception:
                        body_snippet = ""
                    _append_failure_log({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "error_type": "groq_429",
                        "model_used": used_model,
                        "chunk_index": i + 1,
                        "total_chunks": len(chunks),
                        "pdf_text_length": len(pdf_text),
                        "status_code": 429,
                        "retry_after_sec": wait,
                        "rate_limit_remaining_tokens": _parse_int_header(resp.headers, "x-ratelimit-remaining-tokens"),
                        "rate_limit_limit_tokens": _parse_int_header(resp.headers, "x-ratelimit-limit-tokens"),
                        "rate_limit_remaining_requests": _parse_int_header(resp.headers, "x-ratelimit-remaining-requests"),
                        "rate_limit_limit_requests": _parse_int_header(resp.headers, "x-ratelimit-limit-requests"),
                        "response_snippet": body_snippet,
                    })
                    raise RuntimeError(
                        "A Groq API limitet elérted (429 Too Many Requests). "
                        "Várj 1–2 percet, vagy válassz magasabb limitű modellt (pl. Compound 70K TPM), majd próbáld újra."
                    )
                break
            # Egyéb HTTP hiba (4xx/5xx): log majd raise
            if resp.status_code >= 400:
                try:
                    body_snippet = (resp.text() or "")[:500]
                except Exception:
                    body_snippet = ""
                _append_failure_log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error_type": "groq_http",
                    "model_used": used_model,
                    "chunk_index": i + 1,
                    "total_chunks": len(chunks),
                    "pdf_text_length": len(pdf_text),
                    "status_code": resp.status_code,
                    "rate_limit_remaining_tokens": _parse_int_header(resp.headers, "x-ratelimit-remaining-tokens"),
                    "rate_limit_limit_tokens": _parse_int_header(resp.headers, "x-ratelimit-limit-tokens"),
                    "response_snippet": body_snippet,
                })
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage") or {}
            total_prompt_tokens += usage.get("prompt_tokens") or 0
            total_completion_tokens += usage.get("completion_tokens") or 0
            total_tokens += usage.get("total_tokens") or 0
            # Rate limit header-ek (Groq: x-ratelimit-remaining-tokens, stb.)
            last_remaining_tokens = _parse_int_header(resp.headers, "x-ratelimit-remaining-tokens")
            last_remaining_requests = _parse_int_header(resp.headers, "x-ratelimit-remaining-requests")
            last_limit_tokens = _parse_int_header(resp.headers, "x-ratelimit-limit-tokens")
            last_limit_requests = _parse_int_header(resp.headers, "x-ratelimit-limit-requests")
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not content:
                if i < len(chunks) - 1:
                    await asyncio.sleep(GROQ_DELAY_BETWEEN_REQUESTS)
                continue
            try:
                parsed = _extract_json_from_response(content)
            except json.JSONDecodeError:
                if i < len(chunks) - 1:
                    await asyncio.sleep(GROQ_DELAY_BETWEEN_REQUESTS)
                continue
            chunk_records = _flatten_and_normalize_records(parsed)
            all_records.extend(chunk_records)
            if student_name is None and parsed.get("student_name"):
                student_name = _ensure_str(parsed.get("student_name"))
            if institution is None and parsed.get("institution"):
                institution = _ensure_str(parsed.get("institution"))
            # Következő chunk előtt várakozás (rate limit)
            if i < len(chunks) - 1:
                await asyncio.sleep(GROQ_DELAY_BETWEEN_REQUESTS)

    if total_tokens == 0 and (total_prompt_tokens or total_completion_tokens):
        total_tokens = total_prompt_tokens + total_completion_tokens
    usage_info = {
        "total_tokens": total_tokens or None,
        "prompt_tokens": total_prompt_tokens or None,
        "completion_tokens": total_completion_tokens or None,
        "remaining_tokens": last_remaining_tokens,
        "remaining_requests": last_remaining_requests,
        "limit_tokens": last_limit_tokens,
        "limit_requests": last_limit_requests,
    }
    logger.info("Groq feldolgozás kész, %d rekord, tokenek: %s", len(all_records), total_tokens or "?")
    return all_records, student_name, institution, usage_info


async def call_groq_with_pdf_text(file: UploadFile) -> Tuple[List[GradeRecord], Optional[str], Optional[str]]:
    """Feltöltött fájlból olvas és továbbadja call_groq_with_pdf_bytes-nak."""
    file_bytes = await file.read()
    return await call_groq_with_pdf_bytes(file_bytes)


# ---------- JSON API (egy porton elérhető, reverse proxy 443 mögött) ----------

@app.get("/api/health")
async def api_health():
    return {"status": "healthy", "service": "PDF Eredménykiolvasó", "version": _get_version()}


@app.get("/api/logs")
async def api_logs():
    """Utolsó N log sor (memóriában), a felület log paneljához."""
    return {"lines": list(_log_buffer)}


@app.get("/api/history")
async def api_history(limit: int = Query(30, ge=1, le=100)):
    """Feldolgozási előzmény (processed.json) az összehasonlításhoz. Visszaadja az utolsó limit bejegyzést."""
    if not PROCESSED_FILE.exists():
        return {"entries": []}
    try:
        data = json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"entries": []}
    if not isinstance(data, list):
        return {"entries": []}
    entries = data[-limit:]
    base = len(data) - len(entries)
    out = []
    for i, e in enumerate(entries):
        out.append({
            "index": base + i,
            "started_at": e.get("started_at") or "",
            "doc_label": e.get("doc_label") or "",
            "source": e.get("source") or "",
            "result_count": e.get("result_count", 0),
            "result": e.get("result") or [],
        })
    return {"entries": out}


@app.get("/api/models")
async def api_models():
    """Elérhető Groq modellek; alapértelmezett = GROQ_MODEL. limit_label = pl. token/perc limit."""
    default_id = GROQ_MODEL
    models = [
        {"id": m["id"], "label": m["label"], "limit_label": m.get("limit_label")}
        for m in GROQ_MODELS
    ]
    return {"default_model": default_id, "models": models}


@app.get("/api/default-pdf-info")
async def api_default_pdf_info():
    p = _get_default_pdf_path()
    name = p.name if p else None
    if name:
        logger.debug("Alapértelmezett PDF: %s", name)
    else:
        logger.debug("Nincs alapértelmezett PDF a pdf/ mappában")
    return {"default_pdf_name": name}


@app.get("/api/default-pdf", response_class=FileResponse)
async def api_default_pdf():
    """Alapértelmezett PDF kiszolgálása (megnyitás/letöltés)."""
    p = _get_default_pdf_path()
    if not p or not p.is_file():
        raise HTTPException(status_code=404, detail="Nincs alapértelmezett PDF")
    return FileResponse(p, filename=p.name, media_type="application/pdf")


@app.post("/api/process-default", response_model=ProcessResponse)
async def api_process_default(model: Optional[str] = Query(None)):
    started_at = datetime.now(timezone.utc)
    used_model = (model or GROQ_MODEL).strip() or GROQ_MODEL
    error = None
    records: List[GradeRecord] = []
    student_name = None
    institution = None
    raw_json_str = None
    doc_label = None
    default_path = _get_default_pdf_path()
    if not default_path:
        logger.warning("process-default: nincs PDF a pdf/ mappában")
        return ProcessResponse(result=[], student_name=None, institution=None, doc_label=None, raw_json=None, error="A pdf/ mappában nincs PDF fájl.", model_used=None, doc_url=None)
    usage_info: dict = {}
    logger.info("process-default indul: fájl=%s, modell=%s", default_path.name, used_model)
    try:
        file_bytes = default_path.read_bytes()
        records, student_name, institution, usage_info = await call_groq_with_pdf_bytes(file_bytes, model=used_model)
        doc_label = default_path.name
        payload = {"student_name": student_name, "institution": institution, "records": records}
        raw_json_str = json.dumps(payload, ensure_ascii=False, indent=2)
        logger.info("process-default kész: %d rekord, doc=%s", len(records), doc_label)
    except Exception as e:
        logger.exception("process-default hiba: %s", e)
        err_str = str(e)
        if "429" in err_str and "Too Many Requests" in err_str:
            error = "A Groq API limitet elérted (429). Várj 1–2 percet, vagy válassz magasabb limitű modellt (pl. Compound), majd próbáld újra."
        else:
            error = err_str
        used_model = None
        # Sikertelen futás log (futás szint) – finomhangolás bemenete (FAILURE-LOG.md)
        _append_failure_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "default",
            "doc_label": default_path.name if default_path else None,
            "model_used": (model or GROQ_MODEL).strip() or GROQ_MODEL,
            "error_type": _infer_error_type(err_str),
            "error_message": err_str[:1000],
        })
    duration_sec = (datetime.now(timezone.utc) - started_at).total_seconds()
    _append_processed_entry(
        source="default",
        started_at=started_at,
        duration_sec=duration_sec,
        doc_label=doc_label,
        model_used=used_model,
        student_name=student_name,
        institution=institution,
        result=records,
        error=error,
    )
    return ProcessResponse(
        result=records, student_name=student_name, institution=institution, doc_label=doc_label,
        raw_json=raw_json_str, error=error, model_used=used_model, doc_url="/api/default-pdf",
        usage_total_tokens=usage_info.get("total_tokens"),
        usage_prompt_tokens=usage_info.get("prompt_tokens"),
        usage_completion_tokens=usage_info.get("completion_tokens"),
        rate_limit_remaining_tokens=usage_info.get("remaining_tokens"),
        rate_limit_remaining_requests=usage_info.get("remaining_requests"),
        rate_limit_limit_tokens=usage_info.get("limit_tokens"),
        rate_limit_limit_requests=usage_info.get("limit_requests"),
    )


@app.post("/api/upload", response_model=ProcessResponse)
async def api_upload(file: UploadFile = File(...), label: Optional[str] = Form(None), model: Optional[str] = Form(None)):
    started_at = datetime.now(timezone.utc)
    used_model = (model or GROQ_MODEL).strip() or GROQ_MODEL
    filename = file.filename or "?"
    logger.info("upload indul: fájl=%s, modell=%s", filename, used_model)
    error = None
    records: List[GradeRecord] = []
    student_name = None
    institution = None
    raw_json_str = None
    doc_label = label or filename
    usage_info: dict = {}
    try:
        file_bytes = await file.read()
        records, student_name, institution, usage_info = await call_groq_with_pdf_bytes(file_bytes, model=used_model)
        payload = {"student_name": student_name, "institution": institution, "records": records}
        raw_json_str = json.dumps(payload, ensure_ascii=False, indent=2)
        logger.info("upload kész: fájl=%s, %d rekord", filename, len(records))
    except Exception as e:
        logger.exception("upload hiba fájl=%s: %s", filename, e)
        err_str = str(e)
        if "429" in err_str and "Too Many Requests" in err_str:
            error = "A Groq API limitet elérted (429). Várj 1–2 percet, vagy válassz magasabb limitű modellt (pl. Compound), majd próbáld újra."
        else:
            error = err_str
        used_model = None
        # Sikertelen futás log (futás szint) – finomhangolás bemenete (FAILURE-LOG.md)
        _append_failure_log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "upload",
            "doc_label": doc_label,
            "model_used": (model or GROQ_MODEL).strip() or GROQ_MODEL,
            "error_type": _infer_error_type(err_str),
            "error_message": err_str[:1000],
        })
    duration_sec = (datetime.now(timezone.utc) - started_at).total_seconds()
    _append_processed_entry(
        source="upload",
        started_at=started_at,
        duration_sec=duration_sec,
        doc_label=doc_label,
        model_used=used_model,
        student_name=student_name,
        institution=institution,
        result=records,
        error=error,
    )
    return ProcessResponse(
        result=records, student_name=student_name, institution=institution, doc_label=doc_label,
        raw_json=raw_json_str, error=error, model_used=used_model, doc_url=None,
        usage_total_tokens=usage_info.get("total_tokens"),
        usage_prompt_tokens=usage_info.get("prompt_tokens"),
        usage_completion_tokens=usage_info.get("completion_tokens"),
        rate_limit_remaining_tokens=usage_info.get("remaining_tokens"),
        rate_limit_remaining_requests=usage_info.get("remaining_requests"),
        rate_limit_limit_tokens=usage_info.get("limit_tokens"),
        rate_limit_limit_requests=usage_info.get("limit_requests"),
    )


# ---------- Web UI: statikus (JS hívja az /api/* végpontokat) ----------

_ROOT = Path(__file__).resolve().parent

@app.get("/", response_class=HTMLResponse)
async def index():
    """Kezdőlap: statikus index.html (JS alapú, az /api/* végpontokat hívja)."""
    return FileResponse(_ROOT / "static" / "index.html")


# Opcionális path prefix (pl. Synology: https://nas.local/pdfai/ -> APP_PREFIX=/pdfai; a proxy továbbítja, az app itt /-ként látja)
APP_PREFIX = (os.getenv("APP_PREFIX") or "").rstrip("/")
if APP_PREFIX:
    _root_app = FastAPI()
    _root_app.mount(APP_PREFIX, app)
    app = _root_app  # így "app:app" egy porton szolgálja a prefixet is

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

