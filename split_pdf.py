"""
Split a PDF into 5-page chunks for spot-checking scanner output.

Given a page number from main.py's output, find which chunk contains it
and feed that chunk to main.py to verify the result independently.

It allows a human to quickly check the quality of a specific grouping of pages
by hand, without needing to attempt to comb through the entire PDF. 

Usage:
    uv run split_pdf.py <path-to-pdf>

Output:
    <pdf-stem>_chunks/chunk_01_pages_01-05.pdf
    <pdf-stem>_chunks/chunk_02_pages_06-10.pdf
    ...

Example workflow:
    uv run main.py report.pdf
    # → Largest adjusted: page 13
    uv run split_pdf.py report.pdf
    # → chunk_03_pages_11-15.pdf contains page 13
    uv run main.py report_chunks/chunk_03_pages_11-15.pdf
    # new output allows engineer to compare results over 5 pages manually to 
    increase confidence of output across larger document.
"""

import sys
from pathlib import Path

import fitz

CHUNK_SIZE = 5


def split_pdf(pdf_path: Path) -> None:
    out_dir = pdf_path.parent / f"{pdf_path.stem}_chunks"
    out_dir.mkdir(exist_ok=True)

    with fitz.open(pdf_path) as doc:
        total = len(doc)
        num_chunks = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
        pad = len(str(num_chunks))

        for chunk_idx in range(num_chunks):
            first = chunk_idx * CHUNK_SIZE          # 0-based inclusive
            last = min(first + CHUNK_SIZE, total)   # 0-based exclusive

            chunk = fitz.open()
            chunk.insert_pdf(doc, from_page=first, to_page=last - 1)

            # 1-based page numbers in filename for human readability
            label = f"chunk_{chunk_idx + 1:0{pad}d}_pages_{first + 1:04d}-{last:04d}"
            out_path = out_dir / f"{label}.pdf"
            chunk.save(str(out_path))
            chunk.close()

            print(f"  {out_path.name}  (pages {first + 1}–{last} of {total})")

    print(f"\n{num_chunks} chunks written to {out_dir}/")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run split_pdf.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Expected a PDF file, got: {pdf_path.suffix or '(no extension)'}")
        sys.exit(1)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Splitting {pdf_path.name} into {CHUNK_SIZE}-page chunks ...")
    split_pdf(pdf_path)


if __name__ == "__main__":
    main()
