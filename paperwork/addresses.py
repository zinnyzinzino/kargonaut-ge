"""Address and company-name comparison for the paperwork agent (pure Python, no AI).

Two documents of one shipment rarely write the same place the same way: "Ln" vs "Lane", ZIP+4 with or
without a dash, a "PO Box" added, a business park name in front, "/PLANT 4" behind, a company name cut off
by a form field. These functions decide whether two strings mean the same place or company, and say why.

What decides an address: the house number, the street name and the 5-digit ZIP (plus the state when both
have one). City spelling is not compared when both ZIPs are there, because the ZIP is the stronger key.

Georgian addresses ("ქ. ბათუმი, ფარნავაზ მეფის ქუჩა №112, საწყობი 3") are written the other way round:
street name, street type, then the number; no ZIP. There the CITY (one of our 8) plays the ZIP's role,
"ქ." before a city means city and after a street name means street, "№112" = "112", and parts like
"საწყობი 3" (warehouse 3) are ignored.
"""
import re

# Street words, written out (USPS standard abbreviations, the ones seen on rate confirmations and BOLs)
ABBREVIATIONS = {
    "st": "street", "str": "street", "rd": "road", "dr": "drive", "ln": "lane", "ave": "avenue",
    "av": "avenue", "blvd": "boulevard", "hwy": "highway", "pkwy": "parkway", "ct": "court",
    "pl": "place", "cir": "circle", "ter": "terrace", "trl": "trail", "sq": "square", "rte": "route",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
    "ste": "suite", "apt": "apartment",
}
STREET_TYPES = {
    "street", "road", "drive", "lane", "avenue", "boulevard", "highway", "parkway", "court", "place",
    "circle", "terrace", "trail", "way", "square", "route",
}
DIRECTIONS = {"north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"}

# Company-name words that say what kind of company it is, not which one
COMPANY_ABBREVIATIONS = {
    "corp": "corporation", "inc": "incorporated", "co": "company", "ltd": "limited",
    "intl": "international", "svcs": "services", "dist": "distribution",
}
GENERIC_COMPANY_WORDS = {
    "the", "corporation", "incorporated", "company", "limited", "llc", "lp", "llp", "plc",
    "logistics", "trucking", "transport", "transportation", "freight", "systems", "services",
    "group", "international", "carriers", "carrier", "express", "lines", "and",
    # Georgian: შპს = LLC, სს = JSC, ი/მ = sole trader, კომპანია, ჯგუფი = group, ლოჯისტიკი = logistics
    "შპს", "სს", "ი", "მ", "კომპანია", "ჯგუფი", "ლოჯისტიკი", "ლოჯისტიკა",
}

# Georgian addresses
_GEORGIAN = re.compile(r"[Ⴀ-ჿ]")
KA_CITIES = {"თბილისი": "Tbilisi", "ქუთაისი": "Kutaisi", "ბათუმი": "Batumi", "ფოთი": "Poti",
             "ზესტაფონი": "Zestafoni", "სამტრედია": "Samtredia", "გორი": "Gori", "რუსთავი": "Rustavi"}
KA_STREET_TYPES = {
    "ქ": "ქუჩა", "ქუჩა": "ქუჩა", "გამზ": "გამზირი", "გამზირი": "გამზირი", "ხეივ": "ხეივანი",
    "ხეივანი": "ხეივანი", "შეს": "შესახვევი", "შესახვევი": "შესახვევი", "ჩიხი": "ჩიხი",
    "გზატკ": "გზატკეცილი", "გზატკეცილი": "გზატკეცილი", "მოედანი": "მოედანი", "აღმართი": "აღმართი",
}

_PO_BOX = re.compile(r"\bp\.?\s*o\.?\s*box\s*#?\s*\d+", re.IGNORECASE)
_ZIP = re.compile(r"\b(\d{5})(?:-?(\d{4}))?\b")
_STATE_ZIP = re.compile(r"\b([a-z]{2})[\s,]+\d{5}(?:-?\d{4})?\b")
_STREET_START = re.compile(r"^\s*(\d+[a-z]?)\s+([a-z].*)$")


def _words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _parse_georgian(text):
    lowered = text.lower()
    # The city (and a "ქ." written before it, which means "city" there), wherever it stands
    city, city_at = None, len(lowered) + 1
    for ka, en in KA_CITIES.items():
        match = re.search(rf"(?<!\w)(?:ქ\.\s*)?(?:{ka}|{en.lower()})(?!\w)", lowered)
        if match and match.start() < city_at:
            city, city_at = en, match.start()
    for ka, en in KA_CITIES.items():
        lowered = re.sub(rf"(?<!\w)(?:ქ\.\s*)?(?:{ka}|{en.lower()})(?!\w)", " ", lowered)

    # Street: the first part that has a street type ("ქ.", "გამზირი", ...) or a number after words;
    # its words up to the house number, the street type written out
    number, street = None, None
    parts = [p for p in re.split(r"[,;/]", lowered) if p.strip()]
    ranked = ([p for p in parts if any(KA_STREET_TYPES.get(w) for w in re.findall(r"\w+", p))]
              + [p for p in parts if re.search(r"[Ⴀ-ჿ]", p) and re.search(r"\d", p)])
    for part in ranked:
        words = []
        for token in re.findall(r"\w+", part):
            if token.isdigit():
                number = token
                break
            if _GEORGIAN.search(token):
                words.append(KA_STREET_TYPES.get(token, token))
        if words:
            street = words
            break
    return {"number": number, "street": street, "zip5": None, "state": None, "city": city, "text": text}


