"""Simulated Georgian demo documents for the paperwork agent (Kargonaut demo, 27-28 November).

    python generate_demo_documents.py            writes demo_documents/ge/ (refuses to overwrite)
    python generate_demo_documents.py --force    overwrite

Six loads, each one RC (and sometimes a BOL or POD), each showing one thing the agent must do (see
SCENARIO below). Every company, person, ID number and phone number is invented and every page says
"SIMULATED"; addresses use real street names with made-up businesses. Truck types stay in English.

Each load is described ONCE (LOADS below); this script builds both the document (HTML, printed to PDF or
photographed to PNG by headless Microsoft Edge, so no extra library) and its answer key (expected.json,
in the paperwork/schema.py format) from that same description, so the two can never disagree.
"""
import argparse
import html
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "demo_documents" / "ge"
LIVE_OUT = ROOT / "demo_documents" / "live"   # read live on stage: never shipped with a saved reading
EDGE_PATHS = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
              Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]

OUR = {"name": "Kargonaut Logistics LLC", "code": "999000101",
       "address": "თბილისი, ცოტნე დადიანის ქ. 7", "phone": "+995 000 10 01 01"}
DISPATCHER = {"ka": "ნინო კაპანაძე", "en": "N. Kapanadze"}
OTHER_CARRIER = {"name": "Lomi Trans Group LLC", "code": "999000514"}
BROKERS = {
    "alazani": {"name": "Alazani Freight LLC", "code": "999000211",
                "address": "თბილისი, ვაჟა-ფშაველას გამზ. 45", "phone": "+995 000 21 11 11", "contact": "გიორგი მელაძე",
                "terms": {"payment_days": 30, "free_hours": 2, "detention_gel_per_hour": 30, "cancellation_gel": 150,
                          "late_gel_per_hour": 50, "late_max_gel": 300}},
    "rioni": {"name": "Rioni Cargo LLC", "code": "999000312",
              "address": "ქუთაისი, წერეთლის ქ. 19", "phone": "+995 000 31 22 22", "contact": "ანა ჩხეიძე",
              "terms": {"payment_days": 15, "free_hours": 3, "detention_gel_per_hour": 25, "cancellation_gel": 100,
                        "late_gel_per_hour": 40, "late_max_gel": 200}},
    "kolkheti": {"name": "Colchis Forwarding LLC", "code": "999000413",
                 "address": "ბათუმი, გორგილაძის ქ. 60", "phone": "+995 000 41 33 33", "contact": "ლევან ხუციშვილი",
                 "terms": {"payment_days": 45, "free_hours": 2, "detention_gel_per_hour": 35, "cancellation_gel": 120,
                           "late_gel_per_hour": 60, "late_max_gel": 360}},
}
PACKAGE_KA = {"pallets": "პალეტი", "bundles": "შეკვრა", "boxes": "ყუთი"}


