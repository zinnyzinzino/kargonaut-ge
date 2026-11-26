// Kargonaut (Georgia): the whole site. Georgian only. Pages by the address after "#":
//   #/            landing            #/login, #/register/shipper, #/register/driver   sign in / register
//   #/app/<tab>   the signed-in app (shipper: loads, new, docs; driver: board, trips, vehicles, docs)
// Every number shown comes from the server (core/pricing.py); this file only lays it out.

const S = { me: null, meta: null, tab: null, filter: "all", mode: "list", open: new Set(), map: null,
            driverWhere: { near_city: "", heading_to: "" }, search: "" };

// ---------------------------------------------------------------- helpers
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// thousands with a narrow no-break space, and "₾" never wraps onto its own line
const fmt = (x) => x == null ? "—" : String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
const gel = (x) => x == null ? "—" : `${fmt(x)} ₾`;
const go = (hash) => { if (location.hash !== hash) location.hash = hash; else route(); };
const cityLabel = (code) => (S.meta.cities.find((c) => c.name === code) || {}).label || code;
const typeLabel = (code) => (S.meta.truck_types.find((t) => t.code === code) || {}).label || code;

// ---------------------------------------------------------------- ratings
// "★ 4,8 (4)" for a person's average, or "ახალი" while nobody has rated them yet
const stars = (r) => r && r.count
  ? `<span class="stars" title="${r.count} შეფასება">★ ${String(r.average).replace(".", ",")}<span class="muted"> (${r.count})</span></span>`
  : `<span class="muted small">ახალი, შეფასება ჯერ არ აქვს</span>`;
const given = (r) => `<span class="muted small">თქვენი შეფასება: </span><span class="stars">${"★".repeat(r.stars)}${"☆".repeat(5 - r.stars)}</span>`;

// ---------------------------------------------------------------- the transport order (PDF, made by the server)
const orderLink = (l, small = false) => ["booked", "in_transit", "delivered"].includes(l.status)
  ? `<a class="${small ? "link small" : "btn sm secondary"}" href="/api/loads/${l.id}/order.pdf" target="_blank" rel="noopener">`
    + `გადაზიდვის შეკვეთა (PDF)</a>` : "";

// ---------------------------------------------------------------- proof of delivery
function podBlock(l, compact = false) {
  const p = l.pod;
  if (!p) return "";
  const who = p.receiver_name ? `მიიღო: <b>${esc(p.receiver_name)}</b>`
    : p.receiver_signed ? "ხელმოწერილია, მაგრამ მიმღების სახელი არ წერია"
    : p.read ? "მიმღების ხელმოწერა არ ჩანს" : "დოკუმენტი ვერ წავიკითხეთ";
  const finding = (f) => `<div class="finding ${f.severity === "problem" ? "" : "note"}">${esc(f.detail)}
    ${f.action ? `<div class="todo">→ ${esc(f.action)}</div>` : ""}</div>`;
  return `<div class="pod-box"><div class="pod-head"><span class="label-sm">მიტანის დადასტურება</span>
      <a href="/api/loads/${l.id}/pod/file" target="_blank" rel="noopener">${esc(p.file_name)}</a>
      ${p.problems.length ? `<span class="chip bad">${p.problems.length} პრობლემა</span>` : `<span class="chip go">✓ რიგზეა</span>`}</div>
    <div class="small">${who}${p.delivery_date ? ` · ${esc(p.delivery_date)}` : ""}</div>
    ${compact ? "" : p.problems.map(finding).join("") + p.notes.map(finding).join("")}</div>`;
}

function podForm(loadId) {
  return `<form class="pod-form" data-pod="${loadId}">
    <span class="label-sm">მიტანისთვის ატვირთეთ ხელმოწერილი ზედნადები ან მიღება-ჩაბარების აქტი</span>
    <label class="btn sm secondary">ფოტო / PDF<input type="file" name="file" accept=".pdf,.jpg,.jpeg,.png,.webp" class="sr-only"></label>
    <span class="pod-name muted small">ფაილი არ არის არჩეული</span>
    <button type="button" class="link small" data-pod-demo>სადემონსტრაციო ქაღალდი</button>
    <button class="btn sm go">✓ მივიტანე</button></form>`;
}

function wirePodForms(root, after) {
  $$(".pod-form", root).forEach((f) => {
    const show = (name) => { $(".pod-name", f).textContent = name; };
    f.file.onchange = () => { f._file = f.file.files[0]; if (f._file) show(f._file.name); };
    $("[data-pod-demo]", f).onclick = async () => {   // the simulated demo POD, the same way the documents tab loads it
      const blob = await (await fetch("/api/paperwork/demo/ge-06/pod.pdf")).blob();
      f._file = new File([blob], "pod.pdf", { type: "application/pdf" });
      show("pod.pdf (სიმულაცია)");
    };
    f.onsubmit = async (e) => {
      e.preventDefault();
      if (!f._file) { toast("ჯერ აირჩიეთ ხელმოწერილი დოკუმენტის ფოტო ან PDF.", true); return; }
      const data = new FormData();
      data.append("file", f._file, f._file.name);
      const button = $("button.go", f);
      button.disabled = true; button.textContent = "ვამოწმებ დოკუმენტს…";
      try {
        const r = await api(`/api/jobs/${f.dataset.pod}/deliver`, { method: "POST", body: data });
        toast(r.pod && r.pod.problems.length ? "მიტანილია. დოკუმენტზე არის პრობლემა: ნახეთ დეტალები." : "მიტანილია. დოკუმენტი რიგზეა.");
        after();
      } catch (err) { toast(err.message, true); button.disabled = false; button.textContent = "✓ მივიტანე"; }
    };
  });
}

function ratingForm(loadId, whom) {
  return `<form class="rate-form" data-rate="${loadId}"><span class="label-sm">შეაფასეთ ${esc(whom)}</span>
    <span class="star-pick">${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-star="${n}" aria-label="${n}">★</button>`).join("")}</span>
    <input name="comment" placeholder="კომენტარი (არასავალდ.)" maxlength="300"><button class="btn sm">შეფასება</button></form>`;
}
function wireRatings(root, after) {
  $$(".rate-form", root).forEach((f) => {
    $$("[data-star]", f).forEach((b) => b.onclick = () => {
      f.dataset.stars = b.dataset.star;
      $$("[data-star]", f).forEach((x) => x.classList.toggle("on", +x.dataset.star <= +b.dataset.star));
    });
    f.onsubmit = async (e) => {
      e.preventDefault();
      if (!f.dataset.stars) { toast("აირჩიეთ 1-დან 5 ვარსკვლავამდე.", true); return; }
      try {
        await api(`/api/loads/${f.dataset.rate}/rate`, { json: { stars: +f.dataset.stars, comment: f.comment.value } });
        toast("მადლობა, შეფასება შენახულია.");
        after();
      } catch (err) { toast(err.message, true); }
    };
  });
}

async function api(path, options = {}) {
  const init = { credentials: "same-origin", ...options };
  if (options.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.json);
  }
  const res = await fetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(typeof data.detail === "string" ? data.detail : "შეცდომა. სცადეთ თავიდან.");
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(text, bad = false) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

function fillSelects(root = document) {
  $$(".city-select", root).forEach((sel) => {
    const any = sel.dataset.any ? `<option value="">${esc(sel.dataset.any)}</option>` : "";
    sel.innerHTML = any + S.meta.cities.map((c) => `<option value="${c.name}">${esc(c.label)}</option>`).join("");
    if (sel.dataset.pick) sel.selectedIndex = +sel.dataset.pick;
    if (sel.dataset.value !== undefined) sel.value = sel.dataset.value;
  });
  $$(".type-select", root).forEach((sel) => {
    sel.innerHTML = S.meta.truck_types.map((t) => `<option value="${t.code}">${esc(t.label)}</option>`).join("");
  });
}
const formData = (form) => {
  const data = Object.fromEntries(new FormData(form));
  $$("input[type=checkbox]", form).forEach((c) => (data[c.name] = c.checked));
  return data;
};

// ---------------------------------------------------------------- pages
function showPage(name) {
  ["landing", "auth", "app"].forEach((p) => $(`#page-${p}`).classList.toggle("hidden", p !== name));
  document.body.classList.toggle("on-app", name === "app");
}

