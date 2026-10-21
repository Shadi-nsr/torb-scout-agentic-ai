(function () {
  "use strict";

  const state = {
    results: [],
    selected: new Set(),
    query: "",
    view: "grid",
    meta: null,
    lastAssistant: null
  };

  const $ = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  const fa = (value) => Number(value || 0).toLocaleString("fa-IR");
  const money = (value) => fa(Math.round(Number(value || 0)));
  const byId = (id) => state.results.find((item) => item.product_id === id);
  const latinDigits = (value) => String(value || "").replace(/[۰-۹]/g, function (digit) {
    return String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit));
  }).replace(/[٬,]/g, "");

  function currentFilters() {
    const budget = latinDigits($("budgetInput").value.trim());
    return {
      budget_max: budget ? budget.replace(/[^\d.]/g, "") : "",
      location: $("locationSelect").value,
      radius_km: $("radiusInput").value,
      sort: $("sortSelect").value,
      lat: "35.694",
      lon: "51.412"
    };
  }

  function updateTrace(plan) {
    const trace = $("agentTrace");
    if (!plan || !plan.length) {
      trace.hidden = true;
      return;
    }
    trace.hidden = false;
    $("traceSteps").innerHTML = plan.map(function (step, index) {
      return '<div class="trace-step"><b>' + (index + 1) + '</b><span title="' +
        escapeHtml(step.detail) + '">' + escapeHtml(step.label) + '</span></div>';
    }).join("");
  }

  function resultTitle(query, total) {
    if (!query) return "برای شروع، یک نیاز خرید بنویس";
    if (!total) return "برای این ترکیب، نتیجه‌ی قابل اتکا پیدا نشد";
    return "گزینه‌های پیشنهادی برای «" + query + "»";
  }

  function renderResults(payload, query) {
    state.results = payload.results || [];
    state.query = query || "";
    $("resultsTitle").textContent = resultTitle(state.query, state.results.length);
    $("resultCount").textContent = state.results.length ? fa(state.results.length) + " گزینه" : "";
    const grid = $("productGrid");
    grid.classList.toggle("list-view", state.view === "list");
    if (!state.results.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-orbit"><span>⌕</span></div><h3>نتیجه‌ی کافی نداریم</h3><p>عبارت محصول یا محدوده را کمی بازتر کن تا گزینه‌های بیشتری بررسی کنم.</p></div>';
      renderMap([]);
      return;
    }
    grid.innerHTML = state.results.map(cardHtml).join("");
    grid.querySelectorAll("[data-compare]").forEach(function (button) {
      button.addEventListener("click", function () { toggleCompare(button.dataset.compare); });
    });
    grid.querySelectorAll("[data-detail]").forEach(function (button) {
      button.addEventListener("click", function () { showProduct(button.dataset.detail); });
    });
    renderMap(state.results);
    updateCompareTray();
  }

  function cardHtml(item) {
    const first = (item.offers || [])[0] || {};
    const fresh = first.freshness || { label: "تازگی نامشخص", tone: "muted" };
    const image = item.image_url ? '<img class="product-visual" src="' + escapeHtml(item.image_url) + '" alt="" loading="lazy" onerror="this.remove()">'
      : '<div class="product-placeholder">✦</div>';
    const reasons = (item.reasons || []).slice(0, 3).map(function (reason) {
      return '<span class="reason-chip">' + escapeHtml(reason) + "</span>";
    }).join("");
    const selected = state.selected.has(item.product_id);
    return '<article class="product-card ' + (selected ? "selected" : "") + '" data-card="' + escapeHtml(item.product_id) + '">' +
      '<div class="card-top">' + image +
      '<button class="compare-check ' + (selected ? "checked" : "") + '" data-compare="' + escapeHtml(item.product_id) + '" aria-label="افزودن به مقایسه">' + (selected ? "✓" : "") + "</button>" +
      '<span class="card-fresh ' + escapeHtml(fresh.tone) + '">' + escapeHtml(fresh.label) + "</span></div>" +
      '<div class="card-body"><div class="card-category">' + escapeHtml(item.category || "دسته‌بندی نامشخص") + "</div>" +
      '<h3 class="card-title">' + escapeHtml(item.title) + "</h3>" +
      '<div class="price-row"><div><span class="price-value">' + money(item.best_price) + '</span><span class="price-unit">تومان</span></div><span class="offer-count">' + fa(item.shop_count) + " فروشنده</span></div>" +
      '<div class="reason-list">' + reasons + "</div>" +
      '<button class="card-action" data-detail="' + escapeHtml(item.product_id) + '">دیدن فروشنده‌ها و جزئیات <span>←</span></button></div></article>';
  }

  function renderMap(results) {
    const canvas = $("mapCanvas");
    canvas.querySelectorAll(".map-pin").forEach((pin) => pin.remove());
    const shops = {};
    results.forEach(function (item) {
      (item.offers || []).forEach(function (offer) {
        if (!shops[offer.shop_id]) shops[offer.shop_id] = offer;
      });
    });
    const rows = Object.values(shops);
    $("mapCount").textContent = fa(rows.length) + " فروشگاه";
    if (!rows.length) {
      $("shopList").innerHTML = '<div class="shop-list-empty">پس از جست‌وجو فروشگاه‌ها اینجا دیده می‌شوند.</div>';
      return;
    }
    const lats = rows.map((shop) => Number(shop.lat)).filter(Boolean);
    const lons = rows.map((shop) => Number(shop.lon)).filter(Boolean);
    const minLat = Math.min.apply(null, lats) - .004, maxLat = Math.max.apply(null, lats) + .004;
    const minLon = Math.min.apply(null, lons) - .004, maxLon = Math.max.apply(null, lons) + .004;
    rows.forEach(function (shop) {
      const x = ((Number(shop.lon) - minLon) / Math.max(.001, maxLon - minLon)) * 82 + 9;
      const y = (1 - (Number(shop.lat) - minLat) / Math.max(.001, maxLat - minLat)) * 74 + 12;
      const pin = document.createElement("button");
      pin.className = "map-pin";
      pin.style.left = Math.max(7, Math.min(92, x)) + "%";
      pin.style.top = Math.max(8, Math.min(89, y)) + "%";
      pin.title = shop.shop_name + " — " + money(shop.price_toman) + " تومان";
      canvas.appendChild(pin);
    });
    $("shopList").innerHTML = rows.slice(0, 7).map(function (shop) {
      return '<div class="shop-row"><span class="shop-row-dot"></span><div><strong>' + escapeHtml(shop.shop_name) + '</strong><span>' +
        escapeHtml(shop.location_label || "تهران") + (shop.distance_km ? " · " + fa(shop.distance_km) + " km" : "") +
        "</span></div><span class=\"shop-row-price\">" + money(shop.price_toman) + "</span></div>";
    }).join("");
  }

  async function search(query, trace) {
    const q = (query || $("searchInput").value || "").trim();
    if (!q) return;
    $("searchInput").value = q;
    const params = new URLSearchParams({ q: q });
    const filters = currentFilters();
    Object.keys(filters).forEach(function (key) { if (filters[key] !== "") params.set(key, filters[key]); });
    $("resultsTitle").textContent = "در حال جست‌وجوی کاتالوگ…";
    try {
      const response = await fetch("/api/search?" + params.toString());
      const payload = await response.json();
      renderResults(payload, q);
      if (trace) updateTrace(trace);
      sendTelemetry("search", { query: q, total: payload.total });
    } catch (error) {
      $("resultsTitle").textContent = "اتصال به کاتالوگ برقرار نشد";
    }
  }

  function appendMessage(type, text, plan) {
    const conversation = $("conversation");
    const wrapper = document.createElement("div");
    wrapper.className = "message " + (type === "user" ? "user-message" : "agent-message");
    if (type === "user") {
      wrapper.innerHTML = '<div><p>' + escapeHtml(text) + "</p></div><div class=\"message-badge\">من</div>";
    } else {
      let planHtml = "";
      if (plan && plan.length) {
        planHtml = '<div class="assistant-plan"><div class="assistant-plan-title">مسیر تصمیم عامل</div>' +
          plan.map(function (step, index) {
            return '<div class="assistant-plan-row"><b>' + (index + 1) + "</b><span>" + escapeHtml(step.label) + "</span></div>";
          }).join("") + "</div>";
      }
      wrapper.innerHTML = '<div class="message-badge">TS</div><div><p>' + escapeHtml(text) + "</p>" + planHtml + "</div>";
    }
    conversation.appendChild(wrapper);
    conversation.scrollTop = conversation.scrollHeight;
  }

  async function askAgent(text) {
    const message = (text || $("assistantInput").value || "").trim();
    if (!message) return;
    $("assistantInput").value = "";
    appendMessage("user", message);
    $("assistantSuggestions").hidden = true;
    try {
      const response = await fetch("/api/assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message, filters: currentFilters(), selected_ids: Array.from(state.selected) })
      });
      const payload = await response.json();
      state.lastAssistant = payload;
      appendMessage("agent", payload.reply || "نتیجه آماده است.", payload.plan);
      renderResults({ results: payload.results || [] }, message);
      updateTrace(payload.plan);
      if (payload.suggestions) {
        $("assistantSuggestions").innerHTML = payload.suggestions.slice(0, 2).map(function (item) {
          return '<button data-prompt="' + escapeHtml(item) + '">' + escapeHtml(item) + "</button>";
        }).join("");
        bindPromptButtons($("assistantSuggestions"));
        $("assistantSuggestions").hidden = false;
      }
      sendTelemetry("assistant", { query: message, total: payload.total });
    } catch (error) {
      appendMessage("agent", "اتصال عامل قطع شد. می‌توانی همین نیاز را از نوار جست‌وجو دوباره امتحان کنی.");
    }
  }

  function toggleCompare(id) {
    if (state.selected.has(id)) state.selected.delete(id);
    else if (state.selected.size < 3) state.selected.add(id);
    else return;
    renderResults({ results: state.results }, state.query);
    updateCompareTray();
  }

  function updateCompareTray() {
    const tray = $("compareTray");
    tray.hidden = state.selected.size === 0;
    $("compareCount").textContent = fa(state.selected.size);
  }

  function showProduct(id) {
    const item = byId(id);
    if (!item) return;
    const offers = item.offers || [];
    const answer = "برای «" + item.title + "»، " + offers.length + " فروشنده در نتیجه‌ی فعلی دیده می‌شود. کمترین قیمت " +
      money(item.best_price) + " تومان است؛ قبل از مراجعه، زمان تغییر قیمت و آدرس را چک کن.";
    appendMessage("agent", answer, [
      { label: "خواندن آفرها" }, { label: "مقایسه‌ی قیمت" }, { label: "بررسی فاصله" }, { label: "تماس قبل از حرکت" }
    ]);
    sendTelemetry("open_product", { product_id: id });
  }

  function openCompare() {
    const selected = Array.from(state.selected).map(byId).filter(Boolean);
    if (!selected.length) return;
    $("compareHead").innerHTML = "<tr><th>معیار</th>" + selected.map(function (item) {
      return "<th>" + escapeHtml(item.title) + "</th>";
    }).join("") + "</tr>";
    const rows = [
      ["کمترین قیمت", (item) => money(item.best_price) + " تومان"],
      ["تعداد فروشنده", (item) => fa(item.shop_count) + " گزینه"],
      ["دسته‌بندی", (item) => item.category || "—"],
      ["دلیل پیشنهاد", (item) => (item.reasons || []).slice(0, 2).join("، ") || "—"],
      ["فروشنده‌ی اول", (item) => item.offers && item.offers[0] ? item.offers[0].shop_name : "—"],
      ["تازگی قیمت", (item) => item.offers && item.offers[0] ? item.offers[0].freshness.label : "نامشخص"]
    ];
    $("compareBody").innerHTML = rows.map(function (row) {
      return "<tr><td>" + escapeHtml(row[0]) + "</td>" + selected.map(function (item) {
        return "<td>" + escapeHtml(row[1](item)) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    $("compareModal").hidden = false;
  }

  function bindPromptButtons(scope) {
    scope.querySelectorAll("[data-prompt]").forEach(function (button) {
      button.addEventListener("click", function () {
        const prompt = button.dataset.prompt;
        $("searchInput").value = prompt;
        search(prompt, null);
        if (scope.id === "assistantSuggestions") askAgent(prompt);
      });
    });
  }

  async function loadMeta() {
    try {
      const meta = await (await fetch("/api/meta")).json();
      state.meta = meta;
      $("catalogStat").textContent = fa(meta.products) + " محصول · " + fa(meta.shops) + " فروشگاه";
      $("dataTrustText").textContent = fa(meta.offers) + " آفر قابل جست‌وجو";
      (meta.locations || []).forEach(function (location) {
        const option = document.createElement("option");
        option.value = location.name;
        option.textContent = location.name + " (" + fa(location.count) + ")";
        $("locationSelect").appendChild(option);
      });
    } catch (error) {
      $("catalogStat").textContent = "حالت نمونه";
      $("dataTrustText").textContent = "داده‌ی نمونه‌ی محلی";
    }
  }

  function sendTelemetry(type, data) {
    fetch("/api/telemetry", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: type, data: data }) }).catch(function () {});
  }

  $("searchForm").addEventListener("submit", function (event) { event.preventDefault(); search(); });
  $("assistantForm").addEventListener("submit", function (event) { event.preventDefault(); askAgent(); });
  $("radiusInput").addEventListener("input", function () { $("radiusValue").textContent = fa(this.value); });
  ["budgetInput", "locationSelect", "radiusInput", "sortSelect"].forEach(function (id) {
    $(id).addEventListener("change", function () { if (state.query) search(state.query); });
  });
  $("resetFilters").addEventListener("click", function () {
    $("budgetInput").value = ""; $("locationSelect").value = ""; $("radiusInput").value = 8; $("radiusValue").textContent = "۸"; $("sortSelect").value = "relevance";
    if (state.query) search(state.query);
  });
  $("clearCompare").addEventListener("click", function () { state.selected.clear(); updateCompareTray(); renderResults({ results: state.results }, state.query); });
  $("openCompare").addEventListener("click", openCompare);
  $("closeCompare").addEventListener("click", function () { $("compareModal").hidden = true; });
  $("compareModal").addEventListener("click", function (event) { if (event.target === $("compareModal")) $("compareModal").hidden = true; });
  $("openAbout").addEventListener("click", function () { $("aboutModal").hidden = false; });
  $("closeAbout").addEventListener("click", function () { $("aboutModal").hidden = true; });
  $("aboutModal").addEventListener("click", function (event) { if (event.target === $("aboutModal")) $("aboutModal").hidden = true; });
  $("clearChat").addEventListener("click", function () {
    $("conversation").innerHTML = '<div class="message agent-message"><div class="message-badge">TS</div><div><p>گفت‌وگو پاک شد. محصول یا محدوده‌ی بعدی را بگو.</p></div></div>';
    $("assistantSuggestions").hidden = false;
  });
  document.querySelectorAll(".view-toggle").forEach(function (button) {
    button.addEventListener("click", function () {
      state.view = button.dataset.view;
      document.querySelectorAll(".view-toggle").forEach((item) => item.classList.toggle("active", item === button));
      renderResults({ results: state.results }, state.query);
    });
  });
  bindPromptButtons(document);
  loadMeta();
})();