# Each load: the RC's data, plus optional "bol" / "pod" with what differs on them. Prices sit inside the
# project's own target range for the lane (check_lane_price), so the demo's price check agrees.
LOADS = [
    {
        "id": "ge-01", "scenario": "Clean RC: everything stated and our company is the carrier. The happy path: "
                                   "read it, no problems, turn it into a draft load the dispatcher confirms.",
        "broker": "alazani", "load_number": "AF-26-1187", "issued": "2026-11-26", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Poti Seafood Terminal LLC",
                   "address": "ფოთი, დავით აღმაშენებლის ქ. 18", "date": "2026-11-30", "time": "09:00–12:00"},
        "delivery": {"company": "Tbilisi Cold Storage LLC",
                     "address": "თბილისი, დავით აღმაშენებლის ხეივანი №160", "date": "2026-12-01", "time": "08:00"},
        "commodity": "გაყინული თევზი / Frozen fish", "equipment": "Refrigerated", "temperature": "−18 °C",
        "package": "pallets", "count": 18, "weight": 12000, "rate": 1100, "references": {"PO": "PFT-55821"},
        "must_flag": [], "must_note": [],
        "must_not_flag": ["carrier_not_ours", "not_stated", "weight_unit_not_stated", "rc_not_signed"],
        "draft": {"available": True, "origin_city": "Poti", "destination_city": "Tbilisi", "truck_type": "refrigerated",
                  "weight_kg": 12000, "customer_price_gel": 1100, "pickup_date": "2026-11-30", "missing": []},
    },
    {
        "id": "ge-02", "scenario": "RC + BOL that agree, but write the same places differently (ქ. / ქუჩა, №, a first "
                                   "name added, a warehouse number) and write our company's name differently on the "
                                   "BOL (KARGONAUT LOGISTICS). No false alarm allowed.",
        "broker": "rioni", "load_number": "RCD-55120", "issued": "2026-11-27", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Batumi Coastal Distribution LLC",
                   "address": "ბათუმი, ფარნავაზ მეფის ქ. 112", "date": "2026-12-01", "time": "10:00"},
        "delivery": {"company": "Imereti Trade House LLC",
                     "address": "ქუთაისი, რუსთაველის გამზ. 8", "date": "2026-12-01", "time": "16:00"},
        "commodity": "საყოფაცხოვრებო ტექნიკა / Household appliances", "equipment": "Dry van",
        "package": "pallets", "count": 16, "weight": 8000, "rate": 590, "references": {"PO": "ZD-20931"},
        "bol": {"number": "BOL-0112-034", "file": "bol.pdf", "carrier_as_written": "KARGONAUT LOGISTICS",
                "pickup_address": "ქ. ბათუმი, ფარნავაზ მეფის ქუჩა №112, საწყობი 3",
                "delivery_address": "ქ. ქუთაისი, შოთა რუსთაველის გამზირი №8",
                "plate": "KG-204-KG", "driver": "დავით ნოზაძე", "shipper_person": "მარიამ ბოლქვაძე",
                "shipper_signs_as": "M. Bolkvadze"},
        "must_flag": [], "must_note": [],
        "must_not_flag": ["address_mismatch", "carrier_mismatch", "weight_mismatch", "pieces_mismatch", "date_mismatch",
                          "carrier_not_ours", "driver_signature_missing", "shipper_signature_missing"],
        "draft": {"available": True, "origin_city": "Batumi", "destination_city": "Kutaisi", "truck_type": "dry_van",
                  "weight_kg": 8000, "customer_price_gel": 590, "pickup_date": "2026-12-01", "missing": []},
    },
    {
        "id": "ge-03", "scenario": "The RC names another carrier (Lomi Trans Group). Problem: ask the broker for a "
                                   "revised RC. Not signed by us yet (we don't sign an RC with the wrong carrier).",
        "broker": "kolkheti", "load_number": "KF/2026/0412", "issued": "2026-11-27", "carrier": OTHER_CARRIER,
        "carrier_signed": False,
        "pickup": {"company": "Rustavi Pipe Works LLC",
                   "address": "რუსთავი, მესხიშვილის ქ. 3", "date": "2026-12-02", "time": "08:00–10:00"},
        "delivery": {"company": "Zestafoni Building Supply LLC",
                     "address": "ზესტაფონი, აღმაშენებლის ქ. 41", "date": "2026-12-02", "time": "15:00"},
        "commodity": "ფოლადის მილები / Steel pipes", "equipment": "Flatbed",
        "package": "bundles", "count": 22, "weight": 14000, "rate": 760, "references": {"PO": "RPW-7714"},
        "must_flag": ["carrier_not_ours"], "must_note": ["rc_not_signed"], "must_not_flag": ["not_stated"],
        "draft": {"available": False, "blocked": ["carrier_not_ours"]},
    },
    {
        "id": "ge-04", "scenario": "RC + BOL (a phone photo, PNG): the delivery address really differs (another "
                                   "street in Batumi). Problem: ask the broker whether the paperwork is acceptable "
                                   "for billing. The pickup address is the same, written differently.",
        "broker": "alazani", "load_number": "AF-26-1203", "issued": "2026-11-27", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Saburtalo Furniture LLC",
                   "address": "თბილისი, გურამიშვილის გამზ. 76", "date": "2026-12-03", "time": "11:00"},
        "delivery": {"company": "Adjara Hotel Group LLC",
                     "address": "ბათუმი, ჭავჭავაძის ქ. 54", "date": "2026-12-04", "time": "10:00"},
        "commodity": "ავეჯი / Furniture", "equipment": "Box truck",
        "package": "boxes", "count": 30, "weight": 3800, "rate": 840, "references": {"PO": "SF-3307"},
        "bol": {"number": "BOL-0312-077", "file": "bol.png", "photo": True,
                "pickup_address": "ქ. თბილისი, დავით გურამიშვილის გამზირი №76",
                "delivery_address": "ბათუმი, ტბელ აბუსერიძის ქ. 9",
                "plate": "KG-317-KG", "driver": "ზურაბ კვარაცხელია", "shipper_person": "თამარ ლომიძე",
                "shipper_signs_as": "T. Lomidze"},
        "must_flag": ["address_mismatch"], "must_note": [],
        "must_not_flag": ["carrier_mismatch", "weight_mismatch", "pieces_mismatch", "carrier_not_ours"],
        "draft": {"available": True, "origin_city": "Tbilisi", "destination_city": "Batumi", "truck_type": "box_truck",
                  "weight_kg": 3800, "customer_price_gel": 840, "pickup_date": "2026-12-03", "missing": []},
    },
    {
        "id": "ge-05", "scenario": "The RC leaves the weight blank. Note 'not stated': the agent must not invent a "
                                   "weight, and the draft load must ask for it.",
        "broker": "rioni", "load_number": "RCD-55187", "issued": "2026-11-27", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Kutaisi Building Centre LLC",
                   "address": "ქუთაისი, ჯავახიშვილის ქ. 33", "date": "2026-12-04", "time": "09:00"},
        "delivery": {"company": "Gori Market LLC",
                     "address": "გორი, ჭავჭავაძის ქ. 15", "date": "2026-12-04", "time": "15:00"},
        "commodity": "სამშენებლო მასალა / Building materials", "equipment": "Dry van",
        "package": "pallets", "count": 20, "weight": None, "rate": 550, "references": {"PO": "KBC-1190"},
        "must_flag": [], "must_note": ["not_stated"], "must_not_flag": ["weight_unit_not_stated", "carrier_not_ours"],
        "draft": {"available": True, "origin_city": "Kutaisi", "destination_city": "Gori", "truck_type": "dry_van",
                  "customer_price_gel": 550, "pickup_date": "2026-12-04", "missing": ["weight_kg"]},
        "must_not_invent": [{"field": "rc.weight", "why": "the weight line on the RC is blank"}],
    },
    {
        "id": "ge-06", "scenario": "A delivered load: RC + POD. The receiver signed with a scribble and left the "
                                   "print-name line empty. Problem: ask the driver to get the receiver's printed name.",
        "broker": "kolkheti", "load_number": "KF/2026/0388", "issued": "2026-11-19", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Gori Auto Service LLC",
                   "address": "გორი, ცხინვალის გზატკეცილი №5", "date": "2026-11-20", "time": "10:00"},
        "delivery": {"company": "Rustavi Auto Parts LLC",
                     "address": "რუსთავი, მეგობრობის გამზ. 21", "date": "2026-11-20", "time": "15:00"},
        "commodity": "სათადარიგო ნაწილები / Spare parts", "equipment": "Sprinter van",
        "package": "boxes", "count": 6, "weight": 900, "rate": 310, "references": {"PO": "GAS-4410"},
        "pod": {"number": "POD-2011-019", "file": "pod.pdf", "received_time": "14:40",
                "delivery_address": "რუსთავი, მეგობრობის გამზირი №21", "driver": "გიორგი ტაბატაძე"},
        "must_flag": ["pod_receiver_unnamed"], "must_note": [],
        "must_not_flag": ["pod_not_signed", "late_delivery", "address_mismatch", "pieces_mismatch", "weight_mismatch"],
        "draft": {"available": False, "blocked": ["already_delivered"]},
        "must_not_invent": [{"field": "pod.receiver_name", "why": "the receiver's signature is an unreadable scribble "
                                                                  "and the print-name line is empty"}],
    },
]