async function route() {
  const hash = location.hash || "#/";
  if (hash.startsWith("#/app")) {
    if (!S.me) return go("#/login");
    showPage("app");
    return openTab(hash.split("/")[2]);
  }
  if (hash.startsWith("#/login") || hash.startsWith("#/register")) {
    if (S.me) return go("#/app");
    showPage("auth");
    const register = hash.startsWith("#/register");
    $("#login-box").classList.toggle("hidden", register);
    $("#register-box").classList.toggle("hidden", !register);
    if (register) {
      const role = hash.split("/")[2] === "driver" ? "driver" : "shipper";
      $(`#register-form input[value=${role}]`).checked = true;
      showTruckBox();
    }
    window.scrollTo(0, 0);
    return;
  }
  if (S.me && (hash === "#/" || hash === "#")) return go("#/app");
  showPage("landing");   // also in-page anchors (#how, #trust): the browser scrolls to them
  drawHeroMap();
}

// ---------------------------------------------------------------- landing
// The landing page's map: a real (dark) map with the real road through our 8 cities, and one truck driving it
// end to end and back. Drawn the first time the landing page is shown (a hidden map has no size).
let heroMap = null;
async function drawHeroMap() {
  if (heroMap) { heroMap.invalidateSize(); return; }
  let road;
  try { road = await (await fetch("/static/data/highway.json")).json(); } catch { return; }
  heroMap = L.map("hero-map", { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
    boxZoom: false, keyboard: false, touchZoom: false, zoomSnap: 0.1 });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 12, attribution: "&copy; OpenStreetMap" }).addTo(heroMap);
  const line = road.points;
  heroMap.fitBounds(line, { padding: [40, 34] });
  L.polyline(line, { color: "#05080C", weight: 9, opacity: .7, interactive: false }).addTo(heroMap);   // the road's edge
  L.polyline(line, { color: "#F2B705", weight: 3.5, opacity: .95, interactive: false }).addTo(heroMap);
  const size = { Tbilisi: 7, Batumi: 6, Kutaisi: 6 };   // bigger cities, bigger dots
  // labels above or below their dot, never to the side: the end cities sit at the map's edges
  const side = { Batumi: "bottom", Poti: "top", Samtredia: "bottom", Kutaisi: "top", Zestafoni: "bottom",
                 Gori: "top", Tbilisi: "top", Rustavi: "bottom" };
  S.meta.cities.forEach((c) => L.circleMarker([c.lat, c.lng], { radius: size[c.name] || 4.5, color: "#05080C", weight: 2,
      fillColor: "#E8EDF3", fillOpacity: 1, interactive: false })
    .bindTooltip(c.label, { permanent: true, direction: side[c.name] || "top", className: "hero-label", offset: [0, 0] })
    .addTo(heroMap));
  $("#hero-km").textContent = String(road.distance_km).replace(".", ",");

  // the truck: moves along the road at an even speed (by distance, not by point), there and back
  const dist = [0];
  for (let i = 1; i < line.length; i++) dist.push(dist[i - 1] + heroMap.distance(line[i - 1], line[i]));
  const total = dist[dist.length - 1];
  const at = (d) => {
    let i = dist.findIndex((x) => x >= d);
    if (i <= 0) return line[0];
    const f = (d - dist[i - 1]) / (dist[i] - dist[i - 1] || 1);
    return [line[i - 1][0] + (line[i][0] - line[i - 1][0]) * f, line[i - 1][1] + (line[i][1] - line[i - 1][1]) * f];
  };
  const halo = L.circleMarker(line[0], { radius: 11, stroke: false, fillColor: "#F2B705", fillOpacity: .25, interactive: false }).addTo(heroMap);
  const truck = L.circleMarker(line[0], { radius: 5.5, color: "#05080C", weight: 2, fillColor: "#F2B705", fillOpacity: 1, interactive: false }).addTo(heroMap);
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const p = at(total * 0.55); halo.setLatLng(p); truck.setLatLng(p); return;
  }
  const lap = 26000;   // ms from Batumi to Rustavi
  const step = (now) => {
    requestAnimationFrame(step);
    if ($("#page-landing").classList.contains("hidden")) return;   // nothing to move while the app is open
    const t = (now % (2 * lap)) / lap, d = (t <= 1 ? t : 2 - t) * total, p = at(d);
    halo.setLatLng(p); truck.setLatLng(p);
  };
  requestAnimationFrame(step);
}

// ---------------------------------------------------------------- sign in / register
async function signedIn(user) {
  S.me = user;
  S.filter = "all"; S.open.clear(); S.mode = "list";
  resetChatView();
  go("#/app");
}

async function login(e) {
  e.preventDefault();
  $("#login-error").textContent = "";
  try { signedIn(await api("/api/login", { json: formData(e.target) })); }
  catch (err) { $("#login-error").textContent = err.message; }
}

async function register(e) {
  e.preventDefault();
  $("#register-error").textContent = "";
  const all = formData(e.target), body = { vehicle: {} };
  for (const [k, v] of Object.entries(all)) {
    if (k.startsWith("v_")) body.vehicle[k.slice(2)] = v; else body[k] = v;
  }
  if (body.role !== "driver") body.vehicle = {};
  try { signedIn(await api("/api/register", { json: body })); }
  catch (err) { $("#register-error").textContent = err.message; }
}

// A driver registers with their truck: the truck section shows (and its fields count) only for drivers
function showTruckBox() {
  const driver = $("#register-form input[name=role]:checked").value === "driver";
  const box = $("#truck-box");
  box.classList.toggle("hidden", !driver);
  box.disabled = !driver;   // a disabled fieldset is neither checked nor sent
}

// ---------------------------------------------------------------- the app shell
const TABS = {
  shipper: [["loads", "ჩემი ტვირთები", renderShipperLoads], ["new", "ახალი ტვირთი", renderNewLoad],
            ["docs", "დოკუმენტები", renderDocs]],
  driver: [["board", "ტვირთების ბირჟა", renderDriverBoard], ["trips", "ჩემი რეისები", renderTrips],
           ["vehicles", "მანქანები", renderVehicles], ["docs", "დოკუმენტები", renderDocs]],
};

function setupShell() {
  const me = S.me;
  $("#who-name").textContent = me.name;
  $("#who-role").textContent = (me.role === "shipper" ? "ტვირთის გამგზავნი" : "მძღოლი") + " · " + me.legal_status_label +
    (me.rating && me.rating.count ? ` · ★ ${String(me.rating.average).replace(".", ",")} (${me.rating.count})` : "");
  $("#avatar").textContent = me.name.trim()[0] || "?";
  $("#demo-chip").classList.toggle("hidden", !me.is_demo);
  $("#app-tabs").innerHTML = TABS[me.role].map(([id, label]) =>
    `<button role="tab" data-tab="${id}" aria-selected="false">${label}</button>`).join("");
  $$("#app-tabs button").forEach((b) => b.onclick = () => go(`#/app/${b.dataset.tab}`));
  renderSuggestions();
}

