"""„აღწერეთ ტვირთი“: a shipper writes, pastes (a Facebook or Viber message) or says what they need, and the AI reads
it into the new-load form. Nothing is saved: the form fills, the shipper checks it and presses „გამოქვეყნება“.

Same rule as everywhere: Gemini only reads (one JSON answer); Python checks every value with the chat's own guards
(ai/common.py) and drops what the user never said, so the form shows it as missing instead of a guess:
  - a weight, price or number of pieces must be a number the user wrote ("3 ტონა" counts as 3000 kg)
  - a city must be named in the text (no "probably from Tbilisi")
  - the pickup day must be the user's own words; "დღეს", "ხვალ", "ზეგ" and weekdays are turned into a date by
    Python, not by the model's arithmetic
  - with no truck type named, Python suggests the cheapest type that can carry the weight (core/pricing.py)
Voice: the browser records, the server sends the audio to Gemini for a transcript; the transcript goes back into the
text box (the user sees what was heard) and is then read like typed text.
"""
import os
import re
from datetime import date, timedelta

from ai.common import date_said, hazmat_said, number_said
from core.geo import CITIES, CITY_KA, CITY_STEMS_KA, city
from number_check import _numbers
from core.pricing import compare_types
from core.vehicles import TRUCK_LABEL, TRUCK_TYPES, TRUCK_WORDS_KA, truck_type

MAX_TEXT = 2000
# Voice: gemini-3.6-flash answered every recording with 504 (27 Nov, 3 of 3), the preview in 2-3 s
VOICE_MODELS = [m.strip() for m in os.getenv("KARGONAUT_VOICE_MODELS", "").split(",") if m.strip()] or [
    "gemini-3-flash-preview", "gemini-3.1-flash-lite"]
# Words that name a truck type, so a type the model says was "named" really is in the text (Georgian stems are in
# core/vehicles.py TRUCK_WORDS_KA)
TYPE_WORDS_EN = {"dry_van": ["dry van", "tent", "curtain"], "refrigerated": ["refrigerat", "reefer", "fridge"],
                 "flatbed": ["flatbed", "platform"], "box_truck": ["box truck"], "sprinter_van": ["sprinter", "minivan"]}

