import asyncio
import io
import json
import os
import re
from typing import List, Optional, Tuple

from fastapi import FastAPI, File, UploadFile, Form
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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
# Másodperc várakozás chunkok között (429 elkerülésére; pl. 2 RPM = 30 s, magasabb limit = 2–5 s)
GROQ_DELAY_BETWEEN_REQUESTS = int(os.getenv("GROQ_DELAY_BETWEEN_REQUESTS", "30"))

# Groq: egy kérésben max PDF-szöveg (karakter); magasabb rate limit mellett nagyobb chunk = gyorsabb
MAX_PDF_CHARS_PER_REQUEST = 4_000
# Teljes PDF szöveg max hossza (feleslegesen hosszú OCR nem terheli az API-t)
MAX_PDF_TEXT_TOTAL = 50_000


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


app.mount("/static", StaticFiles(directory="static"), name="static")


class GradeRecord(dict):
    """Egyszerű típus annotáció a jegyekhez."""


def _normalize_text(s: str) -> str:
    """Üres vagy csak whitespace = nincs szöveg."""
    return (s or "").strip()


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

    # 4) OCR (szkennelt PDF): pdf2image + pytesseract – csak ha telepítve van
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
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
    except Exception:
        pass

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


async def call_groq_with_pdf_bytes(file_bytes: bytes) -> Tuple[List[GradeRecord], Optional[str], Optional[str]]:
    """
    PDF bájtaiból kinyeri a szöveget és Groq API-val strukturált adatot kér.
    Visszaadja: (records, student_name, institution).
    """
    if not GROQ_API_KEY:
        raise RuntimeError("Hiányzik a GROQ_API_KEY környezeti változó.")

    pdf_text = extract_text_from_pdf(file_bytes)
    if not pdf_text:
        raise RuntimeError(
            "A PDF-ből nem sikerült szöveget kinyerni (pypdf, pdfplumber és PyMuPDF mind üresen tért vissza). "
            "Ha a PDF szkennelt vagy csak képalapú, előbb OCR-rel kell szöveget belőle készíteni, "
            "vagy próbálj egy másik, szöveges PDF-et."
        )

    if len(pdf_text) > MAX_PDF_TEXT_TOTAL:
        pdf_text = pdf_text[:MAX_PDF_TEXT_TOTAL]

    system_prompt = (
        "Tanulmányi eredmény dokumentum szövege. Kinyerni: hallgató neve, intézmény, és minden tárgyra: "
        "tárgy neve, kód, félév, kredit, osztályzat. Válasz CSAK JSON, semmi más:\n"
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

    async with httpx.AsyncClient(timeout=120) as client:
        for i, chunk in enumerate(chunks):
            user_content = f"A dokumentum szövege (rész {i + 1}/{len(chunks)}):\n\n{chunk}\n\nAdd vissza a kért JSON-t."
            payload = {
                "model": GROQ_MODEL,
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
                    if attempt == 0:
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                break
            resp.raise_for_status()
            data = resp.json()
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
            chunk_records = parsed.get("records") or []
            all_records.extend(chunk_records)
            if student_name is None and parsed.get("student_name"):
                student_name = parsed.get("student_name")
            if institution is None and parsed.get("institution"):
                institution = parsed.get("institution")
            # Következő chunk előtt várakozás (rate limit)
            if i < len(chunks) - 1:
                await asyncio.sleep(GROQ_DELAY_BETWEEN_REQUESTS)

    return all_records, student_name, institution


async def call_groq_with_pdf_text(file: UploadFile) -> Tuple[List[GradeRecord], Optional[str], Optional[str]]:
    """Feltöltött fájlból olvas és továbbadja call_groq_with_pdf_bytes-nak."""
    file_bytes = await file.read()
    return await call_groq_with_pdf_bytes(file_bytes)


# ---------- JSON API (egy porton elérhető, reverse proxy 443 mögött) ----------

@app.get("/api/health")
async def api_health():
    return {"status": "healthy", "service": "PDF Eredménykiolvasó", "version": "1.0.0"}


@app.get("/api/default-pdf-info")
async def api_default_pdf_info():
    p = _get_default_pdf_path()
    return {"default_pdf_name": p.name if p else None}


@app.post("/api/process-default", response_model=ProcessResponse)
async def api_process_default():
    error = None
    records: List[GradeRecord] = []
    student_name = None
    institution = None
    raw_json_str = None
    doc_label = None
    default_path = _get_default_pdf_path()
    if not default_path:
        return ProcessResponse(result=[], student_name=None, institution=None, doc_label=None, raw_json=None, error="A pdf/ mappában nincs PDF fájl.")
    try:
        file_bytes = default_path.read_bytes()
        records, student_name, institution = await call_groq_with_pdf_bytes(file_bytes)
        doc_label = default_path.name
        payload = {"student_name": student_name, "institution": institution, "records": records}
        raw_json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as e:
        error = str(e)
    return ProcessResponse(result=records, student_name=student_name, institution=institution, doc_label=doc_label, raw_json=raw_json_str, error=error)


@app.post("/api/upload", response_model=ProcessResponse)
async def api_upload(file: UploadFile = File(...), label: Optional[str] = Form(None)):
    error = None
    records: List[GradeRecord] = []
    student_name = None
    institution = None
    raw_json_str = None
    try:
        records, student_name, institution = await call_groq_with_pdf_text(file)
        payload = {"student_name": student_name, "institution": institution, "records": records}
        raw_json_str = json.dumps(payload, ensure_ascii=False, indent=2)
    except Exception as e:
        error = str(e)
    return ProcessResponse(result=records, student_name=student_name, institution=institution, doc_label=label or file.filename, raw_json=raw_json_str, error=error)


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

