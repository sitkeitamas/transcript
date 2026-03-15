#!/usr/bin/env python3
"""
Teszt: a pdf/ mappában lévő PDF fájlok (legfeljebb 3) sorban feldolgozása alapbeállításokkal.
Használat: python test_pdf_folder.py   (a projekt gyökeréből, .env betöltve)
Kimenet: 0 ha mind sikeres, 1 ha valamelyik hibázott.
Minden release előtt opcionálisan futtatható (release.sh kérdezi).
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import List, Tuple

# Projekt gyökér = ahol az app.py van
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# .env betöltése
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app import call_groq_with_pdf_bytes

PDF_DIR = ROOT / "pdf"
MAX_FILES = 3


def get_pdf_list() -> List[Path]:
    """pdf/ mappa első MAX_FILES PDF-je abc szerint."""
    if not PDF_DIR.is_dir():
        return []
    pdfs = sorted(PDF_DIR.glob("*.pdf")) or sorted(PDF_DIR.glob("*.PDF"))
    return pdfs[:MAX_FILES]


async def run_one(p: Path) -> Tuple[bool, str]:
    """Egy PDF feldolgozása alapbeállításokkal (model=None). Vissza: (siker, üzenet)."""
    try:
        file_bytes = p.read_bytes()
        records, student_name, institution, usage_info = await call_groq_with_pdf_bytes(
            file_bytes, model=None
        )
        n = len(records)
        return True, f"OK — {n} rekord"
    except Exception as e:
        return False, str(e)


async def main() -> int:
    pdfs = get_pdf_list()
    if not pdfs:
        print("Nincs PDF a pdf/ mappában.")
        return 1
    print(f"PDF mappa: {PDF_DIR}")
    print(f"Feldolgozandó: {len(pdfs)} fájl (max {MAX_FILES})")
    if not os.getenv("GROQ_API_KEY"):
        print("Hiba: nincs GROQ_API_KEY (.env)")
        return 1
    failed = 0
    for i, p in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] {p.name} ...", end=" ", flush=True)
        ok, msg = await run_one(p)
        if ok:
            print(msg)
        else:
            print("HIBA:", msg)
            failed += 1
    print()
    if failed:
        print(f"Összesen: {failed} hibás, {len(pdfs) - failed} sikeres.")
        return 1
    print("Mindegyik PDF feldolgozva sikeresen.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