SCHEMA = {
    "type": "object",
    "properties": {
        "origin_city": {"type": ["string", "null"]},
        "destination_city": {"type": ["string", "null"]},
        "truck_type": {"type": "string", "enum": [TRUCK_LABEL[t] for t in TRUCK_TYPES] + ["none"]},
        "truck_type_reason": {"type": "string", "enum": ["named", "cargo_needs_cold", "none"]},
        "weight_kg": {"type": ["number", "null"]},
        "pickup_date": {"type": ["string", "null"]},
        "pickup_date_words": {"type": ["string", "null"]},
        "deliver_by": {"type": ["string", "null"]},
        "deliver_by_words": {"type": ["string", "null"]},
        "price_gel": {"type": ["number", "null"]},
        "cargo": {"type": ["string", "null"]},
        "pieces": {"type": ["integer", "null"]},
        "piece_length_m": {"type": ["number", "null"]},
        "piece_width_m": {"type": ["number", "null"]},
        "piece_height_m": {"type": ["number", "null"]},
        "pickup_address": {"type": ["string", "null"]},
        "delivery_address": {"type": ["string", "null"]},
        "needs_liftgate": {"type": ["boolean", "null"]},
        "no_stacking": {"type": ["boolean", "null"]},
        "hazmat": {"type": ["boolean", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["origin_city", "destination_city", "truck_type", "truck_type_reason", "weight_kg", "pickup_date",
                 "pickup_date_words", "deliver_by", "deliver_by_words", "price_gel", "cargo", "pieces",
                 "piece_length_m", "piece_width_m", "piece_height_m", "pickup_address", "delivery_address",
                 "needs_liftgate", "no_stacking", "hazmat", "notes"],
}

PROMPT = """A shipper on a Georgian freight marketplace describes a load they want to send (typed, pasted from a
Facebook or Viber post, or spoken). Read it into the fields. You only read: copy what the text says; anything it
doesn't say is null. Never guess, never fill in a typical value, never suggest a price.

- origin_city / destination_city: the city in English if it is one of: {cities}. Georgian forms count
  ("ქუთაისიდან" = Kutaisi, "თბილისში" = Tbilisi). Another place: write it as the user wrote it.
- truck_type: only if the user names one ("მაცივარი", "რეფი" = Refrigerated; "ტენტი" = Dry van; "ბორტი",
  "პლატფორმა" = Flatbed; "ფურგონი" = Box truck; "სპრინტერი", "მიკროავტობუსი" = Sprinter van), reason "named";
  or if the cargo must be kept cold or frozen (meat, fish, dairy, ice cream, medicine), then Refrigerated with
  reason "cargo_needs_cold". Otherwise "none" (and reason "none").
- weight_kg: in kilograms ("3 ტონა" = 3000, "3,5 ტ" = 3500). null if no weight is given.
- pickup_date: YYYY-MM-DD, from the user's words for the day; today is {today} ({weekday}). pickup_date_words: the
  user's exact words for the day, copied ("ხვალ", "5 დეკემბერს", "პარასკევს"). Both null if no day is given.
- deliver_by / deliver_by_words: only if the user says by when it must ARRIVE ("პარასკევამდე უნდა ჩავიდეს",
  "8 დეკემბრამდე მიტანა", "იმავე დღეს უნდა ჩავიდეს" = the pickup day): the date and the user's exact words. Else null.
- price_gel: only a price the user names, in lari ("600 ლარამდე" = 600). null otherwise.
- cargo: what is carried, short, in Georgian as written ("ავეჯი"). pieces: the number of pieces/pallets/boxes if
  given.
- piece_length_m / piece_width_m / piece_height_m: the size of ONE piece, in metres, only if the user gives it
  ("1,2x0,8x1,5" = 1.2, 0.8, 1.5; "120x80 სმ, სიმაღლე 150" = 1.2, 0.8, 1.5). Length x width x height in the
  user's order. A size not given is null; never a typical pallet size.
- pickup_address / delivery_address: a street address only if written, copied as written.
- no_stacking: true only if the user says the pieces must not be put on top of each other ("ერთმანეთზე არ
  დაიწყობა", "not stackable"), else null.
- needs_liftgate: true only if a liftgate (ჰიდრავლიკური ბორტი) is asked for. hazmat: true only if the cargo is
  dangerous goods (gas cylinders, fuel, chemicals, explosives) or the user says so.
- notes: other instructions for the driver (loading help, phone a person, time window), short, else null. Not
  greetings or questions to the reader ("ვინ წაიღებს?", "გამარჯობა"), not what is already in another field.

The text:
\"\"\"{text}\"\"\""""

TRANSCRIBE_SCHEMA = {"type": "object", "properties": {"transcript": {"type": "string"}}, "required": ["transcript"]}
TRANSCRIBE_PROMPT = ("Write down word for word what is said in this recording, in the language it is spoken in: "
                     "Georgian speech in Georgian script, English speech in English, Russian in Russian. NEVER "
                     "translate. Numbers as digits. Don't summarise, correct or add anything. Silence or noise only: "
                     "an empty transcript.")

WEEKDAYS_KA = ["ორშაბათ", "სამშაბათ", "ოთხშაბათ", "ხუთშაბათ", "პარასკევ", "შაბათ"]   # Monday..Saturday
FIELD_KA = {"origin_city": "საიდან", "destination_city": "სადამდე", "truck_type": "მანქანის ტიპი",
            "weight_kg": "წონა", "pickup_date": "აღების თარიღი", "price_gel": "ფასი"}
REQUIRED = list(FIELD_KA)


def _words(text):
    return re.findall(r"\w+", (text or "").lower())


def _quoted(words, text):
    """True if `words` appear, in order, in `text` (the user's own words, not the model's paraphrase)."""
    quote, said = _words(words), _words(text)
    return bool(quote) and any(said[i:i + len(quote)] == quote for i in range(len(said) - len(quote) + 1))


def relative_date(words, today):
    """Python, not the model, turns a relative day into a date: დღეს, ხვალ, ზეგ, a weekday (the next one)."""
    w = " ".join(_words(words))
    if re.search(r"\b(დღეს|today)\b", w):
        return today
    if re.search(r"\bზეგ", w):
        return today + timedelta(days=2)
    if re.search(r"\b(ხვალ\w*|tomorrow)\b", w):
        return today + timedelta(days=1)
    english = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for day, (stem, en) in enumerate(zip(WEEKDAYS_KA + [None], english)):   # "შაბათ" is inside "ორშაბათ": hence \s
        if (stem and re.search(rf"(^|\s){stem}", w)) or re.search(rf"\b{en}\b", w):
            ahead = (day - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


def _day(iso, words, text, today):
    """A day from the user's own words: Python dates a relative day itself; otherwise the model's date, if the words
    are really in the text and fit it (ai/common.date_said). None if neither."""
    if not words or not _quoted(words, text):
        return None
    day = relative_date(words, today)
    if day is None and iso and date_said(iso, words, text):
        try:
            day = date.fromisoformat(iso)
        except ValueError:
            day = None
    return day


def _city_said(code, text):
    """The city really is in the text: its Georgian stem or its English name."""
    low = (text or "").lower()
    stems = [s for s, c in CITY_STEMS_KA.items() if c == code]
    return code.lower()[:5] in low or any(s in (text or "") for s in stems)


def _type_said(code, text):
    """The user really named this truck type: a Georgian word for it, its label or an English word for it."""
    low = (text or "").lower()
    return (any(stem in low for stem, c in TRUCK_WORDS_KA.items() if c == code)
            or TRUCK_LABEL[code].lower() in low or any(w in low for w in TYPE_WORDS_EN.get(code, [])))


def size_said(metres, text):
    """True if the user wrote this size: as metres (1.2), centimetres (120) or millimetres (1200). Exact to the
    centimetre (number_said's ±0.5 is fine for kg or lari, not for metres)."""
    try:
        x = float(metres)
    except (TypeError, ValueError):
        return False
    if not 0 < x <= 16:
        return False
    return any(abs(x - n / unit) < 0.005 for n in _numbers(text or "") for unit in (1, 100, 1000))


def check(answer, text, today=None):
    """Gemini's reading -> the form's values, every one checked. Pure Python (tested without Gemini).
    Returns {"values", "filled", "missing", "notes", "unknown_places", "suggested"}."""
    today = today or date.today()
    a = {k: answer.get(k) for k in SCHEMA["properties"]}
    a = {k: (None if v == "none" else v) for k, v in a.items()}
    values, notes, unknown, suggested = {}, [], [], {}

    for field in ("origin_city", "destination_city"):
        said = a[field]
        if not said:
            continue
        code = city(said)
        if code and _city_said(code, text):
            values[field] = code
        elif not code:
            unknown.append(str(said))
    if unknown:
        notes.append("ეს ადგილი ჯერ არ გვაქვს: " + ", ".join(unknown) + ". ქალაქები: " + ", ".join(CITY_KA.values()) + ".")
    if values.get("origin_city") and values.get("origin_city") == values.get("destination_city"):
        values.pop("destination_city")
        notes.append("საიდან და სადამდე ერთი ქალაქია: ქალაქის შიგნით გადაზიდვა ჯერ არ გვაქვს.")

    if a["weight_kg"] and number_said(a["weight_kg"], text, tons=True) and a["weight_kg"] > 0:
        values["weight_kg"] = int(round(a["weight_kg"]))
    if a["price_gel"] and number_said(a["price_gel"], text) and a["price_gel"] > 0:
        values["price_gel"] = int(round(a["price_gel"]))
    if a["pieces"] and number_said(a["pieces"], text) and a["pieces"] > 0:
        values["pieces"] = int(a["pieces"])
    # One piece's size: each number must be written (in m, cm or mm), and all three, else none (the form's rule)
    size = {f: a[f] for f in ("piece_length_m", "piece_width_m", "piece_height_m")}
    if all(size_said(x, text) for x in size.values()):
        values.update({f: round(float(x), 2) for f, x in size.items()})
    elif any(size.values()):
        notes.append("პალეტის ზომა სრულად ვერ ამოვიკითხე: ჩაწერეთ სიგრძე, სიგანე და სიმაღლე მეტრებში.")

    day = _day(a["pickup_date"], a["pickup_date_words"], text, today)
    if day and day < today:
        notes.append("აღების თარიღი წარსულშია: აირჩიეთ სხვა დღე.")
    elif day:
        values["pickup_date"] = day.isoformat()
    words = a["deliver_by_words"] or ""
    if re.search(r"იმავე დღ|same day", words.lower()):   # before _day: "იმავე დღეს" holds "დღეს" (today)
        deadline = day if _quoted(words, text) else None
    else:
        deadline = _day(a["deliver_by"], words, text, today)
    if deadline and day and deadline < day:
        notes.append("მიტანის ვადა აღების დღეზე ადრეა: შეამოწმეთ თარიღები.")
    elif deadline and deadline >= today:
        values["deliver_by"] = deadline.isoformat()

    kind = truck_type(a["truck_type"]) if a["truck_type"] else None
    if kind and a["truck_type_reason"] != "cargo_needs_cold" and not _type_said(kind, text):
        kind = None   # "named", but the user never named it (27 Nov: "Dry van" for a message with no type)
    if kind and a["truck_type_reason"] == "cargo_needs_cold":
        values["truck_type"] = kind
        notes.append("ტვირთს სიცივე სჭირდება, ამიტომ Refrigerated: შეცვალეთ, თუ ასე არ არის.")
    elif kind:
        values["truck_type"] = kind
    elif values.get("origin_city") and values.get("destination_city"):
        # Python's suggestion, not the AI's: the cheapest type that can carry the weight
        options = compare_types(values["origin_city"], values["destination_city"], values.get("weight_kg"))
        if options.get("cheapest_type"):
            suggested["truck_type"] = options["cheapest_type"]
            values["truck_type"] = options["cheapest_type"]
            weight = f" {values['weight_kg']:,} კგ-ს".replace(",", " ") if values.get("weight_kg") else ""
            notes.append(f"მანქანის ტიპი არ დაგისახელებიათ: შემოთავაზებულია {TRUCK_LABEL[options['cheapest_type']]},"
                         f" ყველაზე იაფი, რომელიც{weight} წაიღებს. შეცვალეთ, თუ სხვა გჭირდებათ.")

    for field in ("cargo", "pickup_address", "delivery_address", "notes"):
        if a[field] and str(a[field]).strip():
            values[field] = str(a[field]).strip()[:200]
    if a["needs_liftgate"] is True:
        values["needs_liftgate"] = True
    if a["no_stacking"] is True and re.search(r"ერთმანეთზე|დაწყობ|დაიწყ|stack", (text or "").lower()):
        values["no_stacking"] = True   # only with the user's own words for it
    if a["hazmat"] is True and hazmat_said(text):   # the model's yes alone isn't enough (ai/common.py)
        values["hazmat"] = True

    missing = [f for f in REQUIRED if f not in values]
    if "price_gel" in missing and all(values.get(f) for f in ("origin_city", "destination_city", "truck_type")):
        notes.append("ფასი არ დაგისახელებიათ: სამართლიანი დიაპაზონი მარჯვნივაა. ფასს თქვენ ირჩევთ.")
    return {"values": values, "filled": [f for f in values if f not in suggested], "missing": missing,
            "missing_labels": [FIELD_KA[f] for f in missing], "notes": notes, "unknown_places": unknown,
            "suggested": list(suggested)}


def read(text, reader, today=None):
    """One Gemini reading of the text, checked by Python. reader: paperwork.extract.GeminiReader (or a fake)."""
    text = (text or "").strip()[:MAX_TEXT]
    today = today or date.today()
    weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][today.weekday()]
    prompt = PROMPT.format(cities=", ".join(CITIES), today=today.isoformat(), weekday=weekday, text=text)
    answer, meta = reader.generate([prompt], SCHEMA, label="describe load")
    # ai_answer: what the model said before Python's checks (the server logs it, then drops it from the reply)
    return {**check(answer, text, today), "model": meta.get("model"), "ai_answer": answer}


def transcribe(audio, mime_type, reader):
    """The recording -> text (Gemini writes down what was said)."""
    from google.genai import types
    part = types.Part.from_bytes(data=audio, mime_type=mime_type)
    answer, meta = reader.generate([part, TRANSCRIBE_PROMPT], TRANSCRIBE_SCHEMA, label="voice")
    return (answer.get("transcript") or "").strip(), meta.get("model")