function openTab(id) {
  const tabs = TABS[S.me.role];
  const tab = tabs.find((t) => t[0] === id) || tabs[0];
  if (!$("#app-tabs").children.length || $("#app-tabs").dataset.role !== S.me.role) {
    setupShell();
    $("#app-tabs").dataset.role = S.me.role;
  }
  if (S.tab !== tab[0]) { S.filter = "all"; S.open.clear(); S.mode = "list"; S.search = ""; }
  S.tab = tab[0];
  $$("#app-tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab[0]));
  if (S.map) { S.map.remove(); S.map = null; }
  tab[2]();
}
const refresh = () => openTab(S.tab);

function boardBar(inner) {
  return `<div class="board-bar">${inner}<span class="spacer"></span>
    <div class="seg" role="group" aria-label="ხედი">
      <button data-mode="list" aria-pressed="${S.mode === "list"}">სია</button>
      <button data-mode="map" aria-pressed="${S.mode === "map"}">რუკა</button></div></div>`;
}
function wireBar(root, rerender) {
  $$(".seg button", root).forEach((b) => b.onclick = () => { S.mode = b.dataset.mode; rerender(); });
}
function pills(groups, items) {
  return `<div class="pills">${groups.map(([id, label, color, test]) => `
    <button class="pill" data-filter="${id}" style="--c:${color}" aria-pressed="${S.filter === id}">
      <span class="dot"></span>${label}<span class="n">${items.filter(test).length}</span></button>`).join("")}</div>`;
}
function wirePills(root, rerender) {
  $$(".pill", root).forEach((p) => p.onclick = () => { S.filter = p.dataset.filter; rerender(); });
}

// A map of loads: a line per load (pickup -> delivery), a badge per city with how many loads start there
function drawMap(el, loads, colorOf, popupOf) {
  if (S.map) { S.map.remove(); S.map = null; }
  S.map = L.map(el, { zoomSnap: 0.25 });
  S.map.fitBounds(S.meta.cities.map((c) => [c.lat, c.lng]), { padding: [40, 40] });   // Georgia, not the region
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 12, attribution: "&copy; OpenStreetMap contributors" }).addTo(S.map);
  const at = Object.fromEntries(S.meta.cities.map((c) => [c.name, [c.lat, c.lng]]));
  loads.forEach((l, i) => {
    const a = at[l.origin_city], b = at[l.destination_city];
    const bend = 0.06 * ((i % 5) - 2);   // loads on one lane don't hide each other
    const mid = [(a[0] + b[0]) / 2 + bend, (a[1] + b[1]) / 2 - bend];
    L.polyline([a, mid, b], { color: colorOf(l), weight: 4, opacity: .85 }).bindPopup(popupOf(l)).addTo(S.map);
  });
  S.meta.cities.forEach((c) => {
    const n = loads.filter((l) => l.origin_city === c.name).length;
    L.marker([c.lat, c.lng], { icon: L.divIcon({ className: "city-pin",
      html: `<div class="city-dot ${n ? "has" : ""}" title="${esc(c.label)}">${esc(c.label)}${n ? " · " + n : ""}</div>` }) }).addTo(S.map);
  });
  setTimeout(() => S.map && S.map.invalidateSize(), 50);
}

// ---------------------------------------------------------------- shipper: my loads (the board)
const SHIP_GROUPS = [
  ["all", "ყველა", "#92A2B4", () => true],
  ["new", "ახალი", "#A99BFF", (l) => l.status === "open" && !l.pending_offers],
  ["offers", "შეთავაზებებით", "#F2B705", (l) => l.status === "open" && l.pending_offers > 0],
  ["booked", "დაჯავშნილი", "#6AA8FF", (l) => l.status === "booked"],
  ["in_transit", "გზაში", "#3CC8D8", (l) => l.status === "in_transit"],
  ["delivered", "მიტანილი", "#34C17B", (l) => l.status === "delivered"],
  ["cancelled", "გაუქმებული", "#7E8C9C", (l) => l.status === "cancelled"],
];
const shipColor = (l) => (SHIP_GROUPS.slice(1).find((g) => g[3](l)) || SHIP_GROUPS[0])[2];
const VERDICT_CHIP = { fair: "go", below_fair: "warn", below_costs: "bad", above_fair: "sign" };

async function renderShipperLoads() {
  const view = $("#view");
  let loads;
  try { loads = await api("/api/loads/mine"); }
  catch (err) { view.innerHTML = `<div class="empty">${esc(err.message)}</div>`; return; }
  const draw = () => {
    const group = SHIP_GROUPS.find((g) => g[0] === S.filter) || SHIP_GROUPS[0];
    const q = S.search.trim().toLowerCase();
    const shown = loads.filter(group[3]).filter((l) => !q || [l.id, l.cargo, l.origin_label, l.destination_label, l.truck_label]
      .join(" ").toLowerCase().includes(q));
    view.innerHTML = `
      <div class="page-title"><h1>ჩემი ტვირთები</h1><span class="muted">${loads.length} ტვირთი</span>
        <span class="spacer" style="flex:1"></span><a class="btn" href="#/app/new">＋ ახალი ტვირთი</a></div>
      ${pills(SHIP_GROUPS, loads)}
      ${boardBar(`<input class="search" id="search" placeholder="ძებნა: №, ტვირთი, ქალაქი…" value="${esc(S.search)}">`)}
      ${S.mode === "map" ? `<div class="board-map" id="board-map"></div>` : `
      <div class="board">
        <div class="board-head cols-shipper"><span>ტვირთი</span><span>სტატუსი</span><span>მარშრუტი</span>
          <span>მძღოლი / მანქანა</span><span>ფასი</span><span>შეთავაზებები</span><span></span></div>
        ${shown.map(shipperRow).join("") || `<div class="empty"><b>აქ ჯერ არაფერია</b>
          ${loads.length ? "სხვა სტატუსი აირჩიეთ." : "გამოაქვეყნეთ პირველი ტვირთი, ან მიწერეთ ასისტენტს: „ხვალ თბილისიდან ბათუმში 5 ტონა უნდა გავგზავნო“."}</div>`}
      </div>`}`;
    wirePills(view, draw);
    wireBar(view, draw);
    const search = $("#search");
    search.oninput = () => { S.search = search.value; draw(); search.focus(); search.setSelectionRange(9999, 9999); };
    if (S.mode === "map") {
      drawMap($("#board-map"), shown, shipColor, (l) => `<b>№${l.id} · ${esc(l.origin_label)} → ${esc(l.destination_label)}</b><br>
        ${esc(l.status_label)} · ${esc(l.truck_label)} · ${fmt(l.weight_kg)} კგ<br>ფასი ${gel(l.agreed_price_gel ?? l.price_gel)}`);
      return;
    }
    $$(".board-row", view).forEach((row) => row.onclick = (e) => {
      if (e.target.closest("button, a, input, form")) return;
      toggleRow(+row.dataset.id, draw);
    });
    $$(".chev", view).forEach((b) => b.onclick = () => toggleRow(+b.closest(".board-row").dataset.id, draw));
    S.open.forEach((id) => { const l = loads.find((x) => x.id === id); if (l) loadDetail(l); });
  };
  draw();
}

function toggleRow(id, draw) {
  S.open.has(id) ? S.open.delete(id) : S.open.add(id);
  draw();
}

