#!/usr/bin/env python3
"""
Teszt: PDF szöveg kinyerése + Groq hívás különböző chunk méretekkel.
Futtatás: a projekt gyökeréből: python test_groq_limit.py
"""
import asyncio
import io
import json
import os
import sys
from pathlib import Path

# projekt gyökér
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).resolve().parent / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

# Ugyanaz a kinyerés, mint app.py (egyszerűsítve, csak pypdf + fitz)
def extract_text(file_path: Path) -> str:
    data = file_path.read_bytes()
    buf = io.BytesIO(data)
    try:
        from pypdf import PdfReader
        reader = PdfReader(buf)
        parts = [p.extract_text() or "" for p in reader.pages]
        text = "\n".join(parts).strip()
        if text:
            return text
    except Exception:
        pass
    try:
        import fitz
        buf.seek(0)
        doc = fitz.open(stream=buf.read(), filetype="pdf")
        text = "\n".join(p.get_text() or "" for p in doc).strip()
        doc.close()
        if text:
            return text
    except Exception:
        pass
    return ""


async def try_groq(chunk: str, label: str) -> bool:
    """Egy chunkot elküld Groq-nak. True = OK, False = 413 vagy hiba."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    system = 'Tanulmányi eredmény. Kinyerni: hallgató, intézmény, tárgyak (név, kód, félév, kredit, jegy). Válasz csak JSON: {"student_name":null,"institution":null,"records":[{"course_name":"","course_code":"","term":"","credits":null,"grade":""}]}'
    payload = {
        "model": GROQ_MODEL,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Dokumentum rész:\n\n{chunk}\n\nAdd vissza a JSON-t."},
        ],
    }
    body_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 413:
            print(f"  {label}: 413 (body ~{body_bytes} bytes, {len(chunk)} chars)")
            return False
        if resp.status_code != 200:
            print(f"  {label}: HTTP {resp.status_code} - {resp.text[:200]}")
            return False
        print(f"  {label}: OK (body ~{body_bytes} bytes, {len(chunk)} chars)")
        return True


async def main():
    pdf_dir = Path(__file__).resolve().parent / "pdf"
    pdfs = list(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print("Nincs PDF a pdf/ mappában.")
        return
    path = pdfs[0]
    print(f"PDF: {path.name}")
    text = extract_text(path)
    if not text:
        print("Nem sikerült szöveget kinyerni.")
        return
    print(f"Kinyert szöveg: {len(text)} karakter\n")

    if not GROQ_API_KEY:
        print("Hiányzik GROQ_API_KEY a .env-ből.")
        return

    # Kipróbáljuk különböző méreteket; 429 (rate limit) miatt max 2 kérés/perc
    for size in [1000, 1500, 2000, 3000]:
        if size > len(text):
            chunk = text[:len(text)]
        else:
            chunk = text[:size]
        ok = await try_groq(chunk, f"chunk {size} chars")
        if not ok:
            print(f"\n→ Működő limit: legfeljebb ~{max(400, size - 300)} karakter.")
            break
        await asyncio.sleep(32)  # Groq RPM limit miatt várunk
    else:
        print("\n→ 3000 karakter is OK.")


if __name__ == "__main__":
    asyncio.run(main())
