import  pymupdf4llm
from pathlib import Path
import sys

CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next(
    (p for p in CURRENT_FILE.parents if p.name.lower() == "aletheia"),
    CURRENT_FILE.parent,
)

# 2. Define dynamic save directory next to this script
SAVE_DIR = ROOT_DIR / "arXiv papers"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

full_data = {}
def headings_and_text_recognization(idx, pdf_path):
    text = pymupdf4llm.to_markdown(str(pdf_path))
    text = text.replace("*", "")

    data = {}
    heading = ""
    headings = []
    for lines in text.splitlines():
        clean_text = lines.strip()

        if not clean_text:
            continue

        if clean_text.startswith("## ") and not clean_text.startswith("###"):
            data[(clean_text[3::])] = ""
            heading = (clean_text[3::])
            headings.append(heading)
        else:
            if data:
                data[heading] += clean_text
    full_data[f"article{idx}"] = data