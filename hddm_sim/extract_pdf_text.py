import sys
from pathlib import Path

from pypdf import PdfReader


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python extract_pdf_text.py INPUT_PDF OUTPUT_TXT")

    input_pdf = Path(sys.argv[1])
    output_txt = Path(sys.argv[2])

    reader = PdfReader(str(input_pdf))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"\n\n--- PAGE {i} ---\n{text}")

    output_txt.write_text("".join(pages), encoding="utf-8")
    print(f"pages={len(reader.pages)}")
    print(f"chars={sum(len(p) for p in pages)}")
    print(f"output={output_txt}")


if __name__ == "__main__":
    main()
