import re
import json
import nltk
import os
from pathlib import Path
import sys


CURRENT_FILE = Path(__file__).resolve()
ROOT_DIR = next(
    (p for p in CURRENT_FILE.parents if p.name.lower() == "aletheia"),
    CURRENT_FILE.parent,
)

# 2. Target the 'arXiv papers' folder inside ALETHEIA
SAVE_DIR = ROOT_DIR / "arXiv papers"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.search.arxiv.download import get_data

try:
    nltk.data.find('tokenizers/punkt_tab/english/')
except LookupError:
    nltk.download('punkt_tab', quiet=True)

def json_importer():
    json_file_path = SAVE_DIR / "arxiv_papers_full.json"
    with open(json_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # print(data)
    return data

def sent_normalizer(cleaned_line):
    # remove html code block and comments
    text = re.sub(r'<!--.*?-->', '', cleaned_line, flags=re.DOTALL)
    # 2. Remove HTML tags (<br>, <sup>, etc.)
    text = re.sub(r'<[^>]+>', ' ', text)
    # 3. Clean figure/table titles stuck to text
    text = re.sub(r'Figure \d+:.*', '', text)
    # 4. Clean the tables
    text = re.sub(r'\|.*?\|', ' ', text)
    text = re.sub(r'\|[_\-\s:]+\|', ' ', text)
    text = re.sub(r'(?<!\n)(###+)', r'\n\1', text)
    text = re.sub(r'(?<=[.!?])(?=[A-Z])', r'\n', text)
    # 5. Clean the caption/heading
    text = re.sub(r'(_?Table \d+\._?|Table \d+:?)', ' ', text, flags=re.IGNORECASE)
    # 4. Remove glued page footers/headers
    text = re.sub(r'Here are\d+Is.*?\b', '', text)
    # 6. Fix glued punctuation and list items
    text = re.sub(r'(?<=[.:!?])(?=[A-Za-z0-9])', ' ', text)
    # normalize the spacing of sentence
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)



def analyzer():
    # get_data()
    all_claims= {}
    overall_structure = {}
    definitive_verbs_regex = re.compile(
        r"\b(?:"
        r"assert|asserts|asserted|asserting|"
        r"prove|proves|proved|proven|proving|"
        r"demonstrate|demonstrates|demonstrated|demonstrating|"
        r"establish|establishes|established|establishing|"
        r"confirm|confirms|confirmed|confirming|"
        r"verify|verifies|verified|verifying|"
        r"substantiate|substantiates|substantiated|substantiating|"
        r"validate|validates|validated|validating|"
        r"conclude|concludes|concluded|concluding|"
        r"claim|claims|claimed|claiming|"
        r"argue|argues|argued|arguing|"
        r"state|states|stated|stating|"
        r"declare|declares|declared|declaring|"
        r"maintain|maintains|maintained|maintaining|"
        r"contend|contends|contended|contending|"
        r"insist|insists|insisted|insisting|"
        r"affirm|affirms|affirmed|affirming|"
        r"allege|alleges|alleged|alleging|"
        r"posit|posits|posited|positing|"
        r"postulate|postulates|postulated|postulating|"
        r"propose|proposes|proposed|proposing|"
        r"suggest|suggests|suggested|suggesting|"
        r"indicate|indicates|indicated|indicating|"
        r"show|shows|showed|shown|showing|"
        r"reveal|reveals|revealed|revealing|"
        r"disclose|discloses|disclosed|disclosing|"
        r"express|expresses|expressed|expressing|"
        r"profess|professes|professed|professing|"
        r"avow|avows|avowed|avowing|"
        r"attest|attests|attested|attesting|"
        r"testify|testifies|testified|testifying|"
        r"certify|certifies|certified|certifying|"
        r"warrant|warrants|warranted|warranting|"
        r"corroborate|corroborates|corroborated|corroborating|"
        r"endorse|endorses|endorsed|endorsing|"
        r"uphold|upholds|upheld|upholding|"
        r"support|supports|supported|supporting|"
        r"back|backs|backed|backing|"
        r"hypothesize|hypothesizes|hypothesized|hypothesizing|"
        r"conjecture|conjectures|conjectured|conjecturing|"
        r"speculate|speculates|speculated|speculating|"
        r"surmise|surmises|surmised|surmising|"
        r"infer|infers|inferred|inferring|"
        r"deduce|deduces|deduced|deducing|"
        r"reason|reasons|reasoned|reasoning|"
        r"hold|holds|held|holding|"
        r"reckon|reckons|reckoned|reckoning|"
        r"opine|opines|opined|opining"
        r")\b",
        re.IGNORECASE,
    )

    background_verbs_regex = re.compile(
        r"\b(?:"
        r"cite|cites|cited|citing|"
        r"report|reports|reported|reporting|"
        r"observe|observes|observed|observing|"
        r"note|notes|noted|noting|"
        r"discuss|discusses|discussed|discussing|"
        r"define|defines|defined|defining|"
        r"consist|consists|consisted|consisting|"
        r"comprise|comprises|comprised|comprising|"
        r"represent|represents|represented|representing|"
        r"characterize|characterizes|characterized|characterizing|"
        r"measure|measures|measured|measuring|"
        r"calculate|calculates|calculated|calculating|"
        r"refer|refers|referred|referring"
        r")\b",
        re.IGNORECASE,
    )

    # Robust structural noise filter to block cross-references and formatting debris
    noise_filter_regex = re.compile(
        r"(?:Table \d+|Figure \d+|Section \d+|Appendix|[Hh]ttp[s]?://|[Uu][Rr][Ll])",
        re.IGNORECASE
    )
    data = json_importer()
    
    for article_id in data:
        article = data[article_id]
        overall_structure = {"claim": []}
        
        for section_heading, text in article.items():
            incremented_text = ""
            if section_heading.lower() in ["references", "acknowledgements"]:
                continue
            text = sent_normalizer(text)
            
            for para in text.splitlines():
                sentences = nltk.sent_tokenize(para)
                for line in sentences:
                    if len(line.split()) < 6 or noise_filter_regex.search(line):
                        continue 
                    should_matches = bool(definitive_verbs_regex.search(line))
                    should_not_match = bool(background_verbs_regex.search(line))
                    if should_matches and not should_not_match:
                        overall_structure["claim"].append({"text":line,
                                                          "section" :section_heading})
        all_claims[f"{article_id}"] = overall_structure
    return all_claims
    
analyzer()