# ---------------------------------------------------------------- rendering helpers

def e(text):
    return html.escape(str(text))


def ddmmyyyy(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def kg(n):
    return f"{n:,}".replace(",", " ") + " კგ"


def gel(n):
    return f"{n:,}".replace(",", " ") + ",00 ₾ (GEL)"


def scribble(seed, width=170, height=44):
    """An unreadable handwritten signature (SVG): the same seed always draws the same scribble."""
    rnd = random.Random(seed)
    x, y = 8, height * 0.6
    path = [f"M{x:.0f},{y:.0f}"]
    while x < width - 20:
        x2 = x + rnd.uniform(10, 26)
        path.append(f"C{x + rnd.uniform(0, 12):.0f},{rnd.uniform(2, height - 2):.0f} "
                    f"{x2 - rnd.uniform(0, 12):.0f},{rnd.uniform(2, height - 2):.0f} {x2:.0f},{rnd.uniform(10, height - 8):.0f}")
        x = x2
    path.append(f"M{width * 0.15:.0f},{height - 6:.0f} L{width * 0.8:.0f},{height - 10:.0f}")
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<path d="{" ".join(path)}" fill="none" stroke="#1a2f7a" stroke-width="1.7" stroke-linecap="round"/></svg>')


def signed_name(name_en):
    """A legible signature: the person's name in handwriting."""
    return f'<span class="hand">{e(name_en)}</span>'


CSS = """
@page { size: A4; margin: 13mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Sylfaen", "Segoe UI", sans-serif; font-size: 10pt; color: #141414; margin: 0; }
.sim { border: 2px solid #b3261e; color: #b3261e; font-weight: 700; text-align: center; padding: 3px 6px;
       font-size: 9pt; margin-bottom: 10px; letter-spacing: .3px; }
.head { display: flex; justify-content: space-between; gap: 16px; border-bottom: 2px solid #222; padding-bottom: 8px; }
.head .co { font-size: 9pt; line-height: 1.45; }
.head .co strong { font-size: 12pt; }
.head .title { text-align: right; }
.head .title h1 { margin: 0 0 4px; font-size: 15pt; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
td, th { border: 1px solid #555; padding: 5px 7px; vertical-align: top; text-align: left; }
th { background: #eef0f3; font-size: 9pt; }
.l { color: #555; font-size: 8pt; display: block; margin-bottom: 1px; }
.v { font-size: 10.5pt; }
.big { font-size: 13pt; font-weight: 700; }
.terms { font-size: 7.5pt; color: #333; margin-top: 8px; line-height: 1.3; }
.sigs { display: flex; gap: 18px; margin-top: 16px; }
.sig { flex: 1; border: 1px solid #555; padding: 6px 8px; min-height: 118px; }
.sig .line { height: 48px; border-bottom: 1px solid #222; display: flex; align-items: flex-end; padding-bottom: 2px; }
.sig .blank { height: 18px; border-bottom: 1px dotted #555; }
.hand { font-family: "Segoe Script", "Ink Free", cursive; font-size: 15pt; color: #1a2f7a; }
.foot { margin-top: 14px; font-size: 7.5pt; color: #b3261e; text-align: center; border-top: 1px solid #ccc; padding-top: 4px; }
"""
PHOTO_CSS = """
html { background: #6d6a63; }
body { width: 1000px; margin: 40px auto; background: #f6f3ea; padding: 34px 40px;
       transform: rotate(-1.1deg); box-shadow: 0 8px 26px rgba(0,0,0,.45); filter: contrast(.95) brightness(.98); }
"""
SIM_BANNER = ('<div class="sim">სიმულირებული სადემონსტრაციო დოკუმენტი — SIMULATED DEMO DOCUMENT · '
              'ყველა კომპანია და პირი გამოგონილია / all companies and people are invented</div>')
SIM_FOOT = ('<div class="foot">Kargonaut demo · სიმულირებული · SIMULATED · not a real company, load or '
            'person</div>')


def page(body, photo=False):
    return (f'<!doctype html><html lang="ka"><head><meta charset="utf-8"><style>{CSS}{PHOTO_CSS if photo else ""}'
            f'</style></head><body>{SIM_BANNER}{body}{SIM_FOOT}</body></html>')


def cell(label, value):
    return f'<span class="l">{label}</span><span class="v">{value}</span>'


# ---------------------------------------------------------------- documents

def rc_terms(load):
    """The RC's numbered terms (Georgian / English). Each broker has its own numbers (BROKERS[...]["terms"]), so
    "what is the detention rate?" has one right answer per load: the paperwork agent's RAG eval asks it."""
    t = BROKERS[load["broker"]]["terms"]
    terms = [
        ("გადამზიდი ადასტურებს ზემოთ მითითებულ პირობებს", "The carrier accepts the terms above."),
        ("ფასი მოიცავს ყველა ხარჯს, თუ სხვა რამ არ არის შეთანხმებული",
         "The rate includes all costs unless agreed otherwise."),
        ("მიტანის დადასტურება (POD) წარმოდგენილი უნდა იყოს ინვოისთან ერთად", "A POD must accompany the invoice."),
        (f"ლოდინი: აღებისას ან მიტანისას პირველი {t['free_hours']} საათი უფასოა, შემდეგ {t['detention_gel_per_hour']} ლარი "
         f"საათში, თუ მძღოლმა მისვლის დრო ბროკერს დროულად აცნობა",
         f"Detention: the first {t['free_hours']} hours at pickup or delivery are free, then {t['detention_gel_per_hour']} GEL "
         f"per hour, if the driver reported the arrival time to the broker."),
        (f"გაუქმება: თუ ბროკერი ტვირთს მანქანის გამოგზავნის შემდეგ გააუქმებს, გადამზიდს ეხდება {t['cancellation_gel']} ლარი",
         f"Cancellation: if the broker cancels after the truck was dispatched, the carrier is paid {t['cancellation_gel']} GEL."),
        (f"დაგვიანება: {t['late_gel_per_hour']} ლარი დაგვიანების ყოველ დაწყებულ საათზე, მაქსიმუმ {t['late_max_gel']} ლარი, "
         f"თუ დაგვიანების შესახებ ბროკერს წინასწარ არ ეცნობა",
         f"Late delivery: {t['late_gel_per_hour']} GEL per started hour of delay, at most {t['late_max_gel']} GEL, unless the "
         f"broker was told about the delay in advance."),
    ]
    if load.get("temperature"):
        terms.append(("ტემპერატურა: გადამზიდი მთელ გზაზე ინარჩუნებს მითითებულ ტემპერატურას და მიტანის დადასტურებასთან "
                      "(POD) ერთად წარადგენს ტემპერატურის ჩანაწერს",
                      "Temperature: the carrier keeps the stated temperature the whole way and hands in the temperature "
                      "record with the POD."))
    return terms


def terms_html(load):
    return "<br>".join(f"{i}. {e(ka)} / {e(en)}" for i, (ka, en) in enumerate(rc_terms(load), 1))


def rc_html(load):
    b = BROKERS[load["broker"]]
    t = b["terms"]
    car = load["carrier"]
    pk, dl = load["pickup"], load["delivery"]
    weight = kg(load["weight"]) if load["weight"] else "&nbsp;"
    temp = f'<tr><td>{cell("ტემპერატურა / Temperature", e(load["temperature"]))}</td><td></td></tr>' if load.get("temperature") else ""
    refs = " · ".join(f"{e(k)}: {e(v)}" for k, v in load["references"].items())
    carrier_sig = (f'<div class="line">{signed_name(DISPATCHER["en"])}</div>'
                   f'{cell("სახელი, გვარი / Name", e(DISPATCHER["ka"]))}<br>{cell("თარიღი / Date", ddmmyyyy(load["issued"]))}'
                   if load["carrier_signed"] else
                   f'<div class="line"></div>{cell("სახელი, გვარი / Name", "")}<div class="blank"></div>'
                   f'{cell("თარიღი / Date", "")}<div class="blank"></div>')
    body = f"""
    <div class="head">
      <div class="co"><strong>{e(b["name"])}</strong><br>ს/კ / ID: {b["code"]}<br>{e(b["address"])}<br>{b["phone"]}</div>
      <div class="title"><h1>ფასის დადასტურება<br>Rate Confirmation</h1>
        <div>№ <strong>{e(load["load_number"])}</strong></div><div>თარიღი / Date: {ddmmyyyy(load["issued"])}</div></div>
    </div>
    <table><tr><td>{cell("გადამზიდი / Carrier", f'<strong>{e(car["name"])}</strong>')}<br>
      {cell("ს/კ / ID", car["code"])}</td>
      <td>{cell("ბროკერის წარმომადგენელი / Broker contact", e(b["contact"]))}<br>{cell("ნომრები / References", refs)}</td></tr></table>
    <table><tr><th>აღება / Pickup</th><th>მიტანა / Delivery</th></tr>
      <tr><td>{cell("კომპანია / Company", e(pk["company"]))}<br>
        {cell("მისამართი / Address", e(pk["address"]))}<br>
        {cell("თარიღი / Date", ddmmyyyy(pk["date"]))} &nbsp; {cell("დრო / Time", e(pk["time"]))}</td>
      <td>{cell("კომპანია / Company", e(dl["company"]))}<br>
        {cell("მისამართი / Address", e(dl["address"]))}<br>
        {cell("თარიღი / Date", ddmmyyyy(dl["date"]))} &nbsp; {cell("დრო / Time", e(dl["time"]))}</td></tr></table>
    <table><tr><td>{cell("ტვირთი / Commodity", e(load["commodity"]))}</td>
      <td>{cell("მანქანის ტიპი / Equipment", e(load["equipment"]))}</td></tr>
      <tr><td>{cell("ადგილები / Pieces", f'{load["count"]} {PACKAGE_KA[load["package"]]}')}</td>
      <td>{cell("წონა / Weight", weight)}</td></tr>{temp}
      <tr><td colspan="2">{cell("ფასი / Rate", f'<span class="big">{gel(load["rate"])}</span>')} &nbsp;
        {cell("გადახდის პირობები / Payment terms", f'ინვოისიდან {t["payment_days"]} დღეში / {t["payment_days"]} days from invoice')}</td></tr></table>
    <div class="terms">{terms_html(load)}</div>
    <div class="sigs"><div class="sig">{cell("გადამზიდის ხელმოწერა / Carrier signature", "")}{carrier_sig}</div></div>
    """
    return page(body)


def bol_html(load):
    b, pk, dl = load["bol"], load["pickup"], load["delivery"]
    carrier = f"<strong>{e(b.get('carrier_as_written', OUR['name']))}</strong>"
    body = f"""
    <div class="head">
      <div class="co"><strong>{e(pk["company"])}</strong></div>
      <div class="title"><h1>კონოსამენტი<br>Bill of Lading</h1><div>№ <strong>{e(b["number"])}</strong></div>
        <div>თარიღი / Date: {ddmmyyyy(pk["date"])}</div></div>
    </div>
    <table><tr><th>გამომგზავნი / Shipper</th><th>მიმღები / Consignee</th></tr>
      <tr><td>{cell("კომპანია / Company", e(pk["company"]))}<br>{cell("მისამართი / Address", e(b["pickup_address"]))}</td>
      <td>{cell("კომპანია / Company", e(dl["company"]))}<br>{cell("მისამართი / Address", e(b["delivery_address"]))}</td></tr></table>
    <table><tr><td>{cell("გადამზიდი / Carrier", carrier)}</td><td>{cell("სახ. ნომერი / Truck plate", e(b["plate"]))}</td>
      <td>{cell("მძღოლი / Driver", e(b["driver"]))}</td></tr></table>
    <table><tr><th>ტვირთი / Goods</th><th>ადგილები / Packages</th><th>წონა / Weight</th></tr>
      <tr><td>{e(load["commodity"])}</td><td>{load["count"]} {PACKAGE_KA[load["package"]]}</td><td>{kg(load["weight"])}</td></tr>
      <tr><td colspan="3">{cell("შეკვეთის ნომერი / Order (PO)", e(load["references"]["PO"]))}</td></tr></table>
    <div class="sigs">
      <div class="sig">{cell("გამომგზავნი / Shipper", "")}<div class="line">{signed_name(b["shipper_signs_as"])}</div>
        {cell("სახელი, გვარი / Name", e(b["shipper_person"]))}<br>{cell("თარიღი / Date", ddmmyyyy(pk["date"]))}</div>
      <div class="sig">{cell("მძღოლი / Driver", "")}<div class="line">{scribble(b["number"] + "driver")}</div>
        {cell("სახელი, გვარი / Name", e(b["driver"]))}<br>{cell("თარიღი / Date", ddmmyyyy(pk["date"]))}</div>
      <div class="sig">{cell("მიმღები / Receiver", "")}<div class="line"></div>
        {cell("სახელი, გვარი / Name", "")}<div class="blank"></div>{cell("თარიღი / Date", "")}<div class="blank"></div></div>
    </div>"""
    return page(body, photo=b.get("photo", False))


def pod_html(load):
    p, dl = load["pod"], load["delivery"]
    body = f"""
    <div class="head">
      <div class="co"><strong>{e(OUR["name"])}</strong><br>ს/კ / ID: {OUR["code"]}<br>{e(OUR["address"])}</div>
      <div class="title"><h1>მიღება-ჩაბარების აქტი<br>Proof of Delivery</h1><div>№ <strong>{e(p["number"])}</strong></div>
        <div>თარიღი / Date: {ddmmyyyy(dl["date"])}</div></div>
    </div>
    <table><tr><td>{cell("გადამზიდი / Carrier", e(OUR["name"]))}</td>
      <td>{cell("ფასის დადასტურება № / RC №", e(load["load_number"]))}</td></tr>
      <tr><td colspan="2">{cell("მიმღები / Consignee", e(dl["company"]))}<br>
        {cell("მისამართი / Address", e(p["delivery_address"]))}<br>
        {cell("მიტანის თარიღი და დრო / Delivered", ddmmyyyy(dl["date"]) + " " + e(p["received_time"]))}</td></tr></table>
    <table><tr><th>ტვირთი / Goods</th><th>ადგილები / Packages</th><th>წონა / Weight</th><th>მდგომარეობა / Condition</th></tr>
      <tr><td>{e(load["commodity"])}</td><td>{load["count"]} {PACKAGE_KA[load["package"]]}</td><td>{kg(load["weight"])}</td>
      <td>დაზიანების გარეშე / No damage</td></tr></table>
    <div class="terms">ტვირთი მიღებულია სრული ოდენობით / Goods received in full.</div>
    <div class="sigs">
      <div class="sig">{cell("მძღოლი / Driver", "")}<div class="line">{scribble(p["number"] + "driver")}</div>
        {cell("სახელი, გვარი / Name", e(p["driver"]))}<br>{cell("თარიღი / Date", ddmmyyyy(dl["date"]))}</div>
      <div class="sig">{cell("მიმღები / Receiver", "")}<div class="line">{scribble(p["number"] + "receiver", width=150)}</div>
        {cell("სახელი, გვარი / Print name", "")}<div class="blank"></div>{cell("თარიღი / Date", ddmmyyyy(dl["date"]))}</div>
    </div>"""
    return page(body)


# ---------------------------------------------------------------- answer keys (paperwork/schema.py format)

def _stop(company_ka, address, date=None, time=None):
    return {"name": company_ka, "address": address, "date": date, "time": time}


def _sig(signed, name=None, date=None):
    return {"signed": signed, "name": name, "initials": None, "date": date}


def answer_key(load):
    pk, dl, b = load["pickup"], load["delivery"], BROKERS[load["broker"]]
    package = {load["package"]: load["count"]}
    rc = {
        "kind": "rate_confirmation", "says_not_a_bol": False, "issuer": b["name"], "issued_date": load["issued"],
        "load_number": load["load_number"], "references": dict(load["references"]), "carrier": load["carrier"]["name"],
        "pickup": _stop(pk["company"], pk["address"], pk["date"], pk["time"]),
        "delivery": _stop(dl["company"], dl["address"], dl["date"], dl["time"]),
        "commodity": load["commodity"], "equipment": load["equipment"], "pieces": load["count"], "packages": package,
        "weight": load["weight"], "weight_unit": "kg" if load["weight"] else None,
        "rate": load["rate"], "currency": "GEL",
        "signatures": {"carrier": _sig(True, DISPATCHER["ka"], load["issued"]) if load["carrier_signed"] else _sig(False)},
        "handwritten_notes": [],
    }
    schema = {"rc": rc}
    files = {"rc": "rc.pdf"}
    terms = dict(b["terms"], temperature_record=bool(load.get("temperature")))
    also = {"rc": {"signature.carrier.name": [DISPATCHER["en"], "Nino Kapanadze"]}}
    if "bol" in load:
        x = load["bol"]
        schema["bol"] = {
            "kind": "bill_of_lading", "says_not_a_bol": False, "issuer": pk["company"], "issued_date": pk["date"],
            "load_number": None, "references": {"BOL №": x["number"], "PO": load["references"]["PO"]},
            "carrier": x.get("carrier_as_written", OUR["name"]),
            "pickup": _stop(pk["company"], x["pickup_address"]),
            "delivery": _stop(dl["company"], x["delivery_address"]),
            "commodity": load["commodity"], "equipment": None, "pieces": None, "packages": package,
            "weight": load["weight"], "weight_unit": "kg", "rate": None, "currency": None,
            "signatures": {"shipper": _sig(True, x["shipper_person"], pk["date"]),
                           "driver": _sig(True, x["driver"], pk["date"]), "receiver": _sig(False)},
            "handwritten_notes": [],
        }
        files["bol"] = x["file"]
        # what the shipper wrote on the signature line ("M. Bolkvadze") is also her name
        also["bol"] = {"signature.shipper.name": [x["shipper_signs_as"]]}
    if "pod" in load:
        x = load["pod"]
        schema["pod"] = {
            "kind": "proof_of_delivery", "says_not_a_bol": False, "issuer": OUR["name"], "issued_date": dl["date"],
            "load_number": None, "references": {"RC №": load["load_number"], "POD №": x["number"]}, "carrier": OUR["name"],
            "pickup": _stop(None, None), "delivery": _stop(dl["company"], x["delivery_address"], dl["date"], x["received_time"]),
            "commodity": load["commodity"], "equipment": None, "pieces": None, "packages": package,
            "weight": load["weight"], "weight_unit": "kg", "rate": None, "currency": None,
            "signatures": {"driver": _sig(True, x["driver"], dl["date"]), "receiver": _sig(True, None, dl["date"])},
            "handwritten_notes": [],
        }
        files["pod"] = x["file"]
    return {
        "pair": load["id"], "set": "ge", "simulated": True, "format": "schema",
        "scenario": load["scenario"],
        "checked_by": "generated by generate_demo_documents.py from the same data as the documents",
        "our_carrier": [OUR["name"]],
        "documents": files, "schema": schema, "also_accept": also,
        "must_flag": [{"check": c} for c in load["must_flag"]],
        "must_note": [{"check": c} for c in load["must_note"]],
        "must_not_flag": [{"check": c} for c in load["must_not_flag"]],
        "must_not_invent": load.get("must_not_invent", []),
        # what the draft load must be (paperwork/draft.py), written out by hand per load, not computed
        "draft": load["draft"],
        # the RC's terms (rc_terms): the RAG eval asks about them, one right answer per load
        "terms": terms,
    }


# A document for the LIVE read on stage (`--live`): simulated like the others, but kept out of demo_documents/ge,
# so no demo button and no shipped reading covers it and Gemini really reads it in front of the audience.
# Clean, so the story is: never seen before -> read -> no problems -> new-load draft -> Confirm.
LIVE_LOADS = [
    {
        "id": "live-01", "scenario": "Live read on stage: a clean RC nobody has read before -> new-load draft.",
        "broker": "kolkheti", "load_number": "KF/2026/0415", "issued": "2026-11-27", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Kutaisi Steel Works LLC",
                   "address": "ქუთაისი, ნიკეას ქ. 52", "date": "2026-12-03", "time": "08:00–10:00"},
        "delivery": {"company": "Batumi Port Logistics LLC",
                     "address": "ბათუმი, გოგებაშვილის ქ. 7", "date": "2026-12-03", "time": "16:00"},
        "commodity": "ლითონის კონსტრუქციები / Steel structures", "equipment": "Flatbed",
        "package": "pallets", "count": 12, "weight": 15000, "rate": 620, "references": {"PO": "KSW-2290"},
        "must_flag": [], "must_note": [],
        "must_not_flag": ["carrier_not_ours", "not_stated", "weight_unit_not_stated", "rc_not_signed"],
        # 620 GEL: inside check_lane_price's target range for Kutaisi -> Batumi, Flatbed, 15 t (602-641)
        "draft": {"available": True, "origin_city": "Kutaisi", "destination_city": "Batumi", "truck_type": "flatbed",
                  "weight_kg": 15000, "customer_price_gel": 620, "pickup_date": "2026-12-03", "missing": []},
    },
    {
        # Like ge-04, but the PICKUP differs and nothing about it is saved: a real reading of an address mismatch.
        "id": "live-02", "scenario": "Live read: RC + BOL nobody has read before. The pickup address really differs "
                                     "(another street in Rustavi); the delivery is the same place written differently. "
                                     "Problem: ask the broker whether the paperwork is acceptable for billing.",
        "broker": "rioni", "load_number": "RCD-55203", "issued": "2026-11-27", "carrier": OUR, "carrier_signed": True,
        "pickup": {"company": "Rustavi Glass Works LLC",
                   "address": "რუსთავი, ბათუმის ქ. 12", "date": "2026-12-05", "time": "09:00–11:00"},
        "delivery": {"company": "Kutaisi Home Market LLC",
                     "address": "ქუთაისი, ჭავჭავაძის გამზ. 21", "date": "2026-12-05", "time": "17:00"},
        "commodity": "მინის ნაწარმი / Glassware", "equipment": "Dry van",
        "package": "pallets", "count": 14, "weight": 10000, "rate": 800, "references": {"PO": "RGW-4471"},
        "bol": {"number": "BOL-0512-102", "file": "bol.pdf",
                "pickup_address": "ქ. რუსთავი, გაგარინის ქუჩა №4",
                "delivery_address": "ქ. ქუთაისი, ილია ჭავჭავაძის გამზირი №21",
                "plate": "KG-428-KG", "driver": "ლევან გოგოლაძე", "shipper_person": "ეკა ბერიძე",
                "shipper_signs_as": "E. Beridze"},
        "must_flag": ["address_mismatch"], "must_note": [],
        "must_not_flag": ["carrier_mismatch", "weight_mismatch", "pieces_mismatch", "carrier_not_ours"],
        # 800 GEL: inside check_lane_price's target range for Rustavi -> Kutaisi, Dry van, 10 t (774-825)
        "draft": {"available": True, "origin_city": "Rustavi", "destination_city": "Kutaisi", "truck_type": "dry_van",
                  "weight_kg": 10000, "customer_price_gel": 800, "pickup_date": "2026-12-05", "missing": []},
    },
]


