"""A SIMULATED სასაქონლო ზედნადები (Georgian goods waybill) for the pickup step, and its answer key.

    python generate_demo_waybill.py      -> demo_documents/ge/ge-07/waybill.pdf + expected.json

The trip is the demo's load 19 (seed_demo.py): Gori -> Rustavi, 6 boxes of car spare parts, 900 kg, on the demo
driver's truck DM-001-KG, the same trip as ge-06's proof of delivery. So the whole chain can be shown on one load:
transport order (booking) -> this waybill (pickup) -> ge-06/pod.pdf (delivery).

The fields follow the RS.ge electronic waybill's data (its public WayBillService: type, seller and buyer with tax IDs,
transport start and end address, driver name and personal number, vehicle number written without dashes, begin date,
transport cost and who pays it, the goods list, a comment; the number is assigned on activation). It is NOT an RS.ge
document: every name, number and ID is made up, and the page says so. The answer key is written from the same data
as the page, so the two can't disagree (the way logimind-ai's generate_demo_documents.py does it).
"""
import json
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "static" / "fonts"
OUT = ROOT / "demo_documents" / "ge" / "ge-07"

W = {   # everything on the page; SIMULATED
    "number": "0412378915",
    "type": "ტრანსპორტირებით",
    "begin": ("2026-11-28", "09:30"),
    "seller": ("Gori Auto Service LLC", "400000001"),
    "buyer": ("Rustavi Auto Parts LLC", "400000002"),
    "start": "გორი, ცხინვალის გზატკეცილი №5",
    "end": "რუსთავი, მეგობრობის გამზ. 21",
    "vehicle": "DM001KG",
    "driver": ("ლევან გელაშვილი", "01000000005"),
    "transport_cost": "310.00",
    "cost_payer": "მყიდველი",
    "goods": [("ავტონაწილები: სამუხრუჭე ხუნდები", "ყუთი", 4, "380.00"),
              ("ავტონაწილები: ფილტრები", "ყუთი", 2, "260.00")],
    "comment": "სათადარიგო ნაწილები, 6 ყუთი, ბრუტო წონა 900 კგ",
    "seller_signer": "თამარ ბერიძე",
}


def _scribble(pdf, x, y):
    """A hand signature: a few connected strokes (not a name, nothing readable)."""
    pts = [(0, 3), (3, 0), (5, 4), (8, -1), (10, 3), (13, 1), (15, 4), (19, 0), (22, 2)]
    pdf.set_draw_color(25, 45, 120)
    pdf.set_line_width(0.5)
    pdf.polyline([(x + a, y + b) for a, b in pts])
    pdf.set_draw_color(0, 0, 0)


