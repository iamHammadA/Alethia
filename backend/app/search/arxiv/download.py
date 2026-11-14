import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import pymupdf4llm

CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next((p for p in CURRENT_FILE.parents if p.name.lower() == "alethia"), CURRENT_FILE.parent)
SAVE_DIR = ROOT_DIR / "arXiv papers"
SAVE_DIR.mkdir(parents=True, exist_ok=True)


def get_data(topic: str, max_results: int = 5) -> list[dict]:
    """Retrieve papers from arXiv and extract their PDF text.

    Importing this module never prompts for input or starts a network request.
    """
    topic = topic.strip()
    if not topic:
        raise ValueError("A research topic is required.")
    query = urllib.parse.quote(topic)
    url = (
        "https://export.arxiv.org/api/query?"
        f"search_query=all:{query}&start=0&max_results={max_results}"
        "&sortBy=relevance&sortOrder=descending"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "Alethia/1.0 (scientific literature research)"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        xml_data = ET.fromstring(response.read().decode("utf-8"))
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = xml_data.findall("atom:entry", ns)
    if not entries:
        raise RuntimeError("arXiv returned no papers for this topic.")

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    for old_pdf in SAVE_DIR.glob("paper*.pdf"):
        old_pdf.unlink(missing_ok=True)

    from backend.app.extraction import extractor as text_extractor
    text_extractor.full_data.clear()
    papers = []
    for idx, entry in enumerate(entries):
        links = entry.findall("atom:link", ns)
        pdf_url = next(
            (link.attrib.get("href") for link in links if link.attrib.get("title") == "pdf"),
            None,
        )
        if not pdf_url:
            continue
        paper = {
            "article_key": f"article{idx}",
            "title": entry.findtext("atom:title", default="", namespaces=ns).strip().replace("\n", " "),
            "summary": entry.findtext("atom:summary", default="", namespaces=ns).strip(),
            "arxiv_id": entry.findtext("atom:id", default="", namespaces=ns).rsplit("/", 1)[-1],
            "published": entry.findtext("atom:published", default="", namespaces=ns),
            "authors": [author.findtext("atom:name", default="", namespaces=ns) for author in entry.findall("atom:author", ns)],
            "pdf_url": pdf_url,
        }
        pdf_path = SAVE_DIR / f"paper{idx}.pdf"
        downloaded = requests.get(
            pdf_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Alethia/1.0)"},
            timeout=90,
        )
        downloaded.raise_for_status()
        pdf_path.write_bytes(downloaded.content)
        text_extractor.headings_and_text_recognization(idx, pdf_path)
        papers.append(paper)

    if not papers:
        raise RuntimeError("No downloadable PDF papers were returned by arXiv.")
    with (SAVE_DIR / "arxiv_papers_full.json").open("w", encoding="utf-8") as file:
        json.dump(text_extractor.full_data, file, indent=2, ensure_ascii=False)
    with (SAVE_DIR / "paper_metadata.json").open("w", encoding="utf-8") as file:
        json.dump({paper["article_key"]: paper for paper in papers}, file, indent=2, ensure_ascii=False)
    return papers


def command_gathering() -> str:
    return input("Enter the topic you want to research on: ")


def pdf_extractor(urls):
    from bs4 import BeautifulSoup
    raw_data = requests.get(urls.text, timeout=30)
    raw_data.raise_for_status()
    html_data = BeautifulSoup(raw_data.text, "html.parser")
    tag = html_data.find("meta", attrs={"name": "citation_pdf_url"})
    return tag["content"] if tag else None


if __name__ == "__main__":
    get_data(command_gathering())