def write_live(edge, force=False):
    """demo_documents/live/<id>/ (every document of the load) + expected.json (the answer key, to check a reading
    afterwards). A load whose folder exists is skipped unless `force`, so adding one doesn't re-render the others."""
    builders = {"rc": rc_html, "bol": bol_html, "pod": pod_html}
    with tempfile.TemporaryDirectory(prefix="kargonaut-docs-") as tmp:
        for load in LIVE_LOADS:
            folder = LIVE_OUT / load["id"]
            if folder.exists() and any(folder.iterdir()) and not force:
                print(f"{load['id']}: exists, skipped (--force rewrites it)")
                continue
            folder.mkdir(parents=True, exist_ok=True)
            key = answer_key(load)
            for section, file_name in key["documents"].items():
                render(edge, builders[section](load), folder / file_name, Path(tmp))
            (folder / "expected.json").write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{load['id']}: {', '.join(key['documents'].values())}")
    print(f"Written to {LIVE_OUT} (not a demo load: no button, no shipped reading)")


# ---------------------------------------------------------------- Edge

def find_edge():
    for path in EDGE_PATHS:
        if path.exists():
            return path
    found = shutil.which("msedge")
    if found:
        return Path(found)
    sys.exit("Microsoft Edge not found: it prints the documents to PDF. Install Edge or add its path to EDGE_PATHS.")


