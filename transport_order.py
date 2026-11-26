"""The transport order (ტვირთის გადაზიდვის შეკვეთა) as a PDF: the platform's own agreement document.

In Georgia there is no standard rate-confirmation form (companies write their own orders and contracts), and the
people on this site mostly have none. So when a shipper accepts an offer, the site writes the order itself from
what both sides agreed on it: the parties, the truck, the route, the cargo and the price. What the site doesn't know
(ID numbers, payment terms) is a blank line to fill in by hand, never an invented value.

Fonts: Noto Sans (Latin, digits, ₾, №, quotes) with Noto Sans Georgian as the fallback for Georgian letters
(static/fonts, SIL Open Font License). Pure Python (fpdf2), so it works in the cloud container too.
"""
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

FONTS = Path(__file__).resolve().parent / "static" / "fonts"
GOLD = (242, 183, 5)
INK = (20, 26, 34)
MUTED = (100, 112, 126)
LINE = (210, 216, 223)
BLANK = "_______________________"


def _date(iso):
    """2026-11-27 -> 27.11.2026 (the way Georgian documents write dates)."""
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso or "")


def _n(x):
    return f"{round(x):,}".replace(",", " ")


class _Order(FPDF):
    number = ""

    def footer(self):
        self.set_y(-13)
        self.set_font("Noto", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"Kargonaut · გადაზიდვის შეკვეთა {self.number} · შედგენილია ავტომატურად "
                        f"{datetime.now():%d.%m.%Y %H:%M} · გვერდი {self.page_no()}/{{nb}}", align="C")