def render():
    pdf = FPDF(format="A4")
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(False)
    for style, suffix in (("", "Regular"), ("B", "Bold")):
        pdf.add_font("Noto", style, str(FONTS / f"NotoSans-{suffix}.ttf"))
        pdf.add_font("NotoGeo", style, str(FONTS / f"NotoSansGeorgian-{suffix}.ttf"))
    pdf.set_fallback_fonts(["NotoGeo"], exact_match=False)
    pdf.set_title("სასაქონლო ზედნადები (სიმულაცია)")
    pdf.add_page()
    width = pdf.epw

    pdf.set_font("Noto", "", 8)
    pdf.set_text_color(150, 40, 40)
    pdf.cell(0, 5, "სიმულაცია · სადემონსტრაციო დოკუმენტი · არ არის RS.ge-ს დოკუმენტი",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Noto", "B", 16)
    pdf.cell(0, 9, "სასაქონლო ზედნადები", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 10)
    pdf.cell(0, 6, f"№ {W['number']}   ·   ტიპი: {W['type']}   ·   სტატუსი: აქტიური", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def row(label, value, bold=False):
        pdf.set_font("Noto", "", 9)
        pdf.set_text_color(90, 98, 110)
        pdf.cell(74, 7, label, border="B")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Noto", "B" if bold else "", 10)
        pdf.cell(width - 74, 7, value, border="B", new_x="LMARGIN", new_y="NEXT")

    row("გამყიდველი (გამგზავნი)", f"{W['seller'][0]}, ს/ნ {W['seller'][1]}", bold=True)
    row("მყიდველი (მიმღები)", f"{W['buyer'][0]}, ს/ნ {W['buyer'][1]}", bold=True)
    row("ტრანსპორტირების დაწყების ადგილი", W["start"])
    row("ტრანსპორტირების დასრულების ადგილი", W["end"])
    row("ტრანსპორტირების დაწყების თარიღი", f"{W['begin'][0][8:10]}.{W['begin'][0][5:7]}.{W['begin'][0][:4]} {W['begin'][1]}")
    row("სატრანსპორტო საშუალება", f"ავტომობილი · სახელმწიფო ნომერი {W['vehicle']}", bold=True)
    row("მძღოლი", f"{W['driver'][0]}, პ/ნ {W['driver'][1]}")
    row("ტრანსპორტირების ხარჯი", f"{W['transport_cost']} ₾ · გადამხდელი: {W['cost_payer']}")
    pdf.ln(5)

    pdf.set_font("Noto", "B", 10)
    pdf.cell(0, 7, "საქონლის ჩამონათვალი", new_x="LMARGIN", new_y="NEXT")
    cols = [(10, "№"), (78, "დასახელება"), (22, "ერთეული"), (22, "რაოდენობა"), (22, "ფასი, ₾"), (24, "თანხა, ₾")]
    pdf.set_font("Noto", "B", 9)
    pdf.set_fill_color(236, 239, 243)
    for w, title in cols:
        pdf.cell(w, 7, title, border=1, fill=True, align="C")
    pdf.ln()
    pdf.set_font("Noto", "", 9)
    total = 0.0
    for i, (name, unit, qty, price) in enumerate(W["goods"], 1):
        amount = qty * float(price)
        total += amount
        for (w, _), value, align in zip(cols, (str(i), name, unit, str(qty), price, f"{amount:,.2f}".replace(",", " ")),
                                        ("C", "L", "C", "C", "R", "R")):
            pdf.cell(w, 7, value, border=1, align=align)
        pdf.ln()
    pdf.set_font("Noto", "B", 9)
    pdf.cell(sum(w for w, _ in cols[:-1]), 7, "სულ:", border=1, align="R")
    pdf.set_font("Noto", "", 9)   # the bold face drew this number as garbage ("9 404₾44" for 2 040.00)
    pdf.cell(cols[-1][0], 7, f"{total:,.2f}".replace(",", " "), border=1, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Noto", "", 9)
    pdf.multi_cell(0, 6, f"შენიშვნა: {W['comment']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # signatures: the seller and the driver sign at loading; the receiver's line is empty until delivery
    third = width / 3
    y = pdf.get_y()
    for i, (title, name) in enumerate((("გამყიდველი (ჩააბარა)", W["seller_signer"]), ("მძღოლი (მიიღო)", W["driver"][0]),
                                       ("მიმღები (ჩაიბარა)", None))):
        x = pdf.l_margin + i * third
        if name:
            _scribble(pdf, x + 8, y + 3)
        pdf.line(x + 2, y + 10, x + third - 6, y + 10)
        pdf.set_xy(x + 2, y + 11)
        pdf.set_font("Noto", "", 8)
        pdf.set_text_color(90, 98, 110)
        pdf.cell(third - 8, 5, title)
        pdf.set_xy(x + 2, y + 16)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Noto", "", 9)
        pdf.cell(third - 8, 5, f"{name}, {W['begin'][0][8:10]}.{W['begin'][0][5:7]}.{W['begin'][0][:4]}" if name else "")
    return bytes(pdf.output())


def answer_key():
    """The expected reading, in the paperwork schema (demo_documents/ge/*/expected.json)."""
    day = W["begin"][0]
    return {
        "pair": "ge-07", "set": "ge", "simulated": True, "format": "schema",
        "scenario": "Pickup: the driver photographs the goods waybill (სასაქონლო ზედნადები). Seller and driver signed, "
                    "the receiver's line is still empty (it is signed at delivery). Nothing wrong: no problem to report, "
                    "and the receiver's signature must not be invented.",
        "checked_by": "generated by generate_demo_waybill.py from the same data as the document",
        "our_carrier": ["Kargonaut Logistics LLC"],
        "documents": {"bol": "waybill.pdf"},
        "schema": {"bol": {
            "kind": "bill_of_lading", "says_not_a_bol": False,
            "issuer": W["seller"][0], "issued_date": None, "load_number": None,
            "references": {"№": W["number"]},
            "carrier": None,
            "pickup": {"name": W["seller"][0], "address": W["start"], "date": day, "time": None},
            "delivery": {"name": W["buyer"][0], "address": W["end"], "date": None, "time": None},
            "commodity": None, "equipment": None, "pieces": None, "packages": {},
            "weight": 900, "weight_unit": "kg", "rate": None, "currency": None,
            "signatures": {"shipper": {"signed": True, "name": W["seller_signer"], "initials": None, "date": day},
                           "driver": {"signed": True, "name": W["driver"][0], "initials": None, "date": day}},
            "handwritten_notes": [],
        }},
        "must_flag": [],
        "must_not_invent": [{"field": "bol.received_signature",
                             "why": "at pickup the receiver hasn't signed; the empty line must stay empty"}],
    }


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "waybill.pdf").write_bytes(render())
    (OUT / "expected.json").write_text(json.dumps(answer_key(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT / "waybill.pdf", "and expected.json")