def render(edge, html_text, out, work):
    """HTML -> PDF (print) or PNG (a 'phone photo' of the page)."""
    source = work / (out.stem + ".html")
    source.write_text(html_text, encoding="utf-8")
    profile = work / f"profile-{out.stem}"
    common = [str(edge), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}"]
    if out.suffix == ".pdf":
        args = common + ["--no-pdf-header-footer", "--print-to-pdf-no-header", f"--print-to-pdf={out}", source.as_uri()]
    else:
        args = common + ["--hide-scrollbars", "--window-size=1100,860", f"--screenshot={out}", source.as_uri()]
    subprocess.run(args, capture_output=True, timeout=90)
    if not out.exists() or out.stat().st_size < 1000:
        sys.exit(f"Edge did not produce {out}")


README = """# Simulated Georgian demo documents (paperwork agent)

Made by `generate_demo_documents.py` (do not edit by hand: change the script and run it with `--force`).
Every company, person, ID and phone number is invented, every page says SIMULATED, and our carrier is
Kargonaut Logistics LLC. Company names are English (as Georgian companies usually write them);
people's names are Georgian. Unlike `documents/` (real, private), these may be
committed, deployed and sent to Gemini.

Each folder is one load; `expected.json` is its answer key in the paperwork/schema.py format, generated from
the same data as the documents, with `must_flag` / `must_note` / `must_not_flag` / `must_not_invent`.

| Load | Documents | Scenario |
|---|---|---|
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="overwrite demo_documents/ge/")
    parser.add_argument("--live", action="store_true",
                        help="write only the live-read documents in demo_documents/live/ (see LIVE_LOADS); "
                             "existing loads are skipped unless --force")
    parser.add_argument("--keys-only", action="store_true",
                        help="rewrite only the answer keys (expected.json): the documents, and so their readings, stay")
    args = parser.parse_args()
    if args.live:
        write_live(find_edge(), force=args.force)
        return
    if args.keys_only:
        for load in LOADS:
            (OUT / load["id"] / "expected.json").write_text(
                json.dumps(answer_key(load), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Answer keys rewritten in {OUT}")
        return
    if OUT.exists() and any(OUT.iterdir()) and not args.force:
        sys.exit(f"{OUT} already exists: run with --force to overwrite it.")
    edge = find_edge()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="kargonaut-docs-") as tmp:
        work = Path(tmp)
        for load in LOADS:
            folder = OUT / load["id"]
            folder.mkdir(exist_ok=True)
            key = answer_key(load)
            builders = {"rc": rc_html, "bol": bol_html, "pod": pod_html}
            for section, file_name in key["documents"].items():
                render(edge, builders[section](load), folder / file_name, work)
            (folder / "expected.json").write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            rows.append(f"| `{load['id']}` | {', '.join(key['documents'].values())} | {load['scenario']} |")
            print(f"{load['id']}: {', '.join(key['documents'].values())}")
    (OUT.parent / "README.md").write_text(README + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"Written to {OUT}")


if __name__ == "__main__":
    main()
