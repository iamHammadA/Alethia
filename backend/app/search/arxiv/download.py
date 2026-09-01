import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup 
import  pymupdf4llm
import json
from pathlib import Path
import sys
import os

# Dynamically add the root 'Aletheia' directory to sys.path
CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next((p for p in CURRENT_FILE.parents if p.name.lower() == "aletheia"), CURRENT_FILE.parent)

SAVE_DIR = ROOT_DIR / "arXiv papers"
SAVE_DIR.mkdir(parents=True, exist_ok=True)

if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
    
def get_data():
    from backend.app.extraction.extractor import (
    headings_and_text_recognization,
    full_data,
    )
    command = command_gathering()
    encoded_command = urllib.parse.quote(command)
    max_results = 1
    url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_command}&max_results={max_results}"
    
    with urllib.request.urlopen(url) as in_data:
        raw_data = in_data.read().decode("utf-8")
    
    # print(raw_data)
    xml_data = ET.fromstring(raw_data)
    # print(xml_data)
    namespace = {"atom" : "http://www.w3.org/2005/Atom"}

    # Extract direct PDF links straight from XML (No BeautifulSoup required)
    pdf_links = []
    for entry in xml_data.findall("atom:entry", namespace):
        for link in entry.findall("atom:link", namespace):
            if link.attrib.get("title") == "pdf":
                pdf_links.append(link.attrib.get("href"))
                
                
    print(pdf_links)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    for idx, links in enumerate(pdf_links):
        clean_url = links if links.endswith(".pdf") else f"{links}.pdf"
        response = requests.get(clean_url,headers=headers)
        
        if response.status_code == 200:
            pdf_path = SAVE_DIR / f"paper{idx}.pdf"    
            with open(pdf_path, "wb") as pdf_file:
                for chunk in response.iter_content(chunk_size= 1024 * 1024):
                    if chunk:
                        pdf_file.write(chunk)
            headings_and_text_recognization(idx, pdf_path)
        else:
            print("Error")
    json_path = SAVE_DIR / "arxiv_papers_full.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, indent=4, ensure_ascii=False )
    return None
    
    
def command_gathering():
    return input("Enter the topic you want to research on: ")

def pdf_extractor(urls):
    raw_data = requests.get(urls.text)
    html_data = BeautifulSoup(raw_data.text,"html.parser")
    pdf_url = html_data.find('meta', attrs={'name': 'citation_pdf_url'})['content']

    return pdf_url

data = get_data()