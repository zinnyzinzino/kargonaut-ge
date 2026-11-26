"""Number grounding: which numbers in an answer appear in no tool result and no dispatcher message.

Used twice, with the same rules:
- assistant.py checks every answer before the dispatcher sees it (one correction round, then a warning);
- evals/run_eval.py grades answers with it (the "right numbers" check).

Pure Python, no AI. It only says a number has NO source; it can't tell if a sourced number is used
for the right thing (e.g. a truck number put next to the wrong price).
"""
import re

MONTH_STEMS = "იანვ|თებერვ|მარტ|აპრილ|მაის|ივნის|ივლის|აგვისტ|სექტემბ|ოქტომბ|ნოემბ|დეკემბ"


def _numbers(text):
    """Numbers in a text: '1,420' -> 1420, '16,4' -> 16.4, '-15' -> 15 (sign ignored)."""
    text = re.sub(r"(\d)[,   ](\d{3})\b", r"\1\2", text)  # 1,420 / 1 420 -> 1420
    return [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", text)]


def _strip_dates_and_times(text):
    text = re.sub(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b", " ", text)
    text = re.sub(rf"\b\d{{1,2}}\s*(?:-?ე\s*)?(?:{MONTH_STEMS})\w*", " ", text)
    text = re.sub(r"\b\d{1,2}-(?:ში|მდე|დან|ს)\b", " ", text)
    text = re.sub(r"\+\s*\d+\s*(?:day|დღ)\w*", " ", text)
    return text


def ungrounded_numbers(reply, sources):
    """Numbers in the reply that appear in no tool result and no dispatcher message.
    Ignored: dates, clock times, and whole numbers up to 10 (counts like '3 options')."""
    known = [abs(n) for s in sources for n in _numbers(s)]
    bad = []
    for n in _numbers(_strip_dates_and_times(reply)):
        if n <= 10 and n == int(n):
            continue
        if not any(abs(n - k) <= max(0.51, 0.005 * k) for k in known):
            bad.append(int(n) if n == int(n) else n)
    return sorted(set(bad))
