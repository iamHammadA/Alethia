import spacy
from claim_extractor import analyzer
import re

nlp = spacy.load("en_core_web_lg")

all_claims = analyzer()

def extract_svo(text):
    doc = nlp(text)
    verbs = []
    subjects = []
    objects = []
    
    for token in doc:
        if token.pos_ in ["VERB","AUX"]:
            verbs.append(token.lemma_)
        if token.dep_ in ["nsubj", "nsubjpass"]:
            subj = " ".join([child.text for child in token.lefts if child.dep_ in ["compound", "amod"]] + [token.text])
            subjects.append(subj)
        if token.dep_ in ["dobj", "pobj", "attr", "obj", "obl", "prep", "xcomp", "ccomp"]:
            obj = " ".join([child.text for child in token.lefts if child.dep_ in ["compound", "amod"]] + [token.text])
            objects.append(obj)
       
    return{
        "sentence" : text,
        "verbs" : verbs,
        "subjects" : subjects,
        "objects" : objects
    }

def weight_calculator(text,sent_svo):
    
    verb_strength = 0

    strong_strength = re.compile(
        r"\b(?:"
        r"assert|asserts|asserted|asserting|"
        r"prove|proves|proved|proving|"
        r"demonstrate|demonstrates|demonstrated|demonstrating|"
        r"establish|establishes|established|establishing|"
        r"confirm|confirms|confirmed|confirming|"
        r"verify|verifies|verified|verifying|"
        r"guarantee|guarantees|guaranteed|guaranteeing|"
        r"dictate|dictates|dictated|dictating|"
        r"determine|determines|determined|determining|"
        r"validate|validates|validated|validating|"
        r"substantiate|substantiates|substantiated|substantiating|"
        r"corroborate|corroborates|corroborated|corroborating|"
        r"ascertain|ascertains|ascertained|ascertaining|"
        r"mandate|mandates|mandated|mandating"
        r")\b",
        re.IGNORECASE,
    )

    medium_strength = re.compile(
        r"\b(?:"
        r"indicate|indicates|indicated|indicating|"
        r"suggest|suggests|suggested|suggesting|"
        r"show|shows|showed|showing|"
        r"support|supports|supported|supporting|"
        r"argue|argues|argued|arguing|"
        r"maintain|maintains|maintained|maintaining|"
        r"contend|contends|contended|contending|"
        r"propose|proposes|proposed|proposing|"
        r"imply|implies|implied|implying|"
        r"reveal|reveals|revealed|revealing|"
        r"disclose|discloses|disclosed|disclosing|"
        r"reflect|reflects|reflected|reflecting|"
        r"convey|conveys|conveyed|conveying|"
        r"posit|posits|posited|positing"
        r")\b",
        re.IGNORECASE,
    )

    low_strength = re.compile(
        r"\b(?:"
        r"hint|hints|hinted|hinting|"
        r"insinuate|insinuates|insinuated|insinuating|"
        r"speculate|speculates|speculated|speculating|"
        r"postulate|postulates|postulated|postulating|"
        r"conjecture|conjectures|conjectured|conjecturing|"
        r"surmise|surmises|surmised|surmising|"
        r"hypothesize|hypothesizes|hypothesized|hypothesizing|"
        r"intimate|intimates|intimated|intimating|"
        r"allude|alludes|alluded|alluding|"
        r"suspect|suspects|suspected|suspecting|"
        r"presume|presumes|presumed|presuming|"
        r"suppose|supposes|supposed|supposing|"
        r"theorize|theorizes|theorized|theorizing|"
        r"wonder|wonders|wondered|wondering"
        r")\b",
        re.IGNORECASE,
    )
        
    has_strong_verb = bool(strong_strength.search(text))
    has_medium_verb = bool(medium_strength.search(text))
    has_low_verb = bool(low_strength.search(text))
    
    if has_strong_verb:
        verb_strength = 0.35
    elif has_medium_verb:
        verb_strength = 0.25
    elif has_low_verb:
        verb_strength = 0.10
    else:
        verb_strength = 0.15
    
    has_numbers = bool(re.search(r'\b\d+(\.\d+)?%?\b', text))
    has_metrics = bool(re.search(r'\b(p-value|accuracy|precision|recall|dataset|increase|decrease|fold|margin)\b', text, re.I))
    
    metrics_strength = 0
    
    if has_numbers and has_metrics:
        metrics_strength = 0.15
    elif has_numbers or has_metrics:
        metrics_strength = 0.10
    
    score_svo = 0
    if sent_svo["subjects"] and sent_svo["objects"]:
        score_svo = 0.15
    elif sent_svo["subjects"] or sent_svo["objects"]:
        score_svo = 0.15
    else:
        score_svo = 0
        
    total_weight = round(verb_strength + metrics_strength + score_svo, 3)
    
    weights = [total_weight, verb_strength, metrics_strength, score_svo]
    
    return weights

