"""Every sentence the paperwork agent shows, in English and Georgian (same idea as PROMPT_TEXT / OFFLINE_TEXT
in assistant.py: logic lives once in checks.py, only wording exists twice). When you change a text, change
both languages. The eval runs in English and checks some action phrases ("revised rate confirmation").

Georgian sentences are built so that inserted names stay in the nominative ("{doc}: ..."), because
Georgian case endings can't be glued onto a file name or a company name reliably.
"""

TEXT = {
    "en": {
        "kind": {"rate_confirmation": "rate confirmation", "bill_of_lading": "bill of lading",
                 "delivery_order": "delivery order", "proof_of_delivery": "proof of delivery", "other": "document"},
        "doc": "{kind} ({name})",
        "stop_address": {"pickup": "pickup address", "delivery": "delivery address"},
        "date_field": {"issued": "issued", "pickup": "pickup", "delivery": "delivery"},
        "signature": {"carrier": "The carrier's signature", "driver": "The driver's signature",
                      "shipper": "The shipper's signature", "receiver": "The receiver's signature"},
        "dated_by": {"driver": "driver", "shipper": "shipper"},
        "field": {"commodity": "commodity", "pieces": "pieces", "weight": "weight"},
        "package": {"cartons": "cartons", "pallets": "pallets", "skids": "skids", "pieces": "pieces",
                    "crates": "crates", "drums": "drums", "bundles": "bundles", "boxes": "boxes"},
        "one_piece": "1 piece",
        "no_unit": "(no unit)",
        "difference": {"zip": "ZIP {a} vs {b}", "state": "state {a} vs {b}", "number": "street number {a} vs {b}",
                       "street": "street '{a}' vs '{b}'", "direction": "direction {a} vs {b}",
                       "city": "city {a} vs {b}"},
        "city": {},
        "not_a_bol_quote": " ('This is NOT a Bill of Lading')",
        "reading_error": {"quota": "Gemini's daily limit is used up (429)", "busy": "Gemini is busy (503), try again shortly",
                          "timeout": "Gemini took too long to answer", "other": "Gemini could not read it"},
        "text": {
            "unreadable_date": "The {field} date on the {doc} could not be read as a date: '{value}'.",
            "delivery_before_pickup": "On the {doc} delivery ({delivery}) is before pickup ({pickup}).",
            "weight_unit_not_stated": "The {doc} gives the weight as {weight} without a unit. It is not stated "
                                      "whether that is lb or kg: ask, don't assume.",
            "not_stated": "The rate confirmation doesn't state: {fields}. Ask the broker before choosing a truck.",
            "rc_after_pickup": "The rate confirmation is dated {issued}, after the pickup on {pickup}: it was issued "
                               "after the load moved. Make sure the rate was agreed before pickup.",
            "signature_missing": "{what} is missing on the {doc}.",
            "rc_not_signed": "The rate confirmation is not signed by the carrier yet.",
            "rc_not_signed.action": "Check it, then sign it and send it back to the broker{broker}.",
            "pod_not_signed.action": "Ask the driver to get the receiver's signature and printed name.",
            "pod_receiver_unnamed": "The {doc} is signed by the receiver, but the signature can't be read and no name "
                                    "is printed: it is not clear who received the freight.",
            "pod_receiver_unnamed.action": "Ask the driver to get the receiver's name printed clearly on the POD "
                                           "(and a phone number).",
            "handwritten_note": "Handwritten on the {doc}: \"{note}\".",
            "carrier_is_broker": "The delivery order names the broker, {carrier}, as the delivering carrier, not "
                                 "{ours}. That is normal when freight is released to the broker who booked it; just "
                                 "make sure the warehouse knows our truck is coming.",
            "carrier_mismatch": "The {doc} names {carrier} as the carrier, not {ours}. Check who actually hauled "
                                "this load.",
            "carrier_mismatch.action": "Ask the broker{broker} to have the {kind} corrected to name {ours}, or to "
                                       "confirm in writing that {ours} hauled this load.",
            "address_mismatch": "The {stop_address} differs: rate confirmation '{a}', {doc} '{b}' ({reasons}).",
            "address_mismatch.action": "Ask the broker{broker} whether the paperwork is acceptable for billing with "
                                       "the different {stop_address}, before invoicing.",
            "address_unclear": "Could not confirm the {stop_address} is the same: '{a}' / '{b}'.",
            "weight_mismatch": "The weight differs: rate confirmation {a}, {doc} {b}.",
            "pieces_mismatch": "The piece count differs: {pieces} on the rate confirmation, {written} on the {doc}.",
            "date_mismatch": "The {who} dated the BOL {signed}; the rate confirmation's pickup date is {pickup}.",
            "late_delivery": "Signed for on {received}; delivery was due {due}.",
            "not_a_bol": "{name} was taken for a bill of lading, but it says it is NOT a bill of lading.",
            "delivery_order_no_bol": "{name} is a delivery order{quote}, not a bill of lading: there is no BOL for "
                                     "this load.",
            "no_bol.action": "Ask the broker{broker} for the bill of lading.",
            "no_rate_confirmation": "There is no rate confirmation among these documents, so the carrier, addresses "
                                    "and weight can't be checked against the agreed load.",
            "carrier_not_stated": "The rate confirmation doesn't name the carrier.",
            "carrier_not_ours": "The rate confirmation names {carrier} as the carrier, not {ours}.",
            "carrier_not_ours.action": "Ask the broker{broker} to send a revised rate confirmation with {ours} as "
                                       "the carrier.",
            "unreadable_document": "{name} could not be read ({error}).",
            "unreadable_document.action": "Check the file, or enter its details by hand.",
            # agreements: what was checked and is fine
            "ok_carrier": "The {doc} names our company as the carrier: {carrier}.",
            "ok_carrier_ours": "The rate confirmation is with our company: {carrier}.",
            "ok_address": "Same {stop_address}: '{a}' / '{b}'.",
            "ok_weight": "Same weight: {a} / {b}.",
            "ok_pieces": "Piece count agrees: {pieces} on the rate confirmation, {written} on the {doc}.",
            "ok_reference": "Linked by a shared number: {value} is the {label_a} on the rate confirmation and the "
                            "{label_b} on the {doc}.",
            "ok_delivery_date": "Delivered on time: signed for on {received}, due {due}.",
            # the "New load from this RC" box (server.py /api/paperwork/draft)
            "draft_missing": "Still needed for the draft: {fields}.",
            "draft_over_capacity": "{weight} kg is more than a {truck} carries ({capacity} kg). Check the weight or "
                                   "choose a bigger truck type.",
            "draft_same_city": "Pickup and delivery are the same city.",
            "draft_delivery_before_pickup": "The delivery date is before the pickup date.",
            "draft_bad_date": "A date on the rate confirmation couldn't be read.",
            "draft_not_a_number": "Weight and price must be numbers.",
            "draft_not_available": "No draft can be made from these documents.",
            "draft_failed": "The draft couldn't be made: {error}",
        },
        "draft_field": {"origin_city": "pickup city", "destination_city": "delivery city", "truck_type": "truck type",
                        "weight_kg": "weight (kg)", "customer_price_gel": "price (GEL)", "pickup_date": "pickup date"},
    },
    "ka": {
        "kind": {"rate_confirmation": "ფასის დადასტურება (RC)", "bill_of_lading": "კონოსამენტი (BOL)",
                 "delivery_order": "მიწოდების ორდერი (DO)", "proof_of_delivery": "მიტანის დადასტურება (POD)",
                 "other": "დოკუმენტი"},
        "doc": "{kind} [{name}]",
        "stop_address": {"pickup": "აღების მისამართი", "delivery": "მიტანის მისამართი"},
        "date_field": {"issued": "გაცემის", "pickup": "აღების", "delivery": "მიტანის"},
        "signature": {"carrier": "გადამზიდის ხელმოწერა", "driver": "მძღოლის ხელმოწერა",
                      "shipper": "გამგზავნის ხელმოწერა", "receiver": "მიმღების ხელმოწერა"},
        "dated_by": {"driver": "მძღოლმა", "shipper": "გამგზავნმა"},
        "field": {"commodity": "ტვირთის შიგთავსი", "pieces": "ადგილების რაოდენობა", "weight": "წონა"},
        "package": {"cartons": "კოლოფი", "pallets": "პალეტი", "skids": "სკიდი", "pieces": "ცალი",
                    "crates": "ყუთი", "drums": "კასრი", "bundles": "შეკვრა", "boxes": "ყუთი"},
        "one_piece": "1 ცალი",
        "no_unit": "(ერთეული არ წერია)",
        "difference": {"zip": "ZIP {a} / {b}", "state": "შტატი {a} / {b}", "number": "ქუჩის ნომერი {a} / {b}",
                       "street": "ქუჩა '{a}' / '{b}'", "direction": "მიმართულება {a} / {b}",
                       "city": "ქალაქი {a} / {b}"},
        "city": {"Tbilisi": "თბილისი", "Kutaisi": "ქუთაისი", "Batumi": "ბათუმი", "Poti": "ფოთი",
                 "Zestafoni": "ზესტაფონი", "Samtredia": "სამტრედია", "Gori": "გორი", "Rustavi": "რუსთავი"},
        "not_a_bol_quote": " (დოკუმენტზე წერია: 'This is NOT a Bill of Lading')",
        "reading_error": {"quota": "Gemini-ის დღიური ლიმიტი ამოიწურა (429)",
                          "busy": "Gemini გადატვირთულია (503), სცადეთ ცოტა ხანში",
                          "timeout": "Gemini-მ დროულად ვერ უპასუხა", "other": "Gemini-მ ვერ წაიკითხა"},
        "text": {
            "unreadable_date": "{doc}: {field} თარიღი ვერ წავიკითხე: '{value}'.",
            "delivery_before_pickup": "{doc}: მიტანის თარიღი ({delivery}) აღების თარიღზე ({pickup}) ადრეა.",
            "weight_unit_not_stated": "{doc}: წონა მითითებულია როგორც {weight}, ერთეულის გარეშე. არ წერია, ეს lb-ია "
                                      "თუ kg: დააზუსტეთ, ნუ ივარაუდებთ.",
            "not_stated": "ფასის დადასტურებაში (RC) მითითებული არ არის: {fields}. მანქანის შერჩევამდე დააზუსტეთ "
                          "ბროკერთან.",
            "rc_after_pickup": "ფასის დადასტურება (RC) დათარიღებულია {issued}, აღების ({pickup}) შემდეგ: ის გაიცა, "
                               "როცა ტვირთი უკვე გზაში იყო. დარწმუნდით, რომ ფასი აღებამდე იყო შეთანხმებული.",
            "signature_missing": "{doc}: {what} არ არის.",
            "rc_not_signed": "ფასის დადასტურებას (RC) გადამზიდის ხელმოწერა ჯერ არ აქვს.",
            "rc_not_signed.action": "გადაამოწმეთ, მოაწერეთ ხელი და დაუბრუნეთ ბროკერს{broker}.",
            "pod_not_signed.action": "სთხოვეთ მძღოლს, მიმღებს მოაწერინოს ხელი და გარკვევით დააწერინოს სახელი და გვარი.",
            "pod_receiver_unnamed": "{doc}: მიმღების ხელმოწერა არის, მაგრამ ის არ იკითხება და სახელი, გვარი დაწერილი "
                                    "არ არის: გაურკვეველია, ვინ მიიღო ტვირთი.",
            "pod_receiver_unnamed.action": "სთხოვეთ მძღოლს, მიმღებს მიტანის დადასტურებაზე (POD) გარკვევით "
                                           "დააწერინოს სახელი და გვარი (და ტელეფონის ნომერი).",
            "handwritten_note": "{doc}, ხელით ნაწერი: \"{note}\".",
            "carrier_is_broker": "მიწოდების ორდერში (DO) გადამზიდად მითითებულია ბროკერი, {carrier}, და არა {ours}. ეს "
                                 "ჩვეულებრივია, როცა ტვირთი გაიცემა იმ ბროკერზე, ვინც ის დაჯავშნა; უბრალოდ "
                                 "დარწმუნდით, რომ საწყობმა იცის, რომ ჩვენი მანქანა მოდის.",
            "carrier_mismatch": "{doc}: გადამზიდად მითითებულია {carrier} და არა {ours}. გადაამოწმეთ, ვინ გადაზიდა "
                                "ეს ტვირთი სინამდვილეში.",
            "carrier_mismatch.action": "სთხოვეთ ბროკერს{broker}, გაასწოროს {kind} და გადამზიდად მიუთითოს {ours}, "
                                       "ან წერილობით დაადასტუროს, რომ ტვირთი გადაზიდა კომპანიამ {ours}.",
            "address_mismatch": "{stop_address} განსხვავდება: ფასის დადასტურებაში (RC) '{a}', {doc}: '{b}' "
                                "({reasons}).",
            "address_mismatch.action": "ინვოისის გაგზავნამდე ჰკითხეთ ბროკერს{broker}, მიიღება თუ არა დოკუმენტები "
                                       "ანგარიშსწორებისთვის, როცა {stop_address} განსხვავდება.",
            "address_unclear": "ვერ დადასტურდა, რომ {stop_address} ერთი და იგივეა: '{a}' / '{b}'.",
            "weight_mismatch": "წონა განსხვავდება: ფასის დადასტურებაში (RC) {a}, {doc}: {b}.",
            "pieces_mismatch": "ადგილების რაოდენობა განსხვავდება: ფასის დადასტურებაში (RC) {pieces}, {doc}: {written}.",
            "date_mismatch": "კონოსამენტზე (BOL) {who} თარიღად მიუთითა {signed}; ფასის დადასტურების (RC) მიხედვით "
                             "აღების თარიღია {pickup}.",
            "late_delivery": "მიმღებმა ხელი მოაწერა {received}; მიტანის ვადა იყო {due}.",
            "not_a_bol": "{name} კონოსამენტად (BOL) ჩაითვალა, მაგრამ დოკუმენტზე წერია, რომ ის BOL არ არის.",
            "delivery_order_no_bol": "{name} მიწოდების ორდერია (DO){quote} და არა კონოსამენტი (BOL): ამ ტვირთს BOL არ აქვს.",
            "no_bol.action": "სთხოვეთ ბროკერს{broker} კონოსამენტი (BOL).",
            "no_rate_confirmation": "დოკუმენტებს შორის ფასის დადასტურება (RC) არ არის, ამიტომ გადამზიდი, მისამართები "
                                    "და წონა შეთანხმებულ ტვირთს ვერ შედარდება.",
            "carrier_not_stated": "ფასის დადასტურებაში (RC) გადამზიდი მითითებული არ არის.",
            "carrier_not_ours": "ფასის დადასტურებაში (RC) გადამზიდად მითითებულია {carrier} და არა {ours}.",
            "carrier_not_ours.action": "სთხოვეთ ბროკერს{broker}, გამოგზავნოს შესწორებული ფასის დადასტურება (revised RC), სადაც "
                                       "გადამზიდია {ours}.",
            "unreadable_document": "{name} ვერ წავიკითხე ({error}).",
            "unreadable_document.action": "შეამოწმეთ ფაილი ან შეიყვანეთ მონაცემები ხელით.",
            "ok_carrier": "{doc}: გადამზიდად მითითებულია ჩვენი კომპანია, {carrier}.",
            "ok_carrier_ours": "ფასის დადასტურება (RC) ჩვენს კომპანიაზეა: {carrier}.",
            "ok_address": "{stop_address} ემთხვევა: '{a}' / '{b}'.",
            "ok_weight": "წონა ემთხვევა: {a} / {b}.",
            "ok_pieces": "ადგილების რაოდენობა ემთხვევა: ფასის დადასტურებაში (RC) {pieces}, {doc}: {written}.",
            "ok_reference": "დოკუმენტებს აკავშირებს საერთო ნომერი {value}: ფასის დადასტურებაში (RC) ეს არის "
                            "{label_a}, {doc}: {label_b}.",
            "ok_delivery_date": "მიტანილია დროზე: მიმღებმა ხელი მოაწერა {received}, ვადა იყო {due}.",
            "draft_missing": "მონახაზისთვის კიდევ საჭიროა: {fields}.",
            "draft_over_capacity": "{weight} კგ მეტია, ვიდრე {truck} იტევს ({capacity} კგ). შეამოწმეთ წონა ან "
                                   "აირჩიეთ უფრო დიდი მანქანის ტიპი.",
            "draft_same_city": "აღებისა და მიტანის ქალაქი ერთი და იგივეა.",
            "draft_delivery_before_pickup": "მიტანის თარიღი აღების თარიღზე ადრეა.",
            "draft_bad_date": "ფასის დადასტურებაში (RC) თარიღი ვერ წავიკითხე.",
            "draft_not_a_number": "წონა და ფასი რიცხვები უნდა იყოს.",
            "draft_not_available": "ამ დოკუმენტებიდან მონახაზის შექმნა არ შეიძლება.",
            "draft_failed": "მონახაზი ვერ შეიქმნა: {error}",
        },
        "draft_field": {"origin_city": "აღების ქალაქი", "destination_city": "მიტანის ქალაქი",
                        "truck_type": "მანქანის ტიპი", "weight_kg": "წონა (კგ)", "customer_price_gel": "ფასი (ლარი)",
                        "pickup_date": "აღების თარიღი"},
    },
}


