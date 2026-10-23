(function () {
  "use strict";

  const state = { results: [], selected: new Set(), query: "", view: "map", meta: null, map: null, markers: [], recognition: null };
  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value == null ? "" : value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  const fa = (value) => Number(value || 0).toLocaleString("fa-IR");
  const money = (value) => fa(Math.round(Number(value || 0)));
  const cleanText = (value) => String(value == null ? "" : value).replace(/\s*\([^)]*[A-Za-z][^)]*\)/g, "").replace(/\b(Black|Blue|Purple|title)\b/gi, "").replace(/\s{2,}/g, " ").replace(/^[،,\s]+|[،,\s]+$/g, "").trim();
  const warrantyLabel = (value) => {
    if (!value) return "گارانتی نامشخص";
    try {
      const data = typeof value === "string" && value.trim().startsWith("{") ? JSON.parse(value) : value;
      const parts = [data.description, data.provider, data.period_months ? data.period_months + " ماه" : ""].filter(Boolean).map(cleanText);
      return parts.join(" · ") || "گارانتی نامشخص";
    } catch (error) { return cleanText(value) || "گارانتی نامشخص"; }
  };
  const byId = (id) => state.results.find((item) => item.product_id === id);
  const latinDigits = (value) => String(value || "").replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit))).replace(/[٬,]/g, "");

  function currentFilters() {
    const budgetMillions = Number($("budgetInput").value || 0);
    return { budget_max: budgetMillions ? String(budgetMillions * 1000000) : "", location: $("locationSelect").value, radius_km: $("radiusInput").value, sort: $("sortSelect").value, lat: "35.694", lon: "51.412" };
  }

  function resultTitle(query, total) {
    if (!query) return "برای شروع، یک نیاز خرید بنویس";
    if (!total) return "برای این ترکیب، گزینه‌ی مناسبی پیدا نشد";
    return "گزینه‌های پیشنهادی برای «" + query + "»";
  }

  function formatFreshness(item) {
    const fresh = item && item.freshness ? item.freshness : { label: "به‌روز بودن نامشخص", tone: "muted" };
    const label = fresh.tone === "fresh" ? "به‌روز" : fresh.tone === "warm" ? "نسبتاً به‌روز" : "قدیمی‌تر";
    return { label: label, tone: fresh.tone || "muted" };
  }

  function cardHtml(item) {
    const first = (item.offers || [])[0] || {};
    const fresh = formatFreshness(first);
    const image = item.image_url ? '<img class="product-visual" src="' + escapeHtml(item.image_url) + '" alt="تصویر ' + escapeHtml(item.title) + '" loading="lazy" onerror="this.remove()">' : '<div class="product-placeholder">✦</div>';
    const reasons = (item.reasons || []).slice(0, 3).map((reason) => '<span class="reason-chip">' + escapeHtml(reason.replace(/ثبت‌شده در داده|طبق ساعت ثبت‌شده|اعلام‌شده/g, "").replace(/\s{2,}/g, " ").trim()) + "</span>").join("");
    const selected = state.selected.has(item.product_id);
    const preferred = state.results.length && state.results[0].product_id === item.product_id ? '<span class="reason-chip preferred-chip">ترجیح تربچه</span>' : "";
    return '<article class="product-card ' + (selected ? "selected" : "") + '" data-card="' + escapeHtml(item.product_id) + '">' +
      '<div class="card-top">' + image + '<button class="compare-check ' + (selected ? "checked" : "") + '" data-compare="' + escapeHtml(item.product_id) + '" aria-label="افزودن به مقایسه">' + (selected ? "✓" : "") + '</button><span class="card-fresh ' + escapeHtml(fresh.tone) + '">' + escapeHtml(fresh.label) + '</span></div>' +
      '<div class="card-body"><div class="card-category">' + escapeHtml(item.category || "محصول") + '</div><h3 class="card-title">' + escapeHtml(item.title) + '</h3>' +
      '<div class="price-row"><div><span class="price-value">' + money(item.best_price) + '</span><span class="price-unit">تومان</span><small class="confidence-label">' + escapeHtml(item.price_confidence || "قیمت قابل مقایسه") + '</small></div><span class="offer-count">' + fa(item.shop_count) + ' فروشنده</span></div>' +
      '<div class="reason-list">' + preferred + reasons + '</div><button class="card-action" data-detail="' + escapeHtml(item.product_id) + '" type="button">دیدن فروشنده‌ها و جزئیات <span>←</span></button></div></article>';
  }

  function renderResults(payload, query) {
    state.results = payload.results || [];
    state.query = query || "";
    if (payload.meta) state.meta = payload.meta;
    $("resultsTitle").textContent = resultTitle(state.query, state.results.length);
    $("resultCount").textContent = state.results.length ? fa(state.results.length) + " گزینه" : "";
    const grid = $("productGrid");
    grid.classList.toggle("list-view", state.view === "grid" ? false : false);
    if (!state.results.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-orbit"><span>⌕</span></div><h3>برای این جست‌وجو گزینه‌ای نداریم</h3><p>عبارت، بودجه یا محدوده را کمی بازتر کن تا تربچه انتخاب‌های بیشتری را بررسی کند.</p></div>';
      $("evidenceBanner").hidden = true;
      renderMap([]);
      updateCompareTray();
      return;
    }
    $("evidenceBanner").hidden = false;
    const valid = payload.meta && payload.meta.valid_offers ? fa(payload.meta.valid_offers) : "داده‌های معتبر";
    $("evidenceText").textContent = "تربچه از " + valid + " قیمت معتبر، فاصله و شرایط فروشنده را با هم مقایسه کرده است.";
    grid.innerHTML = state.results.map(cardHtml).join("");
    grid.querySelectorAll("[data-compare]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); toggleCompare(button.dataset.compare); }));
    grid.querySelectorAll("[data-detail]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); showProduct(button.dataset.detail); }));
    grid.querySelectorAll("[data-card]").forEach((card) => card.addEventListener("click", () => showProduct(card.dataset.card)));
    renderMap(state.results);
    updateCompareTray();
    if (state.view === "map") showMapView(); else showGridView();
  }

  function ensureMap() {
    if (!window.L || state.map) return;
    state.map = window.L.map("mapCanvas", { zoomControl: false, attributionControl: true }).setView([35.694, 51.412], 11);
    window.L.control.zoom({ position: "bottomright" }).addTo(state.map);
    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(state.map);
  }

  function renderMap(results) {
    ensureMap();
    if (!state.map) return;
    state.markers.forEach((marker) => marker.remove());
    state.markers = [];
    const shops = {};
    results.forEach((item) => (item.offers || []).forEach((offer) => { if (!shops[offer.shop_id]) shops[offer.shop_id] = { ...offer, product_id: item.product_id }; }));
    const rows = Object.values(shops).filter((shop) => Number.isFinite(Number(shop.lat)) && Number.isFinite(Number(shop.lon)));
    $("mapCount").textContent = fa(rows.length) + " فروشگاه";
    if (!rows.length) {
      $("shopList").innerHTML = '<div class="shop-list-empty">پس از جست‌وجو فروشگاه‌ها اینجا دیده می‌شوند.</div>';
      state.map.setView([35.694, 51.412], 11);
      return;
    }
    rows.forEach((shop) => {
      const marker = window.L.marker([Number(shop.lat), Number(shop.lon)]).addTo(state.map);
      marker.bindPopup('<strong>' + escapeHtml(shop.shop_name) + '</strong><br>' + money(shop.price_toman) + ' تومان');
      state.markers.push(marker);
    });
    const bounds = window.L.latLngBounds(rows.map((shop) => [Number(shop.lat), Number(shop.lon)]));
    state.map.fitBounds(bounds.pad(.16), { maxZoom: 14 });
    $("shopList").innerHTML = rows.slice(0, 8).map((shop) => '<button class="shop-row" type="button" data-shop-product="' + escapeHtml(shop.product_id) + '"><span class="shop-row-dot"></span><span class="shop-row-body"><strong>' + escapeHtml(shop.shop_name) + '</strong><span>' + escapeHtml(shop.location_label || "تهران") + (shop.distance_km ? " · " + fa(shop.distance_km) + " km" : "") + '</span></span><span class="shop-row-price">' + money(shop.price_toman) + '</span></button>').join("");
    $("shopList").querySelectorAll("[data-shop-product]").forEach((row) => row.addEventListener("click", () => showProduct(row.dataset.shopProduct)));
    setTimeout(() => state.map && state.map.invalidateSize(), 50);
  }

  function showMapView() {
    state.view = "map";
    $("productGrid").hidden = true;
    $("mapPanel").hidden = false;
    document.querySelectorAll(".view-toggle").forEach((button) => button.classList.toggle("active", button.dataset.view === "map"));
    setTimeout(() => state.map && state.map.invalidateSize(), 40);
  }
  function showGridView() {
    state.view = "grid";
    $("productGrid").hidden = false;
    $("mapPanel").hidden = true;
    document.querySelectorAll(".view-toggle").forEach((button) => button.classList.toggle("active", button.dataset.view === "grid"));
  }

  async function search(query) {
    const q = (query || $("searchInput").value || "").trim();
    if (!q) return;
    $("searchInput").value = q;
    const params = new URLSearchParams({ q });
    const filters = currentFilters();
    Object.keys(filters).forEach((key) => { if (filters[key] !== "") params.set(key, filters[key]); });
    $("loadingOverlay").hidden = false;
    document.body.classList.add("is-searching");
    $("resultsTitle").textContent = "تربچه در حال جست‌وجوست…";
    const started = Date.now();
    try {
      const response = await fetch("/api/search?" + params.toString());
      const payload = await response.json();
      const wait = Math.max(0, 850 - (Date.now() - started));
      await new Promise((resolve) => setTimeout(resolve, wait));
      renderResults(payload, q);
      $("filterPanel").classList.add("compact");
      $("searchState").hidden = false;
    } catch (error) {
      $("resultsTitle").textContent = "اتصال به کاتالوگ برقرار نشد";
    } finally {
      $("loadingOverlay").hidden = true;
      document.body.classList.remove("is-searching");
    }
  }

  function appendMessage(type, text) {
    const wrapper = document.createElement("div");
    wrapper.className = "message " + (type === "user" ? "user-message" : "agent-message");
    wrapper.innerHTML = type === "user" ? '<div><p>' + escapeHtml(text) + '</p></div><div class="message-badge">من</div>' : '<div class="message-badge">ت</div><div><p>' + escapeHtml(text) + '</p></div>';
    $("conversation").appendChild(wrapper);
    $("conversation").scrollTop = $("conversation").scrollHeight;
  }

  async function askAgent(text) {
    const message = (text || $("assistantInput").value || "").trim();
    if (!message) return;
    $("assistantInput").value = "";
    appendMessage("user", message);
    $("assistantSuggestions").hidden = true;
    try {
      const response = await fetch("/api/assistant", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, filters: currentFilters(), selected_ids: Array.from(state.selected) }) });
      const payload = await response.json();
      appendMessage("agent", payload.reply || "نتیجه آماده است.");
      renderResults({ results: payload.results || [], meta: payload.evidence && payload.evidence.catalog_rows }, message);
      $("filterPanel").classList.add("compact");
      if (payload.suggestions) {
        $("assistantSuggestions").innerHTML = payload.suggestions.slice(0, 3).map((item) => '<button data-prompt="' + escapeHtml(item) + '" type="button">' + escapeHtml(item) + '</button>').join("");
        bindPromptButtons($("assistantSuggestions"));
        $("assistantSuggestions").hidden = false;
      }
    } catch (error) { appendMessage("agent", "ارتباط با تربچه قطع شد؛ می‌توانی همین عبارت را از نوار جست‌وجو امتحان کنی."); }
  }

  function toggleCompare(id) { if (state.selected.has(id)) state.selected.delete(id); else if (state.selected.size < 3) state.selected.add(id); else return; renderResults({ results: state.results, meta: state.meta }, state.query); updateCompareTray(); }
  function updateCompareTray() { $("compareTray").hidden = state.selected.size === 0; $("compareCount").textContent = fa(state.selected.size); }

  async function showMockContact(shopId, shopName, phone) {
    $("contactModalTitle").textContent = "تماس تربچه با فروشنده";
    $("contactModalLead").textContent = "تربچه در حال آماده‌سازی تماس با «" + shopName + "» است.";
    $("contactStatus").innerHTML = '<div class="mock-contact-icon"><div class="loading-spinner"></div></div><strong>در حال تماس با ' + escapeHtml(shopName) + '</strong><p>تربچه اطلاعات گزینه را برای فروشنده آماده می‌کند…</p>';
    $("contactModal").hidden = false;
    let payload = null;
    try { payload = await (await fetch("/api/contact", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shop_id: shopId, channel: "mock_call" }) })).json(); } catch (error) {}
    await new Promise((resolve) => setTimeout(resolve, 1200));
    const outcomes = ["فروشنده پاسخ داد؛ موجودی و قیمت برای بررسی حضوری آماده شد.", "فروشنده در دسترس بود؛ پیشنهاد شد قبل از حرکت یک‌بار دیگر قیمت را چک کنی.", "پیام تربچه به فروشنده رسید؛ پاسخ نهایی هنگام مراجعه تأیید می‌شود."];
    const outcome = outcomes[Math.floor(Math.random() * outcomes.length)];
    $("contactModalLead").textContent = "نتیجه‌ی تماس نمایشی برای «" + shopName + "»";
    $("contactStatus").innerHTML = '<div class="mock-contact-icon">✓</div><strong>تماس تربچه با فروشنده انجام شد</strong><p>' + outcome + '</p><small>این نتیجه برای دمو ساخته شده و خرید یا موجودی را تضمین نمی‌کند.' + (payload && payload.contact && phone ? " شماره‌ی نمونه: " + escapeHtml(phone) : "") + '</small>';
  }

  function showProduct(id) {
    const item = byId(id); if (!item) return;
    const offers = item.offers || [];
    $("productModalTitle").textContent = item.title;
    $("productModalLead").textContent = "کمترین قیمت " + money(item.best_price) + " تومان است؛ فروشنده‌ی مناسب را انتخاب کن و بعد برای مراجعه تماس بگیر.";
    const reasons = (item.reasons || []).map((reason) => '<li>' + escapeHtml(reason.replace(/ثبت‌شده در داده|طبق ساعت ثبت‌شده|اعلام‌شده/g, "").trim()) + '</li>').join("");
    const specs = (item.specs || []).filter((spec) => spec && spec.key && spec.value && String(spec.key).toLowerCase() !== "title").slice(0, 6);
    const specRows = specs.length ? specs.map((spec) => '<div><span>' + escapeHtml(cleanText(spec.key)) + '</span><b>' + escapeHtml(cleanText(spec.value)) + '</b></div>').join("") : '<div class="unknown-field">مشخصات فنی برای این محصول ثبت نشده است.</div>';
    $("productContext").innerHTML = '<div class="product-insights"><section class="review-panel"><div class="insight-kicker">چرا این گزینه؟</div><strong>انتخاب تربچه بر اساس اطلاعات موجود</strong><p>قیمت کمتر، فاصله‌ی مناسب و وضعیت فروشنده در این نتیجه در نظر گرفته شده است.</p><ul>' + (reasons || '<li>مقایسه‌ی قیمت و فروشنده انجام شد.</li>') + '</ul></section><section class="spec-panel"><div class="insight-kicker">مشخصات محصول</div>' + specRows + '</section></div>';
    $("offerList").innerHTML = offers.map((offer) => {
      const phone = ((offer.contacts || []).find((contact) => contact.channel === "phone" && contact.display_number) || {}).display_number || "";
      const status = (offer.open_status || {}).key === "open" ? "باز است" : "ساعت کاری نامشخص";
      const freshness = formatFreshness(offer).label;
      return '<article class="offer-row"><div class="offer-main"><strong>' + escapeHtml(offer.shop_name) + '</strong><span>' + escapeHtml(offer.address || offer.location_label || "آدرس ثبت نشده") + '</span><small>' + escapeHtml(status) + ' · ' + escapeHtml(freshness) + '</small></div><div class="offer-side"><b>' + money(offer.price_toman) + ' <small>تومان</small></b><span>' + escapeHtml(warrantyLabel(offer.warranty)) + '</span><button type="button" class="offer-contact" data-contact-shop="' + escapeHtml(offer.shop_id) + '" data-contact-name="' + escapeHtml(offer.shop_name) + '" data-contact-phone="' + escapeHtml(phone) + '">تماس تربچه با فروشنده</button></div></article>';
    }).join("");
    $("offerList").querySelectorAll("[data-contact-shop]").forEach((button) => button.addEventListener("click", () => showMockContact(button.dataset.contactShop, button.dataset.contactName, button.dataset.contactPhone)));
    $("productModal").hidden = false;
  }

  function openCompare() {
    const selected = Array.from(state.selected).map(byId).filter(Boolean); if (!selected.length) return;
    $("compareHead").innerHTML = "<tr><th>معیار</th>" + selected.map((item) => '<th>' + escapeHtml(item.title) + '</th>').join("") + "</tr>";
    const rows = [["کمترین قیمت", (item) => money(item.best_price) + " تومان"], ["تعداد فروشنده", (item) => fa(item.shop_count) + " فروشنده"], ["چرا پیشنهاد شد؟", (item) => (item.reasons || []).slice(0, 2).join("، ") || "مقایسه‌ی قیمت و فاصله"], ["فروشنده‌ی اول", (item) => item.offers && item.offers[0] ? item.offers[0].shop_name : "—"]];
    $("compareBody").innerHTML = rows.map((row) => '<tr><td>' + escapeHtml(row[0]) + '</td>' + selected.map((item) => '<td>' + escapeHtml(row[1](item)) + '</td>').join("") + '</tr>').join("");
    $("compareModal").hidden = false;
  }

  function bindPromptButtons(scope) { scope.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { $("searchInput").value = button.dataset.prompt; search(button.dataset.prompt); if (scope.id === "assistantSuggestions") askAgent(button.dataset.prompt); })); }

  async function loadMeta() {
    try {
      const meta = await (await fetch("/api/meta")).json(); state.meta = meta;
      $("catalogStat").textContent = fa(meta.products) + " محصول · " + fa(meta.shops) + " فروشگاه";
      (meta.locations || []).forEach((location) => { const option = document.createElement("option"); option.value = location.name; option.textContent = location.name + " (" + fa(location.count) + ")"; $("locationSelect").appendChild(option); });
    } catch (error) { $("catalogStat").textContent = "حالت نمونه"; }
  }

  function setTheme(theme) { document.documentElement.dataset.theme = theme; $("themeToggle").textContent = theme === "dark" ? "☀" : "☾"; localStorage.setItem("torbche-theme", theme); if (state.map) setTimeout(() => state.map.invalidateSize(), 50); }

  function setupVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { $("voiceButton").title = "جست‌وجوی صوتی در این مرورگر فعال نیست"; return; }
    state.recognition = new SpeechRecognition(); state.recognition.lang = "fa-IR"; state.recognition.interimResults = false; state.recognition.maxAlternatives = 1;
    state.recognition.onstart = () => $("voiceButton").classList.add("listening"); state.recognition.onend = () => $("voiceButton").classList.remove("listening"); state.recognition.onerror = () => $("voiceButton").classList.remove("listening");
    state.recognition.onresult = (event) => { const text = event.results[0][0].transcript; $("searchInput").value = text; search(text); };
    $("voiceButton").addEventListener("click", () => { try { state.recognition.start(); } catch (error) {} });
  }

  $("searchForm").addEventListener("submit", (event) => { event.preventDefault(); search(); });
  $("assistantForm").addEventListener("submit", (event) => { event.preventDefault(); askAgent(); });
  $("budgetInput").addEventListener("input", () => { const value = Number($("budgetInput").value); $("budgetValue").textContent = value ? "تا " + fa(value) + " میلیون" : "بدون محدودیت"; });
  $("radiusInput").addEventListener("input", () => { $("radiusValue").textContent = fa($("radiusInput").value); });
  ["budgetInput", "locationSelect", "radiusInput", "sortSelect"].forEach((id) => $(id).addEventListener("change", () => { if (state.query) search(state.query); }));
  $("resetFilters").addEventListener("click", () => { $("budgetInput").value = 0; $("budgetValue").textContent = "بدون محدودیت"; $("locationSelect").value = ""; $("radiusInput").value = 8; $("radiusValue").textContent = "۸"; $("sortSelect").value = "relevance"; if (state.query) search(state.query); });
  $("filterToggle").addEventListener("click", () => $("filterPanel").classList.toggle("compact"));
  $("clearCompare").addEventListener("click", () => { state.selected.clear(); updateCompareTray(); renderResults({ results: state.results, meta: state.meta }, state.query); });
  $("openCompare").addEventListener("click", openCompare);
  $("closeCompare").addEventListener("click", () => $("compareModal").hidden = true); $("compareModal").addEventListener("click", (event) => { if (event.target === $("compareModal")) $("compareModal").hidden = true; });
  $("openAbout").addEventListener("click", () => $("aboutModal").hidden = false); $("closeAbout").addEventListener("click", () => $("aboutModal").hidden = true); $("aboutModal").addEventListener("click", (event) => { if (event.target === $("aboutModal")) $("aboutModal").hidden = true; });
  $("closeProduct").addEventListener("click", () => $("productModal").hidden = true); $("productModal").addEventListener("click", (event) => { if (event.target === $("productModal")) $("productModal").hidden = true; });
  $("closeContact").addEventListener("click", () => $("contactModal").hidden = true); $("closeContactAction").addEventListener("click", () => $("contactModal").hidden = true); $("contactModal").addEventListener("click", (event) => { if (event.target === $("contactModal")) $("contactModal").hidden = true; });
  $("clearChat").addEventListener("click", () => { $("conversation").innerHTML = '<div class="message agent-message"><div class="message-badge">ت</div><div><p>گفت‌وگو پاک شد. محصول یا محدوده‌ی بعدی را بگو.</p></div></div>'; $("assistantSuggestions").hidden = false; });
  document.querySelectorAll(".view-toggle").forEach((button) => button.addEventListener("click", () => { if (button.dataset.view === "map") showMapView(); else showGridView(); }));
  $("themeToggle").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  bindPromptButtons(document); loadMeta(); setupVoice(); setTheme(localStorage.getItem("torbche-theme") || "light"); ensureMap(); showMapView();
})();