function shipperRow(l) {
  const c = shipColor(l), pc = l.price_check;
  const driver = l.driver ? `<div class="cell-title">${esc(l.driver.name)}</div><div>${stars(l.driver.rating)}</div>
      <div class="line"><span class="ico">☎</span><a href="tel:+995${esc(l.driver.phone)}">${esc(l.driver.phone)}</a></div>
      <div class="muted small">${esc(l.driver.legal_status_label)}</div>
      ${l.vehicle ? `<div class="small">${esc(l.vehicle.truck_label)}${l.vehicle.plate ? " · " + esc(l.vehicle.plate) : ""}</div>` : ""}`
    : `<span class="muted">${l.status === "open" ? (l.pending_offers ? "აირჩიეთ შეთავაზებებიდან" : "ელოდება შეთავაზებებს") : "—"}</span>`;
  return `<div class="board-row cols-shipper clickable ${S.open.has(l.id) ? "open" : ""}" data-id="${l.id}" style="--c:${c}">
    <div><div class="cell-title">№${l.id}</div><div>${esc(l.cargo || "ტვირთი")}</div>
      <div class="muted small">${fmt(l.weight_kg)} კგ${l.pieces ? ` · ${l.pieces} ადგ.` : ""}</div>
      <div class="muted small">შექმნილია ${esc((l.created_at || "").slice(0, 10))}</div></div>
    <div><span class="status" style="--c:${c}">${esc(l.status_label)}</span>
      ${l.pod ? `<div><span class="chip ${l.pod.problems.length ? "bad" : "go"}">დოკუმენტი ${l.pod.problems.length ? "⚠" : "✓"}</span></div>` : ""}
      ${l.needs_liftgate ? `<div><span class="chip">ჰიდრ. ბორტი</span></div>` : ""}${l.hazmat ? `<div><span class="chip bad">სახიფათო</span></div>` : ""}</div>
    <div><div class="label-sm">აღება</div>
      <div class="line"><span class="ico pick"></span><span>${esc(l.origin_label)}${l.pickup_address ? ", " + esc(l.pickup_address) : ""}</span></div>
      <div class="line"><span class="ico date"></span><span class="num">${esc(l.pickup_date)}</span></div>
      <div class="label-sm" style="margin-top:6px">მიტანა</div>
      <div class="line"><span class="ico drop"></span><span>${esc(l.destination_label)}${l.delivery_address ? ", " + esc(l.delivery_address) : ""}</span></div>
      <div class="muted small">${l.loaded_km ? fmt(l.loaded_km) + " კმ · " : ""}${esc(l.truck_label)}</div></div>
    <div>${driver}</div>
    <div><div class="money num">${gel(l.agreed_price_gel ?? l.price_gel)}</div>
      ${l.agreed_price_gel ? `<div class="muted small">შეთანხმებული ფასი</div>` : ""}
      ${pc ? `<div class="muted small num">სამართლიანი ${fmt(pc.fair_price_range_gel[0])}–${fmt(pc.fair_price_range_gel[1])} ₾</div>
        <span class="chip ${VERDICT_CHIP[pc.verdict] || ""}">${esc(pc.verdict_label)}</span>` : ""}</div>
    <div>${l.status === "open" ? `<div class="cell-title">${l.pending_offers}</div>
      ${l.best_offer_gel != null ? `<div class="muted small">საუკეთესო ${gel(l.best_offer_gel)}</div>` : ""}` : `<span class="muted">—</span>`}</div>
    <div><button class="chev" aria-label="დეტალები">›</button></div>
  </div>${S.open.has(l.id) ? `<div class="detail" id="detail-${l.id}"><p class="muted">იტვირთება…</p></div>` : ""}`;
}