class Wording:
    """The sentences of one language. Unknown language -> English."""

    def __init__(self, lang="en"):
        self.lang = lang if lang in TEXT else "en"
        self.t = TEXT[self.lang]

    def say(self, key, **values):
        return self.t["text"][key].format(**values)

    def has(self, key):
        return key in self.t["text"]

    def action(self, key, **values):
        template = self.t["text"].get(f"{key}.action")
        return template.format(**values) if template else None

    def kind(self, kind):
        return self.t["kind"].get(kind, self.t["kind"]["other"])

    def doc(self, doc):
        return self.t["doc"].format(kind=self.kind(doc["kind"]), name=doc["name"])

    def stop_address(self, stop):
        return self.t["stop_address"][stop]

    def date_field(self, field):
        return self.t["date_field"][field]

    def signature(self, role):
        return self.t["signature"][role]

    def dated_by(self, role):
        return self.t["dated_by"].get(role, role)

    def fields(self, names):
        return ", ".join(self.t["field"].get(n, n) for n in names)

    def draft_error(self, result, truck_label=lambda code: code):
        """A failed draft from the RC (paperwork/draft.py create_draft, marketplace's error_code) as a sentence.
        truck_label: truck-type code -> its display name ("Dry van": truck types stay English)."""
        code = result.get("error_code")
        if code == "missing":
            return self.say("draft_missing", fields=", ".join(self.t["draft_field"].get(f, f)
                                                              for f in result.get("fields", [])))
        if code == "over_capacity":
            return self.say("draft_over_capacity", weight=f"{result['weight_kg']:,}", capacity=f"{result['capacity_kg']:,}",
                            truck=truck_label(result["truck_type"]))
        if code and self.has(f"draft_{code}"):
            return self.say(f"draft_{code}")
        return self.say("draft_failed", error=result.get("error", ""))

    def weight(self, weight, unit):
        return f"{weight:g} {unit or self.t['no_unit']}"

    def counts(self, counts):
        """{"cartons": 8, "pallets": 2} -> "8 cartons, 2 pallets" / "8 კოლოფი, 2 პალეტი"."""
        parts = []
        for kind, n in counts.items():
            if (kind, n) == ("pieces", 1):
                parts.append(self.t["one_piece"])
            else:
                parts.append(f"{n} {self.t['package'].get(kind, kind)}")
        return ", ".join(parts)

    def differences(self, differences):
        city = self.t["city"]   # cities come as English names; Georgian sentences show Georgian ones
        return "; ".join(self.t["difference"][d["part"]].format(a=city.get(d["a"], d["a"]), b=city.get(d["b"], d["b"]))
                         for d in differences)

    def not_a_bol_quote(self):
        return self.t["not_a_bol_quote"]

    def reading_error(self, error):
        """A short reason for the dispatcher instead of the raw API text ("model: 429 RESOURCE_EXHAUSTED; ...").
        The error lists every model tried; the FIRST (main) model's reason is the one explained."""
        first = str(error).split(";")[0]
        reasons = self.t["reading_error"]
        if "429" in first or "RESOURCE_EXHAUSTED" in first:
            return reasons["quota"]
        if "503" in first or "UNAVAILABLE" in first:
            return reasons["busy"]
        if "504" in first or "Timeout" in first or "DEADLINE" in first:
            return reasons["timeout"]
        if "original document" in first or "unsupported file type" in first:
            return str(error)          # our own refusal (not Gemini): already a clear sentence
        return reasons["other"]
