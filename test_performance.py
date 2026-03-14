#!/usr/bin/env python3
"""
Teljesítményteszt: alapértelmezett PDF feldolgozása mérésekkel.
Paraméterek a .env-ből (vagy környezeti változók): MAX_PDF_CHARS_PER_REQUEST,
GROQ_DELAY_BETWEEN_REQUESTS, MAX_PDF_TEXT_TOTAL. Futtatás után változtathatod
őket és újrafuttatod, amíg a performans kerek.

Futtatás (projekt gyökeréből):
  python test_performance.py
  GROQ_DELAY_BETWEEN_REQUESTS=5 python test_performance.py
  MAX_PDF_CHARS_PER_REQUEST=8000 python test_performance.py
"""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

# Projekt gyökér, .env betöltése
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

# Konfig (ugyanaz mint app.py, de itt külön olvassuk, hogy .env változtatás azonnal érvényesüljön)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_DELAY = int(os.getenv("GROQ_DELAY_BETWEEN_REQUESTS", "30"))
MAX_CHARS = int(os.getenv("MAX_PDF_CHARS_PER_REQUEST", "4000"))
MAX_TOTAL = int(os.getenv("MAX_PDF_TEXT_TOTAL", "50000"))


def get_default_pdf_path() -> Path | None:
    env_dir = os.getenv("PDF_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.is_dir():
            pdfs = sorted(p.glob("*.pdf")) or sorted(p.glob("*.PDF"))
            if pdfs:
                return pdfs[0]
        if p.is_file() and p.suffix.lower() == ".pdf":
            return p
    base = ROOT
    for name in ("pdf", "PDF"):
        pdf_dir = base / name
        if pdf_dir.is_dir():
            pdfs = sorted(pdf_dir.glob("*.pdf")) or sorted(pdf_dir.glob("*.PDF"))
            if pdfs:
                return pdfs[0]
    return None


def extract_text_from_pdf(file_bytes: bytes) -> str:
    from app import extract_text_from_pdf as app_extract
    return app_extract(file_bytes)


def extract_json_from_response(text: str) -> dict:
    from app import _extract_json_from_response
    return _extract_json_from_response(text)


def build_chunks(pdf_text: str) -> list[str]:
    if len(pdf_text) > MAX_TOTAL:
        pdf_text = pdf_text[:MAX_TOTAL]
    chunks = []
    if len(pdf_text) <= MAX_CHARS:
        chunks.append(pdf_text)
    else:
        start = 0
        while start < len(pdf_text):
            end = start + MAX_CHARS
            if end < len(pdf_text):
                last_nl = pdf_text.rfind("\n", start, end + 1)
                if last_nl > start:
                    end = last_nl + 1
            chunks.append(pdf_text[start:end])
            start = end
    return chunks


async def run_test():
    path = get_default_pdf_path()
    if not path:
        print("Hiba: nincs alapértelmezett PDF (pdf/ mappa vagy PDF_DIR).")
        return
    print(f"PDF: {path.name}")
    print(f"Paraméterek: MAX_CHARS={MAX_CHARS}, DELAY={GROQ_DELAY}s, MAX_TOTAL={MAX_TOTAL}")
    print("-" * 60)

    # 1) Szöveg kinyerés
    t0 = time.perf_counter()
    file_bytes = path.read_bytes()
    pdf_text = extract_text_from_pdf(file_bytes)
    t_extract = time.perf_counter() - t0
    if not pdf_text:
        print("Hiba: nem sikerült szöveget kinyerni a PDF-ből.")
        return
    print(f"Szöveg kinyerés: {t_extract:.2f} s  ({len(pdf_text)} karakter)")

    chunks = build_chunks(pdf_text)
    print(f"Chunkok: {len(chunks)} (max {MAX_CHARS} kar/chunk)")
    print("-" * 60)

    if not GROQ_API_KEY:
        print("Hiba: nincs GROQ_API_KEY.")
        return

    system_prompt = (
        "Tanulmányi eredmény dokumentum szövege. Kinyerni: hallgató neve, intézmény, és minden tárgyra: "
        "tárgy neve, kód, félév, kredit, osztályzat. Válasz CSAK JSON, semmi más:\n"
        '{"student_name":null,"institution":null,"records":[{"course_name":"","course_code":"","term":"","credits":null,"grade":""}]}'
    )
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    total_api = 0.0
    total_delay = 0.0
    all_records = []
    errors = []

    async with httpx.AsyncClient(timeout=120) as client:
        for i, chunk in enumerate(chunks):
            n = i + 1
            user_content = f"A dokumentum szövege (rész {n}/{len(chunks)}):\n\n{chunk}\n\nAdd vissza a kért JSON-t."
            payload = {
                "model": GROQ_MODEL,
                "max_tokens": 2000,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            }
            # API hívás
            t_api_start = time.perf_counter()
            for attempt in range(2):
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    if attempt == 0:
                        await asyncio.sleep(wait)
                        continue
                break
            t_api = time.perf_counter() - t_api_start
            total_api += t_api

            if resp.status_code != 200:
                errors.append(f"Chunk {n}: HTTP {resp.status_code}")
                print(f"  Chunk {n}/{len(chunks)}: HTTP {resp.status_code} ({t_api:.1f}s)")
            else:
                try:
                    data = resp.json()
                    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
                    if not content:
                        print(f"  Chunk {n}/{len(chunks)}: API {t_api:.2f}s  →  üres válasz")
                    else:
                        parsed = extract_json_from_response(content)
                        recs = parsed.get("records") or []
                        all_records.extend(recs)
                        print(f"  Chunk {n}/{len(chunks)}: API {t_api:.2f}s  →  {len(recs)} tárgy")
                except Exception as e:
                    errors.append(f"Chunk {n}: {e}")
                    print(f"  Chunk {n}/{len(chunks)}: hiba {e}")

            # Várakozás a következő chunk előtt
            if i < len(chunks) - 1:
                t_delay_start = time.perf_counter()
                await asyncio.sleep(GROQ_DELAY)
                total_delay += time.perf_counter() - t_delay_start
                print(f"           várakozás {GROQ_DELAY}s")

    total_wall = t_extract + total_api + total_delay
    print("-" * 60)
    print("Összesítés:")
    print(f"  Szöveg kinyerés: {t_extract:.2f}s")
    print(f"  Groq API (összesen): {total_api:.2f}s  (~{total_api / len(chunks):.2f}s / chunk)")
    print(f"  Várakozás (rate limit): {total_delay:.2f}s")
    print(f"  Összes idő: {total_wall:.2f}s  (~{total_wall / 60:.1f} perc)")
    print(f"  Kinyert tárgyak száma: {len(all_records)}")
    if errors:
        print("  Hibák:", errors)
    print()
    print("Paraméterek finomhangolásához módosítsd a .env-t és futtasd újra:")
    print("  GROQ_DELAY_BETWEEN_REQUESTS=5   (kisebb = gyorsabb, de 429 esély)")
    print("  MAX_PDF_CHARS_PER_REQUEST=8000   (nagyobb = kevesebb chunk, de 413 esély)")


if __name__ == "__main__":
    asyncio.run(run_test())