async function loadDetail(l) {
  const box = $(`#detail-${l.id}`);
  if (!box) return;
  const ask = `<button class="btn sm secondary" data-ask="ტვირთი №${l.id}: რომელი შეთავაზება ავირჩიო და რატომ?">💬 ჰკითხე ასისტენტს</button>`;
  if (l.status !== "open") {
    const steps = [["booked", "დაჯავშნილი"], ["in_transit", "გზაში"], ["delivered", "მიტანილი"]];
    const at = steps.findIndex((s) => s[0] === l.status);
    box.innerHTML = l.status === "cancelled" ? `<p class="muted">ტვირთი გაუქმებულია.</p>` :
      `<div class="pills" style="margin:10px 0 0">${steps.map((s, i) =>
        `<span class="pill" style="--c:${i <= at ? "#34C17B" : "#3A4A5E"}"><span class="dot"></span>${s[1]}</span>`).join("")}</div>
       <p class="muted small">სტატუსს მძღოლი ცვლის: „ავიღე ტვირთი“, შემდეგ „მივიტანე“.</p>
       <div class="detail-actions">${orderLink(l)}</div>` +
      podBlock(l) + (l.can_rate ? ratingForm(l.id, "მძღოლი") : l.my_rating ? `<p>${given(l.my_rating)}</p>` : "");
    wireRatings(box, refresh);
    return;
  }
  try {
    const r = await api(`/api/loads/${l.id}/offers`);
    box.innerHTML = (r.offers.length ? `<table class="offers-table"><thead><tr><th>მძღოლი</th><th>მანქანა</th>
        <th>აღებამდე</th><th>ფასი</th><th>შეფასება</th><th>შეტყობინება</th><th></th></tr></thead><tbody>
        ${r.offers.map((o) => `<tr class="${o.id === r.recommended_offer_id ? "best" : ""}">
          <td>${o.id === r.recommended_offer_id ? `<span class="chip go">რეკომენდებული</span><br>` : ""}<b>${esc(o.driver_name)}</b>
            <div>${stars(o.driver_rating)}</div><div class="muted small">${esc(o.legal_status_label)}${o.is_demo ? " · სიმულაცია" : ""}</div></td>
          <td>${esc(o.truck_label)}<div class="muted small">${fmt(o.capacity_kg)} კგ</div></td>
          <td class="num">${o.km_to_pickup != null ? fmt(o.km_to_pickup) + " კმ" : "—"}<div class="muted small">${esc(o.vehicle_city_label)}</div></td>
          <td class="money num">${gel(o.price_gel)}</td>
          <td>${o.price_verdict_label ? `<span class="chip ${VERDICT_CHIP[o.price_verdict] || ""}">${esc(o.price_verdict_label)}</span>` : "—"}</td>
          <td>${o.message ? "„" + esc(o.message) + "“" : `<span class="muted">—</span>`}</td>
          <td><button class="btn sm go" data-accept="${o.id}">მიღება</button></td></tr>`).join("")}
        </tbody></table><p class="muted small">რეკომენდაცია: ყველაზე დაბალი ფასი; თანაბარ ფასზე — მანქანა, რომელიც აღებასთან უფრო ახლოსაა.</p>`
      : `<p class="muted">შეთავაზება ჯერ არ არის. მძღოლები ხედავენ ტვირთს ბირჟაზე.</p>`) +
      `<div class="detail-actions">${r.offers.length ? ask : ""}
        <button class="btn sm danger" data-cancel="${l.id}">ტვირთის გაუქმება</button></div>`;
  } catch (err) { box.innerHTML = `<p class="error-text">${esc(err.message)}</p>`; return; }
  $$("[data-accept]", box).forEach((b) => b.onclick = async () => {
    if (!confirm("დავჯავშნოთ ეს მძღოლი? დანარჩენი შეთავაზებები უარყოფილი იქნება.")) return;
    try {
      await api(`/api/offers/${b.dataset.accept}/accept`, { json: {} });
      toast("მძღოლი დაჯავშნილია: კონტაქტი და გადაზიდვის შეკვეთა (PDF) ახლა ტვირთის დეტალებშია.");
      refresh();
    }
    catch (err) { toast(err.message, true); }
  });
  $$("[data-cancel]", box).forEach((b) => b.onclick = async () => {
    if (!confirm("გავაუქმოთ ტვირთი?")) return;
    try { await api(`/api/loads/${b.dataset.cancel}/cancel`, { json: {} }); toast("ტვირთი გაუქმდა."); refresh(); }
    catch (err) { toast(err.message, true); }
  });
  $$("[data-ask]", box).forEach((b) => b.onclick = () => askAssistant(b.dataset.ask));
}

// ---------------------------------------------------------------- shipper: new load
function renderNewLoad() {
  const tomorrow = new Date(Date.now() + 864e5).toISOString().slice(0, 10);
  $("#view").innerHTML = `
    <div class="page-title"><h1>ახალი ტვირთი</h1><span class="muted">ან მიწერეთ ასისტენტს — მონახაზს თავად მოგიმზადებთ</span></div>
    <div class="grid-2">
      <form class="panel" id="load-form">
        <div class="panel-head"><h2>ტვირთის მონაცემები</h2></div>
        <div class="panel-body form-grid">
          <label class="field">საიდან <select name="origin_city" class="city-select"></select></label>
          <label class="field">სადამდე <select name="destination_city" class="city-select" data-pick="2"></select></label>
          <label class="field">მანქანის ტიპი <select name="truck_type" class="type-select"></select></label>
          <label class="field">წონა (კგ) <input name="weight_kg" type="number" min="1" required placeholder="5000"></label>
          <label class="field">აღების თარიღი <input name="pickup_date" type="date" required value="${tomorrow}"></label>
          <label class="field">თქვენი ფასი (₾) <input name="price_gel" type="number" min="1" required placeholder="სამართლიანი ფასი მარჯვნივ"></label>
          <label class="field">რა არის ტვირთი <input name="cargo" placeholder="მაგ. ავეჯი"></label>
          <label class="field">ადგილების რაოდენობა <input name="pieces" type="number" min="0"></label>
          <label class="field wide">აღების მისამართი <input name="pickup_address" placeholder="ქუჩა, ნომერი"></label>
          <label class="field wide">მიტანის მისამართი <input name="delivery_address" placeholder="ქუჩა, ნომერი"></label>
          <label class="check"><input type="checkbox" name="needs_liftgate"> საჭიროა ჰიდრავლიკური ბორტი</label>
          <label class="check"><input type="checkbox" name="hazmat"> სახიფათო ტვირთი</label>
          <label class="field wide">შენიშვნა მძღოლისთვის <input name="notes"></label>
          <div class="wide" style="display:flex;gap:10px;align-items:center">
            <button class="btn">გამოქვეყნება</button>
            <span class="muted small">ან <a href="#/app/docs">შეავსეთ დოკუმენტიდან</a></span></div>
        </div>
      </form>
      <div class="panel price-card"><div class="panel-head"><h2>სამართლიანი ფასი</h2></div>
        <div class="panel-body" id="price-card"><p class="muted">აირჩიეთ მარშრუტი და წონა.</p></div></div>
    </div>`;
  fillSelects($("#view"));
  const form = $("#load-form");
  let timer;
  form.oninput = () => { clearTimeout(timer); timer = setTimeout(priceCard, 250); };
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const load = await api("/api/loads", { json: formData(form) });
      toast(`ტვირთი №${load.id} გამოქვეყნდა.`);
      go("#/app/loads");
    } catch (err) { toast(err.message, true); }
  };
  priceCard();
}

async function priceCard() {
  const f = formData($("#load-form")), box = $("#price-card");
  if (!box) return;
  if (f.origin_city === f.destination_city) { box.innerHTML = `<p class="muted">აირჩიეთ ორი სხვადასხვა ქალაქი.</p>`; return; }
  try {
    const r = await api(`/api/price?origin=${f.origin_city}&destination=${f.destination_city}&kind=${f.truck_type}` +
                        `&weight_kg=${f.weight_kg || 0}&price_gel=${f.price_gel || 0}`);
    const [low, high] = r.fair_price_range_gel, full = r.estimated_full_cost_gel;
    const lo = full * 0.8, hi = high * 1.2, pct = (x) => Math.max(0, Math.min(100, (x - lo) / (hi - lo) * 100));
    const bar = `linear-gradient(90deg, var(--loss-soft) 0 ${pct(full)}%, var(--amber-soft) ${pct(full)}% ${pct(low)}%,
      var(--go-soft) ${pct(low)}% ${pct(high)}%, var(--sign-soft) ${pct(high)}%)`;
    const price = +f.price_gel || 0;
    box.innerHTML = `
      <div class="muted small">${esc(r.origin && cityLabel(r.origin))} → ${esc(cityLabel(r.destination))} · ${fmt(r.loaded_km)} კმ · ${esc(typeLabel(r.truck_type))}</div>
      <div class="big-range num">${gel(low)} – ${gel(high)}</div>
      <div class="range-bar" style="background:${bar}">
        <div class="fair" style="left:${pct(low)}%;width:${pct(high) - pct(low)}%"></div>
        <span class="tick" style="left:${pct(full)}%">ხარჯი ${fmt(full)}</span>
        ${price ? `<span class="marker" style="left:${pct(price)}%">${fmt(price)} ₾</span>` : ""}
      </div>
      ${r.verdict ? `<div class="verdict ${r.verdict}">თქვენი ფასი: ${esc(r.verdict_label)}</div>` : ""}
      ${r.too_heavy_for_typical_vehicle ? `<div class="verdict below_fair">⚠️ ჩვეულებრივი ${esc(typeLabel(r.truck_type))} ${fmt(r.typical_capacity_kg)} კგ-მდე წაიღებს.</div>` : ""}
      <dl class="facts">
        <dt>მგზავრობის ხარჯი</dt><dd class="num">≈ ${gel(r.estimated_trip_costs_gel)} (საწვავი, ცვეთა, რეისი)</dd>
        <dt>+ მძღოლის დღე</dt><dd class="num">= ${gel(full)}</dd>
        <dt>ბაზარი</dt><dd>${r.market_evidence.market_average ? gel(r.market_evidence.market_average.market_average_gel)
          : "საშუალო ფასი არ გვაქვს (3 დადასტურებული გარიგება საჭიროა)"}</dd>
      </dl>
      <p class="muted small">მანძილი რეალურია (OSRM). ხარჯები სიმულირებული დაშვებებია. ფასს თქვენ წყვეტთ; მძღოლებს შეუძლიათ სხვა ფასი შემოგთავაზონ.</p>`;
  } catch (err) { box.innerHTML = `<p class="error-text">${esc(err.message)}</p>`; }
}

// ---------------------------------------------------------------- driver: the load board
async function renderDriverBoard() {
  const view = $("#view");
  let r;
  try {
    r = await api(`/api/loads/open?near_city=${S.driverWhere.near_city}&heading_to=${S.driverWhere.heading_to}`);
  } catch (err) {
    view.innerHTML = `<div class="page-title"><h1>ტვირთების ბირჟა</h1></div><div class="panel"><div class="empty">
      <b>${esc(err.message)}</b><a class="btn" href="#/app/vehicles" style="margin-top:12px">მანქანის დამატება</a></div></div>`;
    return;
  }
  const draw = () => {
    view.innerHTML = `
      <div class="page-title"><h1>ტვირთების ბირჟა</h1>
        <span class="muted">${r.total} ტვირთი თქვენი მანქანისთვის, საუკეთესო — ზემოთ</span></div>
      ${boardBar(`<label class="field">სად ვიქნები <select id="near" class="city-select" data-any="ახლა სადაც ვარ" data-value="${S.driverWhere.near_city}"></select></label>
        <label class="field">მივდივარ <select id="heading" class="city-select" data-any="ნებისმიერი" data-value="${S.driverWhere.heading_to}"></select></label>`)}
      ${S.mode === "map" ? `<div class="board-map" id="board-map"></div>` : `
      <div class="board">
        <div class="board-head cols-driver"><span>ტვირთი</span><span>მარშრუტი</span><span>მოთხოვნები</span>
          <span>გამგზავნის ფასი</span><span>შენ დაგრჩება</span><span>შეთავაზება</span></div>
        ${r.loads.map(driverRow).join("") || `<div class="empty"><b>შესაფერისი ტვირთი ახლა არ არის</b>
          სცადეთ სხვა ქალაქი, ან მონიშნეთ მანქანა თავისუფლად.</div>`}
      </div>
      <p class="muted small" style="margin-top:10px">„დაგრჩება“ = ფასი − საწვავი − ცვეთა − რეისის ხარჯი (შეფასება). ეს თქვენი დროის ანაზღაურებაა.</p>`}`;
    fillSelects(view);
    $("#near").onchange = $("#heading").onchange = () => {
      S.driverWhere = { near_city: $("#near").value, heading_to: $("#heading").value };
      renderDriverBoard();
    };
    wireBar(view, draw);
    if (S.mode === "map") {
      drawMap($("#board-map"), r.loads.map((x) => x.load), (l) => {
        const x = r.loads.find((y) => y.load.id === l.id);
        return x.earnings.driver_keeps_gel < 0 ? "#FF7A59" : "#34C17B";
      }, (l) => {
        const x = r.loads.find((y) => y.load.id === l.id);
        return `<b>№${l.id} · ${esc(l.origin_label)} → ${esc(l.destination_label)}</b><br>${esc(l.pickup_date)} · ${fmt(l.weight_kg)} კგ<br>
          ფასი ${gel(l.price_gel)} · დაგრჩება ≈ ${gel(x.earnings.driver_keeps_gel)}`;
      });
      return;
    }
    $$("form.offer-form", view).forEach((f) => f.onsubmit = async (e) => {
      e.preventDefault();
      const data = formData(f);
      try {
        await api(`/api/loads/${f.dataset.load}/offers`, { json: { price_gel: +data.price_gel || 0, vehicle_id: +f.dataset.vehicle } });
        toast("შეთავაზება გაიგზავნა.");
        renderDriverBoard();
      } catch (err) { toast(err.message, true); }
    });
    $$("[data-ask]", view).forEach((b) => b.onclick = () => askAssistant(b.dataset.ask));
  };
  draw();
}

function driverRow(x) {
  const l = x.load, e = x.earnings, bad = e.driver_keeps_gel < 0;
  return `<div class="board-row cols-driver" style="--c:${bad ? "#FF7A59" : "#34C17B"}">
    <div><div class="cell-title">№${l.id}</div><div>${esc(l.cargo || "ტვირთი")}</div>
      <div class="muted small">${fmt(l.weight_kg)} კგ${l.pieces ? ` · ${l.pieces} ადგ.` : ""}</div>
      <div class="small">გამგზავნი ${stars(x.shipper_rating)}</div></div>
    <div><div class="line"><span class="ico pick"></span><span>${esc(l.origin_label)}${l.pickup_address ? ", " + esc(l.pickup_address) : ""}</span></div>
      <div class="line"><span class="ico drop"></span><span>${esc(l.destination_label)}${l.delivery_address ? ", " + esc(l.delivery_address) : ""}</span></div>
      <div class="line"><span class="ico date"></span><span class="num">${esc(l.pickup_date)}</span></div></div>
    <div><span class="chip sign">${esc(l.truck_label)}</span>${l.needs_liftgate ? `<span class="chip">ჰიდრ. ბორტი</span>` : ""}
      ${l.hazmat ? `<span class="chip bad">სახიფათო</span>` : ""}${l.notes ? `<div class="muted small">${esc(l.notes)}</div>` : ""}</div>
    <div class="money num">${gel(l.price_gel)}</div>
    <div><div class="${bad ? "neg" : "pos"} num" style="font-size:17px">${gel(e.driver_keeps_gel)}</div>
      <div class="muted small num">${e.per_driving_hour_gel != null ? gel(e.per_driving_hour_gel) + "/სთ · " : ""}ხარჯი ≈ ${gel(e.trip_costs_gel)}</div>
      <div class="muted small num">ცარიელი ${fmt(e.empty_km)} კმ · სულ ${fmt(e.total_km)} კმ, ${e.driving_hours} სთ</div></div>
    <div>${x.my_offer ? `<div><span class="chip go">გაგზავნილია: ${gel(x.my_offer.price_gel)}</span></div>` : ""}
      <form class="offer-form" data-load="${l.id}" data-vehicle="${x.vehicle_id}">
        <input name="price_gel" type="number" min="1" placeholder="${Math.round(l.price_gel)}" title="ცარიელი = გამგზავნის ფასი">
        <button class="btn sm">${x.my_offer ? "შეცვლა" : "შეთავაზება"}</button></form>
      <button class="link small" data-ask="ტვირთი №${l.id}: რამდენი დამრჩება და ღირს თუ არა?">💬 ჰკითხე ასისტენტს</button></div>
  </div>`;
}

// ---------------------------------------------------------------- driver: my trips
const TRIP_GROUPS = [
  ["all", "ყველა", "#92A2B4", () => true],
  ["offer", "შეთავაზება გაგზავნილი", "#F2B705", (t) => t.kind === "offer"],
  ["booked", "დაჯავშნილი", "#6AA8FF", (t) => t.status === "booked"],
  ["in_transit", "გზაში", "#3CC8D8", (t) => t.status === "in_transit"],
  ["delivered", "მიტანილი", "#34C17B", (t) => t.status === "delivered"],
];

async function renderTrips() {
  const view = $("#view");
  let r;
  try { r = await api("/api/jobs"); } catch (err) { view.innerHTML = `<div class="empty">${esc(err.message)}</div>`; return; }
  const items = [...r.pending_offers.map((o) => ({ kind: "offer", status: "offer", offer: o, load: o.load })),
                 ...r.jobs.map((l) => ({ kind: "job", status: l.status, load: l }))];
  const draw = () => {
    const group = TRIP_GROUPS.find((g) => g[0] === S.filter) || TRIP_GROUPS[0];
    const shown = items.filter(group[3]);
    view.innerHTML = `<div class="page-title"><h1>ჩემი რეისები</h1></div>
      ${pills(TRIP_GROUPS, items)}
      <div class="board alone">
        <div class="board-head cols-trips"><span>ტვირთი</span><span>მარშრუტი</span>
          <span>გამგზავნი</span><span>ფასი</span><span>მოქმედება</span></div>
        ${shown.map(tripRow).join("") || `<div class="empty"><b>აქ ჯერ არაფერია</b>ტვირთები ბირჟაზეა.</div>`}
      </div>`;
    wirePills(view, draw);
    wireRatings(view, renderTrips);
    wirePodForms(view, renderTrips);
    $$("[data-advance]", view).forEach((b) => b.onclick = async () => {
      try { await api(`/api/jobs/${b.dataset.advance}/advance`, { json: {} }); toast("სტატუსი განახლდა."); renderTrips(); }
      catch (err) { toast(err.message, true); }
    });
    $$("[data-withdraw]", view).forEach((b) => b.onclick = async () => {
      try { await api(`/api/offers/${b.dataset.withdraw}/withdraw`, { json: {} }); toast("შეთავაზება გაუქმდა."); renderTrips(); }
      catch (err) { toast(err.message, true); }
    });
  };
  draw();
}

function tripRow(t) {
  const l = t.load, c = (TRIP_GROUPS.slice(1).find((g) => g[3](t)) || TRIP_GROUPS[0])[2];
  const next = { booked: "✓ ავიღე ტვირთი" }[l.status];
  const action = t.kind === "offer"
    ? `<button class="btn sm danger" data-withdraw="${t.offer.id}">შეთავაზების გაუქმება</button>`
    : next ? `<button class="btn sm go" data-advance="${l.id}">${next}</button>`
    : l.status === "in_transit" ? podForm(l.id)
    : podBlock(l, true) + (l.can_rate ? ratingForm(l.id, "გამგზავნი") : l.my_rating ? given(l.my_rating) : `<span class="chip go">დასრულებული</span>`);
  return `<div class="board-row cols-trips" style="--c:${c}">
    <div><div class="cell-title">№${l.id}</div><span class="status" style="--c:${c}">${t.kind === "offer" ? "შეთავაზება" : esc(l.status_label)}</span>
      <div>${esc(l.cargo || "ტვირთი")}</div><div class="muted small">${fmt(l.weight_kg)} კგ · ${esc(l.truck_label)}</div></div>
    <div><div class="line"><span class="ico pick"></span><span>${esc(l.origin_label)}${l.pickup_address ? ", " + esc(l.pickup_address) : ""}</span></div>
      <div class="line"><span class="ico drop"></span><span>${esc(l.destination_label)}${l.delivery_address ? ", " + esc(l.delivery_address) : ""}</span></div>
      <div class="line"><span class="ico date"></span><span class="num">${esc(l.pickup_date)}</span></div></div>
    <div>${l.shipper ? `<div class="cell-title">${esc(l.shipper.name)}</div><div>${stars(l.shipper.rating)}</div>
      <div class="line"><span class="ico">☎</span><a href="tel:+995${esc(l.shipper.phone)}">${esc(l.shipper.phone)}</a></div>
      <div class="muted small">${esc(l.shipper.legal_status_label)}</div>` : `<span class="muted small">კონტაქტი ჯავშნის შემდეგ ჩანს</span>`}</div>
    <div class="money num">${gel(t.kind === "offer" ? t.offer.price_gel : l.agreed_price_gel)}
      <div class="muted small">${t.kind === "offer" ? "თქვენი შეთავაზება" : "შეთანხმებული"}</div></div>
    <div>${action}${t.kind === "job" ? `<div style="margin-top:6px">${orderLink(l, true)}</div>` : ""}</div>
  </div>`;
}

// ---------------------------------------------------------------- driver: vehicles
async function renderVehicles() {
  const view = $("#view");
  let vs;
  try { vs = await api("/api/vehicles/mine"); } catch (err) { view.innerHTML = `<div class="empty">${esc(err.message)}</div>`; return; }
  view.innerHTML = `<div class="page-title"><h1>მანქანები</h1><span class="muted">ტვირთებს ტიპით, ტვირთამწეობით და ადგილით ვარჩევთ</span></div>
    <div class="grid-2">
      <div class="panel"><div class="panel-head"><h2>ჩემი მანქანები</h2><span class="muted">${vs.length}</span></div>
        ${vs.length ? `<table class="offers-table" style="border:0;border-radius:0"><thead><tr><th>მანქანა</th><th>სად დგას</th><th>სტატუსი</th></tr></thead><tbody>
          ${vs.map((v) => `<tr><td><b>${esc(v.truck_label)}</b>${v.plate ? ` · ${esc(v.plate)}` : ""}
              <div class="muted small">${fmt(v.capacity_kg)} კგ${v.liftgate ? " · ჰიდრ. ბორტი" : ""}${v.hazmat ? " · სახიფათო ტვირთი" : ""}</div></td>
            <td><select class="input city-select" data-vehicle-city="${v.id}" data-value="${v.city}" style="width:auto"></select></td>
            <td><button class="btn sm ${v.available ? "go" : "ghost"}" data-vehicle-free="${v.id}" data-free="${v.available}">
              ${v.available ? "თავისუფალი" : "დაკავებული"}</button></td></tr>`).join("")}</tbody></table>`
          : `<div class="empty"><b>მანქანა ჯერ არ გაქვთ</b>დაამატეთ მარჯვნივ: ამის შემდეგ ბირჟა შესაფერის ტვირთებს გაჩვენებთ.</div>`}
      </div>
      <form class="panel" id="vehicle-form"><div class="panel-head"><h2>მანქანის დამატება</h2></div>
        <div class="panel-body form-grid">
          <label class="field">ტიპი <select name="truck_type" class="type-select"></select></label>
          <label class="field">ტვირთამწეობა (კგ) <input name="capacity_kg" type="number" min="100" required></label>
          <label class="field">სად დგას ახლა <select name="city" class="city-select"></select></label>
          <label class="field">სახელმწიფო ნომერი <input name="plate" placeholder="AA-123-BB" required></label>
          <label class="field">საწვავი, ლ/100 კმ <input name="fuel_l_per_100km" type="number" step="0.1" placeholder="არასავალდებულო"></label>
          <label class="field">ცვეთა, ₾/კმ <input name="cost_per_km" type="number" step="0.01" placeholder="არასავალდებულო"></label>
          <label class="check"><input type="checkbox" name="liftgate"> ჰიდრავლიკური ბორტი</label>
          <label class="check"><input type="checkbox" name="hazmat"> სახიფათო ტვირთის ნებართვა</label>
          <p class="muted small wide" style="margin:0">საწვავს და ცვეთას თუ არ მიუთითებთ, ამ ტიპის ჩვეულებრივ მანქანას ავიღებთ (სიმულირებული მნიშვნელობა).</p>
          <div class="wide"><button class="btn">დამატება</button></div>
        </div></form>
    </div>`;
  fillSelects(view);
  $$("[data-vehicle-city]", view).forEach((s) => s.onchange = () => updateVehicle(s.dataset.vehicleCity, { city: s.value }));
  $$("[data-vehicle-free]", view).forEach((b) => b.onclick = () => updateVehicle(b.dataset.vehicleFree, { available: b.dataset.free !== "true" }));
  $("#vehicle-form").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/vehicles", { json: formData(e.target) }); toast("მანქანა დაემატა."); renderVehicles(); }
    catch (err) { toast(err.message, true); }
  };
}
async function updateVehicle(id, change) {
  try { await api(`/api/vehicles/${id}`, { json: change }); renderVehicles(); } catch (err) { toast(err.message, true); }
}

// ---------------------------------------------------------------- documents (both sides)
async function renderDocs() {
  const view = $("#view");
  view.innerHTML = `<div class="page-title"><h1>დოკუმენტები</h1>
      <span class="muted">AI კითხულობს, Python ადარებს ერთმანეთს. არაფერი ინახება.</span></div>
    <div class="grid-2">
      <div class="panel"><div class="panel-head"><h2>ერთი ტვირთის დოკუმენტები</h2></div><div class="panel-body">
        <label class="dropzone" id="drop"><input type="file" id="files" class="sr-only" multiple accept=".pdf,.jpg,.jpeg,.png,.webp">
          <strong>ჩააგდეთ ფაილები აქ ან დააჭირეთ</strong><span class="muted small">PDF, JPG, PNG · მაქს. 5 ფაილი, 10 MB</span></label>
        <div class="demo-row" id="demo-row">სადემონსტრაციო (სიმულაცია):</div>
        <ul class="ok-list" id="file-list" style="margin-bottom:12px"></ul>
        <button class="btn" id="check" disabled>შემოწმება</button>
        <div id="doc-result" style="margin-top:16px"></div>
      </div></div>
      <div class="panel"><div class="panel-head"><h2>რა წავიკითხეთ</h2></div><div class="panel-body" id="doc-read">
        <div class="empty">შემოწმების შემდეგ აქ გამოჩნდება თითოეული დოკუმენტი.</div></div></div>
    </div>`;
  let picked = [];
  const list = () => {
    $("#file-list").innerHTML = picked.map((f) => `<li>${esc(f.name)}</li>`).join("");
    $("#check").disabled = !picked.length;
  };
  $("#files").onchange = (e) => { picked = [...e.target.files]; list(); };
  const drop = $("#drop");
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); picked = [...e.dataTransfer.files]; list(); };
  $("#check").onclick = () => { const d = new FormData(); picked.forEach((f) => d.append("files", f)); runCheck(d); };
  try {
    const demos = await api("/api/paperwork/demo");
    demos.forEach((d) => {
      const b = document.createElement("button");
      b.className = "btn sm secondary"; b.textContent = d.id;
      b.onclick = async () => {
        const data = new FormData();
        for (const name of d.files) data.append("files", await (await fetch(`/api/paperwork/demo/${d.id}/${name}`)).blob(), name);
        picked = d.files.map((name) => ({ name })); list();
        runCheck(data);
      };
      $("#demo-row").appendChild(b);
    });
  } catch { /* no demo documents: nothing to show */ }
}

async function runCheck(data) {
  const out = $("#doc-result"), read = $("#doc-read");
  out.innerHTML = `<p class="muted">ვკითხულობ დოკუმენტებს… (ერთ წუთამდე)</p>`;
  try {
    const r = await api("/api/paperwork/check", { method: "POST", body: data });
    const problems = r.findings.filter((f) => f.severity === "problem"), notes = r.findings.filter((f) => f.severity !== "problem");
    const finding = (f) => `<div class="finding ${f.severity === "problem" ? "" : "note"}">${esc(f.detail)}
      ${f.action ? `<div class="todo">→ ${esc(f.action)}</div>` : ""}</div>`;
    out.innerHTML = `<div class="pills"><span class="pill" style="--c:#FF7A59"><span class="dot"></span>პრობლემა<span class="n">${problems.length}</span></span>
        <span class="pill" style="--c:#F2B705"><span class="dot"></span>შენიშვნა<span class="n">${notes.length}</span></span>
        <span class="pill" style="--c:#34C17B"><span class="dot"></span>ემთხვევა<span class="n">${r.agreements.length}</span></span></div>
      ${problems.map(finding).join("") || `<p class="pos">✓ პრობლემა არ მოიძებნა.</p>`}${notes.map(finding).join("")}
      ${r.agreements.length ? `<ul class="ok-list">${r.agreements.map((a) => `<li>${esc(a.detail)}</li>`).join("")}</ul>` : ""}
      ${r.draft_plan && r.draft_plan.available && S.me.role === "shipper"
        ? `<div class="detail-actions"><button class="btn" id="doc-draft">ტვირთის მონახაზი ამ დოკუმენტიდან</button></div>` : ""}`;
    read.innerHTML = r.documents.map((d) => `<div style="margin-bottom:14px"><b>${esc(d.name)}</b> <span class="chip sign">${esc(d.kind_label)}</span>
      ${d.load_number ? `<div class="muted small">ტვირთის № ${esc(d.load_number)}</div>` : ""}
      <dl class="facts">${[["აღება", d.pickup && d.pickup.address], ["მიტანა", d.delivery && d.delivery.address],
        ["წონა", d.weight != null ? `${d.weight} ${d.weight_unit || ""}` : null], ["ფასი", d.rate != null ? `${d.rate} ${d.currency || ""}` : null],
        ["გადამზიდი", d.carrier]].filter((x) => x[1]).map(([k, v]) => `<dt>${k}</dt><dd>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</dd>`).join("")}</dl></div>`).join("");
    const btn = $("#doc-draft");
    if (btn) btn.onclick = async () => {
      try { const d = await api("/api/paperwork/draft", { json: { check_id: r.check_id, values: {} } }); openChat(); draftCard(d); }
      catch (err) { toast(err.message, true); }
    };
  } catch (err) { out.innerHTML = `<p class="error-text">${esc(err.message)}</p>`; }
}

// ---------------------------------------------------------------- the assistant
const SUGGEST = {
  shipper: ["რა ღირს 5 ტონის გაგზავნა თბილისიდან ბათუმში?", "ვინ შემომთავაზა ჩემს ტვირთებზე?",
            "ხვალ ქუთაისიდან თბილისში 3 ტონა ავეჯი უნდა გავგზავნო"],
  driver: ["რომელი ტვირთი მაწყობს ყველაზე მეტად?", "ბათუმიდან თბილისისკენ უკან რამე ხომ არ არის?", "ჩემი რეისები"],
};
function renderSuggestions() {
  $("#suggestions").innerHTML = SUGGEST[S.me.role].map((s) => `<button>${esc(s)}</button>`).join("");
  $$("#suggestions button").forEach((b) => b.onclick = () => askAssistant(b.textContent));
}
function resetChatView() {
  $("#chat-log").innerHTML = `<div class="chat-empty"><strong>გამარჯობა!</strong>მკითხეთ ფასზე, ტვირთებზე ან შეთავაზებებზე.
    ყველა რიცხვი სისტემიდან მოდის; ცვლილებას თქვენ ადასტურებთ.</div>`;
}
function openChat() {
  $("#workspace").classList.remove("chat-closed");
  $("#chat-toggle").setAttribute("aria-expanded", "true");
}
function addMsg(cls, html) {
  $(".chat-empty", $("#chat-log"))?.remove();
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  div.innerHTML = html;
  $("#chat-log").appendChild(div);
  $("#chat-log").scrollTop = 1e9;
  return div;
}
const markdown = (text) => DOMPurify.sanitize(marked.parse(text || ""));

function askAssistant(text) {
  openChat();
  $("#chat-input").value = text;
  sendChat();
}

async function sendChat(e) {
  if (e) e.preventDefault();
  const input = $("#chat-input"), text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", esc(text));
  const wait = document.createElement("div");
  wait.className = "thinking"; wait.textContent = "ვფიქრობ…";
  $("#chat-log").appendChild(wait);
  try {
    const r = await api("/api/chat", { json: { message: text } });
    wait.remove();
    const msg = addMsg("bot" + (r.ai_available ? "" : " offline"), markdown(r.reply));
    if (r.unverified_numbers && r.unverified_numbers.length)
      msg.insertAdjacentHTML("beforeend", `<div class="warn">⚠️ ეს რიცხვები ვერ შემოწმდა: ${esc(r.unverified_numbers.join(", "))}</div>`);
    (r.drafts || []).forEach(draftCard);
  } catch (err) { wait.remove(); addMsg("bot offline", esc(err.message)); }
}

function draftCard(d) {
  const x = d.draft;
  const rows = d.kind === "load"
    ? [["მარშრუტი", `${x.origin_label} → ${x.destination_label}`], ["მანქანა", x.truck_label], ["წონა", `${fmt(x.weight_kg)} კგ`],
       ["აღება", x.pickup_date], ["ფასი", gel(x.price_gel)], ["ტვირთი", x.cargo],
       ["სამართლიანი", d.price_check ? `${gel(d.price_check.fair_price_range_gel[0])} – ${gel(d.price_check.fair_price_range_gel[1])} · ${d.price_check.verdict_label}` : null]]
    : [["ტვირთი", `№${x.load_id}: ${x.route}`], ["აღება", x.pickup_date], ["მანქანა", x.truck_label],
       ["თქვენი ფასი", gel(x.price_gel)], ["გამგზავნის ფასი", gel(x.shipper_price_gel)],
       ["ხარჯი", d.earnings ? `≈ ${gel(d.earnings.trip_costs_gel)}` : null],
       ["დაგრჩებათ", d.earnings ? `≈ ${gel(d.earnings.driver_keeps_gel)}` : null], ["შეტყობინება", x.message]];
  const card = document.createElement("div");
  card.className = "draft";
  card.innerHTML = `<h4>${d.kind === "load" ? "ტვირთის მონახაზი" : "შეთავაზების მონახაზი"}<span>შეუნახავი</span></h4>
    <dl class="facts">${rows.filter((r) => r[1]).map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <div class="btns"><button class="btn sm go">დადასტურება</button><button class="btn sm ghost">გაუქმება</button></div>`;
  $(".chat-empty", $("#chat-log"))?.remove();
  $("#chat-log").appendChild(card);
  $("#chat-log").scrollTop = 1e9;
  const [ok, no] = $$("button", card);
  ok.onclick = async () => {
    try {
      const saved = await api(`/api/drafts/${d.draft_id}/confirm`, { json: {} });
      card.classList.add("saved");
      $(".btns", card).innerHTML = `<span class="pos">✓ ${d.kind === "load" ? `ტვირთი №${saved.id} გამოქვეყნდა` : "შეთავაზება გაიგზავნა"}</span>`;
      refresh();
    } catch (err) { toast(err.message, true); }
  };
  no.onclick = async () => {
    await api(`/api/drafts/${d.draft_id}/reject`, { json: {} }).catch(() => {});
    card.classList.add("cancelled");
    $(".btns", card).innerHTML = `<span class="muted">გაუქმდა</span>`;
  };
}

// ---------------------------------------------------------------- start
(async () => {
  S.meta = await api("/api/meta");
  fillSelects();
  $("#legal-select").innerHTML = Object.entries(S.meta.legal_statuses).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#login-form").onsubmit = login;
  $("#register-form").onsubmit = register;
  $$("#register-form input[name=role]").forEach((r) => r.onchange = showTruckBox);
  $("#register-form [name=city]").onchange = (e) => { $("#register-form [name=v_city]").value = e.target.value; };
  $$("[data-demo]").forEach((b) => b.onclick = () => {
    $("#login-form [name=phone]").value = b.dataset.demo;
    $("#login-form [name=password]").value = "demo1234";
    $("#login-form").requestSubmit();
  });
  $("#composer").onsubmit = sendChat;
  $("#chat-input").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } };
  $("#chat-toggle").onclick = () => {
    const closed = $("#workspace").classList.toggle("chat-closed");
    $("#chat-toggle").setAttribute("aria-expanded", String(!closed));
    if (S.map) setTimeout(() => S.map.invalidateSize(), 50);
  };
  $("#chat-close").onclick = () => $("#chat-toggle").click();
  $("#chat-reset").onclick = async () => { await api("/api/chat/reset", { json: {} }).catch(() => {}); resetChatView(); };
  $("#logout").onclick = async () => {
    await api("/api/logout", { json: {} }).catch(() => {});
    S.me = null; $("#app-tabs").innerHTML = ""; delete $("#app-tabs").dataset.role;
    go("#/");
  };
  if (window.innerWidth < 1250) $("#chat-toggle").click();   // on small screens the panel starts closed
  try { S.me = await api("/api/me"); } catch { S.me = null; }
  if (S.me) resetChatView();
  window.addEventListener("hashchange", route);
  route();
})();