def claim_type_identifier(doc):
    text = doc.text if hasattr(doc, "text") else str(doc)
    
    performance_pattern = re.compile(
        r"\b(?:"
        r"outperform|outperforms|outperformed|outperforming|"
        r"exceed|exceeds|exceeded|exceeding|"
        r"surpass|surpasses|surpassed|surpassing|"
        r"accelerate|accelerates|accelerated|accelerating|"
        r"optimize|optimizes|optimized|optimizing|"
        r"scale|scales|scaled|scaling|"
        r"achieve|achieves|achieved|achieving|"
        r"boost|boosts|boosted|boosting|"
        r"maximize|maximizes|maximized|maximizing|"
        r"minimize|minimizes|minimized|minimizing|"
        r"reduce|reduces|reduced|reducing|"
        r"improve|improves|improved|improving|"
        r"enhance|enhances|enhanced|enhancing"
        r")\b",
        re.IGNORECASE,
    )
    method_pattern = re.compile(
        r"\b(?:"
        r"propose|proposes|proposed|proposing|"
        r"introduce|introduces|introduced|introducing|"
        r"develop|develops|developed|developing|"
        r"design|designs|designed|designing|"
        r"implement|implements|implemented|implementing|"
        r"construct|constructs|constructed|constructing|"
        r"formulate|formulates|formulated|formulating|"
        r"devise|devises|devised|devising|"
        r"present|presents|presented|presenting|"
        r"engineer|engineers|engineered|engineering|"
        r"employ|employs|employed|employing|"
        r"apply|applies|applied|applying|"
        r"utilize|utilizes|utilized|utilizing"
        r")\b",
        re.IGNORECASE,
    )
    result_pattern = re.compile(
        r"\b(?:"
        r"yield|yields|yielded|yielding|"
        r"obtain|obtains|obtained|obtaining|"
        r"find|finds|found|finding|"
        r"observe|observes|observed|observing|"
        r"reveal|reveals|revealed|revealing|"
        r"disclose|discloses|disclosed|disclosing|"
        r"produce|produces|produced|producing|"
        r"demonstrate|demonstrates|demonstrated|demonstrating|"
        r"show|shows|showed|showing|"
        r"record|records|recorded|recording|"
        r"measure|measures|measured|measuring"
        r")\b",
        re.IGNORECASE,
    )
    comparison_pattern = re.compile(
        r"\b(?:"
        r"compare|compares|compared|comparing|"
        r"contrast|contrasts|contrasted|contrasting|"
        r"differ|differs|differed|differing|"
        r"benchmark|benchmarks|benchmarked|benchmarking|"
        r"parallel|parallels|paralleled|paralleling|"
        r"match|matches|matched|matching|"
        r"differentiate|differentiates|differentiated|differentiating|"
        r"distinguish|distinguishes|distinguished|distinguishing|"
        r"vary|varies|varied|varying"
        r")\b",
        re.IGNORECASE,
    )
    causal_pattern = re.compile(
        r"\b(?:"
        r"cause|causes|caused|causing|"
        r"lead|leads|led|leading|"
        r"result|results|resulted|resulting|"
        r"trigger|triggers|triggered|triggering|"
        r"affect|affects|affected|affecting|"
        r"influence|influences|influenced|influencing|"
        r"impact|impacts|impacted|impacting|"
        r"induce|induces|induced|inducing|"
        r"stem|stems|stemmed|stemming|"
        r"drive|drives|drove|driven|driving|"
        r"correlate|correlates|correlated|correlating"
        r")\b",
        re.IGNORECASE,
    )
    hypothesis_pattern = re.compile(
        r"\b(?:"
        r"hypothesize|hypothesizes|hypothesized|hypothesizing|"
        r"postulate|postulates|postulated|postulating|"
        r"conjecture|conjectures|conjectured|conjecturing|"
        r"speculate|speculates|speculated|speculating|"
        r"surmise|surmises|surmised|surmising|"
        r"assume|assumes|assumed|assuming|"
        r"theorize|theorizes|theorized|theorizing|"
        r"presume|presumes|presumed|presuming|"
        r"positing|posits|posited|positing"
        r")\b",
        re.IGNORECASE,
    )
    observation_pattern = re.compile(
        r"\b(?:"
        r"observe|observes|observed|observing|"
        r"note|notes|noted|noting|"
        r"witness|witnesses|witnessed|witnessing|"
        r"detect|detects|detected|detecting|"
        r"discern|discerns|discerned|discerning|"
        r"perceive|perceives|perceived|perceiving|"
        r"identify|identifies|identified|identifying|"
        r"spot|spots|spotted|spotting|"
        r"document|documents|documented|documenting"
        r")\b",
        re.IGNORECASE,
    )
    limitation_pattern = re.compile(
        r"\b(?:"
        r"limit|limits|limited|limiting|"
        r"restrict|restricts|restricted|restricting|"
        r"constrain|constrains|constrained|constraining|"
        r"fail|fails|failed|failing|"
        r"lacks|lacked|lacking|"
        r"hinder|hinders|hindered|hindering|"
        r"impair|impairs|impaired|impairing|"
        r"suffer|suffers|suffered|suffering|"
        r"fall short|falls short|fell short|falling short|"
        r"bottleneck|bottlenecks|bottlenecked|bottlenecking"
        r")\b",
        re.IGNORECASE,
    )
    if performance_pattern.search(text):
        return "performance" 
    elif method_pattern.search(text):
        return "method"
    elif result_pattern.search(text):
        return "result"
    elif causal_pattern.search(text):
        return "causal"     
    elif comparison_pattern.search(text):
        return "comparison"
    elif hypothesis_pattern.search(text):
        return "hypothesis"
    elif observation_pattern.search(text):
        return "observation"
    elif limitation_pattern.search(text):
        return "limitation"
    else:
        return "unknown"
    
def main_function():
    claim_normalized = {}
    for article_id in all_claims:
        claims_list = (all_claims[article_id]["claim"])
        claim_inter_normalization = []
        for claims in claims_list:
            text = (claims["text"])
            text = re.sub(r'^\d{1,2}\s*[A-Z][a-zA-Z\s\-]{3,40}(?=[A-Z])', '', text)
            text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
            text = re.sub(r'([a-zA-Z])(\d+)([A-Z])', r'\1 \3', text)
            section = (claims["section"])
            sent_svo = extract_svo(text)
            weight = weight_calculator(text,sent_svo)
            doc = nlp(text)
            claim_type = claim_type_identifier(doc)
            
            claim_inter_normalization.append({
                "text" : text,
                "section" : section,
                "subject" : sent_svo["subjects"],
                "verb" : sent_svo["verbs"],
                "object" : sent_svo["objects"],
                "claim_type" : claim_type,
                "verb_weight" : weight[1],
                "metrics_weight" : weight[2],
                "score_svo" : weight[3],
                "total_weight" : weight[0]
            })
        claim_normalized[f"{article_id}"]= claim_inter_normalization
    return claim_normalized