def render(data):
    """PDF bytes of one transport order. data: marketplace.order_data()."""
    load, shipper, driver, vehicle = data["load"], data["shipper"], data["driver"], data["vehicle"]
    pdf = _Order(format="A4")
    pdf.number = data["number"]
    pdf.set_margins(18, 16, 18)
    pdf.set_auto_page_break(True, 16)
    for style, suffix in (("", "Regular"), ("B", "Bold")):
        pdf.add_font("Noto", style, str(FONTS / f"NotoSans-{suffix}.ttf"))
        pdf.add_font("NotoGeo", style, str(FONTS / f"NotoSansGeorgian-{suffix}.ttf"))
    pdf.set_fallback_fonts(["NotoGeo"], exact_match=False)
    pdf.set_title(f"გადაზიდვის შეკვეთა {data['number']}")
    pdf.set_author("Kargonaut")
    pdf.add_page()
    width = pdf.epw

    # ---- header
    pdf.set_font("Noto", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(width / 2, 6, "KARGONAUT")
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(width / 2, 6, "სატვირთო ბირჟა · საქართველო", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.l_margin + width, pdf.get_y() + 1)
    pdf.ln(5)
    pdf.set_text_color(*INK)
    pdf.set_font("Noto", "B", 17)
    pdf.cell(0, 9, "ტვირთის გადაზიდვის შეკვეთა", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Noto", "", 10)
    pdf.cell(0, 6, f"№ {data['number']}   ·   თარიღი: {_date(data['date'])}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*MUTED)
    pdf.set_font("Noto", "", 8.5)
    pdf.multi_cell(0, 4.5, "შედგენილია Kargonaut-ზე ავტომატურად, მხარეთა შეთანხმების (გადამზიდავის შეთავაზების და "
                           "დამკვეთის მიერ მისი მიღების) საფუძველზე.", align="L", new_x="LMARGIN", new_y="NEXT")
    if data.get("simulated"):
        pdf.ln(2)
        pdf.set_fill_color(253, 236, 232)
        pdf.set_text_color(180, 60, 30)
        pdf.set_font("Noto", "B", 8.5)
        pdf.multi_cell(0, 5, "  სადემონსტრაციო დოკუმენტი (სიმულაცია): მონაცემები გამოგონილია, ეს არ არის ნამდვილი "
                             "შეთანხმება.", fill=True, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    def heading(n, text):
        pdf.ln(1.5)
        if pdf.get_y() > pdf.h - 45:   # a heading never sits alone at the bottom of a page
            pdf.add_page()
        pdf.set_fill_color(*GOLD)
        pdf.rect(pdf.l_margin, pdf.get_y() + 1.5, 2.2, 4, style="F")
        pdf.set_fill_color(255, 255, 255)   # tables draw with the current fill colour: never the gold
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_text_color(*INK)
        pdf.set_font("Noto", "B", 11)
        pdf.cell(0, 7, f"{n}. {text}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    label = FontFace(color=MUTED, size_pt=8.5)
    head = FontFace(emphasis="BOLD", color=INK, fill_color=(246, 247, 249))

    def rows(table_rows, widths):
        pdf.set_font("Noto", "", 9)
        pdf.set_text_color(*INK)
        pdf.set_draw_color(*LINE)
        pdf.set_line_width(0.2)
        with pdf.table(col_widths=widths, first_row_as_headings=False, borders_layout="HORIZONTAL_LINES",
                       line_height=4.8, padding=(0.7, 2), cell_fill_mode="NONE") as t:
            for row in table_rows:
                r = t.row()
                for i, value in enumerate(row):
                    if isinstance(value, tuple):          # (text, FontFace)
                        r.cell(value[0], style=value[1])
                    else:
                        r.cell(str(value), style=label if i == 0 else None)

    # ---- 1. parties
    heading(1, "მხარეები")
    plate = vehicle["plate"] if vehicle and vehicle.get("plate") else BLANK
    rows([
        [("", head), ("დამკვეთი (ტვირთის გამგზავნი)", head), ("გადამზიდავი", head)],
        ["სახელი / დასახელება", shipper["name"], driver["name"]],
        ["სამართლებრივი ფორმა", shipper["legal_status_label"], driver["legal_status_label"]],
        ["პირადი / საიდენტიფიკაციო №", BLANK, BLANK],
        ["ტელეფონი", f"+995 {shipper['phone']}", f"+995 {driver['phone']}"],
        ["ავტომობილი", "", f"{vehicle['truck_label']}, {plate}" if vehicle else BLANK],
        ["ტვირთამწეობა", "", f"{_n(vehicle['capacity_kg'])} კგ" if vehicle else ""],
    ], (56, 59, 59))

    # ---- 2. the shipment
    heading(2, "გადაზიდვის დეტალები")
    needs = [x for x, on in (("ჰიდრავლიკური ბორტი", load.get("needs_liftgate")), ("სახიფათო ტვირთი", load.get("hazmat")))
             if on]
    rows([
        ["დატვირთვის ადგილი", load["origin_label"] + (f", {load['pickup_address']}" if load.get("pickup_address") else "")],
        ["დატვირთვის თარიღი", _date(load["pickup_date"])],
        ["გადმოტვირთვის ადგილი",
         load["destination_label"] + (f", {load['delivery_address']}" if load.get("delivery_address") else "")],
        *([["მიტანის ვადა", _date(load["deliver_by"]) + "-მდე (ჩათვლით)"],
           # the amount is the two sides' agreement (Civil Code: პირგასამტეხლო); the site never fills it in
           ["დაგვიანების პირგასამტეხლო", BLANK]] if load.get("deliver_by") else []),
        ["ტვირთი", load.get("cargo") or BLANK],
        ["წონა", f"{_n(load['weight_kg'])} კგ"],
        ["ადგილების რაოდენობა", str(load["pieces"]) if load.get("pieces") else BLANK],
        ["ავტომობილის ტიპი", load["truck_label"]],
        ["განსაკუთრებული მოთხოვნები", ", ".join(needs) if needs else "—"],
        ["მანძილი", f"დაახლოებით {_n(load['loaded_km'])} კმ (საავტომობილო გზით, OpenStreetMap)" if load.get("loaded_km") else "—"],
        ["შენიშვნა", load.get("notes") or "—"],
    ], (56, 118))

    # ---- 3. money
    heading(3, "ფინანსური პირობები")
    price = load.get("agreed_price_gel") or load["price_gel"]
    rows([
        ["გადაზიდვის საფასური", (f"{_n(price)} ₾", FontFace(emphasis="BOLD", color=INK, size_pt=11))],
        ["გადახდის წესი და ვადა", f"მხარეთა შეთანხმებით: {BLANK}"],
        ["სხვა პირობები", BLANK + BLANK],
    ], (56, 118))

    # ---- 4. what isn't covered here
    heading(4, "დამატებითი პირობები")
    pdf.set_font("Noto", "", 9)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 4.8, "ტვირთის ჩაბარება დასტურდება მიმღების ხელმოწერით (ხელმოწერილი ზედნადები ან მიღება-ჩაბარების "
                           "აქტი), რომელსაც გადამზიდავი ტვირთავს Kargonaut-ზე. ამ შეკვეთით გაუთვალისწინებელი საკითხები "
                           "რეგულირდება საქართველოს კანონმდებლობით.", align="L", new_x="LMARGIN", new_y="NEXT")

    # ---- signatures
    pdf.ln(5)
    if pdf.get_y() > pdf.h - pdf.b_margin - 34:   # the signatures need about 32 mm
        pdf.add_page()
    half = width / 2
    y = pdf.get_y()
    for i, (who, person) in enumerate((("დამკვეთი", shipper), ("გადამზიდავი", driver))):
        x = pdf.l_margin + i * half
        pdf.set_xy(x, y)
        pdf.set_font("Noto", "B", 10)
        pdf.cell(half - 8, 6, who, new_x="LEFT", new_y="NEXT")
        pdf.set_font("Noto", "", 9.5)
        pdf.cell(half - 8, 6, person["name"], new_x="LEFT", new_y="NEXT")
        pdf.ln(7)
        pdf.set_x(x)
        pdf.set_draw_color(*INK)
        pdf.line(x, pdf.get_y(), x + half - 14, pdf.get_y())
        pdf.ln(1.5)
        pdf.set_x(x)
        pdf.set_text_color(*MUTED)
        pdf.set_font("Noto", "", 8.5)
        pdf.cell(half - 8, 5, "ხელმოწერა", new_x="LEFT", new_y="NEXT")
        pdf.cell(half - 8, 6, f"თარიღი: {BLANK}", new_x="LEFT", new_y="NEXT")
        pdf.set_text_color(*INK)
    return bytes(pdf.output())