def parse_address(text):
    """Split a written address into the parts that decide whether two addresses are the same place.

    Returns {"number", "street" (list of words, abbreviations written out, cut after the street type),
    "zip5", "state", "city", "text"}; any part can be None when the address doesn't contain it.
    US addresses have no "city" here (the ZIP decides); Georgian ones have no ZIP (the city decides).
    """
    if not text:
        return None
    if _GEORGIAN.search(text):
        return _parse_georgian(text)
    lowered = _PO_BOX.sub(" ", text.lower())

    # ZIP: the last 5- or 9-digit number, if nothing but "USA" follows it (otherwise it's a house number)
    zip5 = None
    zip_matches = list(_ZIP.finditer(lowered))
    if zip_matches:
        last = zip_matches[-1]
        after = lowered[last.end():].replace("usa", "")
        if not re.search(r"[a-z]", after):
            zip5 = last.group(1)
            lowered = lowered[:last.start()] + " " + lowered[last.end():]

    state_match = _STATE_ZIP.search(text.lower()) if zip5 else None
    state = state_match.group(1) if state_match else None

    # Street: the first comma- or slash-separated part that starts with a number followed by a word
    number, street = None, None
    for part in re.split(r"[,/]", lowered):
        match = _STREET_START.match(part)
        if not match:
            continue
        number = match.group(1)
        street = []
        for word in _words(match.group(2)):
            word = ABBREVIATIONS.get(word, word)
            street.append(word)
            if word in STREET_TYPES:
                break
        break

    return {"number": number, "street": street, "zip5": zip5, "state": state, "city": None, "text": text}


def compare_addresses(a, b):
    """Are two written addresses the same place?

    Returns {"result": "same" | "different" | "unclear", "differences": [{"part", "a", "b"}], "reasons": [...]}.
    "differences" is for wording.py (part: zip, state, number, street, direction); "reasons" is the same in
    plain English for the eval's messages. "unclear" means neither a difference nor enough matching parts
    were found (e.g. one side has no street or no ZIP).
    """
    pa, pb = parse_address(a), parse_address(b)
    if not pa or not pb:
        return {"result": "unclear", "differences": [], "reasons": ["one of the addresses is missing"]}

    differences, matched = [], []

    def differ(part, x, y):
        differences.append({"part": part, "a": x, "b": y})

    if pa["zip5"] and pb["zip5"]:
        if pa["zip5"] != pb["zip5"]:
            differ("zip", pa["zip5"], pb["zip5"])
        else:
            matched.append("zip")
    if pa["state"] and pb["state"] and pa["state"] != pb["state"]:
        differ("state", pa["state"].upper(), pb["state"].upper())
    if pa["city"] and pb["city"]:
        if pa["city"] != pb["city"]:
            differ("city", pa["city"], pb["city"])
        else:
            matched.append("city")
    if pa["number"] and pb["number"]:
        if pa["number"] != pb["number"]:
            differ("number", pa["number"], pb["number"])
        else:
            matched.append("number")
    if pa["street"] and pb["street"]:
        dirs_a = set(pa["street"]) & DIRECTIONS
        dirs_b = set(pb["street"]) & DIRECTIONS
        core_a = set(pa["street"]) - DIRECTIONS
        core_b = set(pb["street"]) - DIRECTIONS
        if dirs_a and dirs_b and dirs_a != dirs_b:
            differ("direction", " ".join(sorted(dirs_a)), " ".join(sorted(dirs_b)))
        if core_a and core_b and (core_a <= core_b or core_b <= core_a):
            matched.append("street")
        else:
            differ("street", " ".join(pa["street"]), " ".join(pb["street"]))

    if differences:
        return {"result": "different", "differences": differences,
                "reasons": [f"{d['part']} {d['a']} vs {d['b']}" for d in differences]}
    place_known = any(p[k] for p in (pa, pb) for k in ("zip5", "city"))
    if {"number", "street"} <= set(matched) and ("zip" in matched or "city" in matched or not place_known):
        return {"result": "same", "differences": [], "reasons": []}
    return {"result": "unclear", "differences": [], "reasons": ["not enough of the address to compare"]}


def _company_words(name):
    # "[on]" marks letters an answer key adds to a cut-off name; the document itself doesn't show them.
    # \w+ (not a-z) so Georgian names keep their letters; „“ quotes and punctuation drop out.
    name = re.sub(r"\[[^\]]*\]", "", name or "")
    return [COMPANY_ABBREVIATIONS.get(w, w) for w in re.findall(r"\w+", name.replace("&", " and ").lower())]


def same_company(a, b):
    """Do two company names mean the same company?

    True when, after writing out abbreviations ("Corp." = "Corporation"): one name is the start of the
    other (a name cut off by a form field), or the distinctive words of one are all in the other
    ("Copperfield" = "Copperfield Logistics", "Hollis, Inc." = "Hollis Surgical Inc").
    """
    wa, wb = _company_words(a), _company_words(b)
    if not wa or not wb:
        return False
    ja, jb = " ".join(wa), " ".join(wb)
    shorter, longer = sorted((ja, jb), key=len)
    if len(shorter) >= 4 and longer.startswith(shorter):
        return True
    core_a = set(wa) - GENERIC_COMPANY_WORDS
    core_b = set(wb) - GENERIC_COMPANY_WORDS
    if core_a and core_b:
        return core_a <= core_b or core_b <= core_a
    return ja == jb


def our_names(ours):
    """Our company can have several names (English, Georgian): a string or a list -> a list."""
    return [ours] if isinstance(ours, str) else [n for n in ours if n]


def is_ours(name, ours):
    return bool(name) and any(same_company(name, n) for n in our_names(ours))
