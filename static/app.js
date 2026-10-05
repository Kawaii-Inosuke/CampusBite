// CampusBite: small vanilla JavaScript, no framework.
// Every feature here is an enhancement: without JavaScript the same pages
// still work through normal HTML forms.

(function () {
  "use strict";

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.content : "";

  // ---------------------------------------------------------------- helpers
  function icon(name) {
    return '<svg class="icon" width="20" height="20" aria-hidden="true" focusable="false">' +
           '<use href="#i-' + name + '"></use></svg>';
  }

  function esc(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var toastTimer;
  function toast(message, isError) {
    var el = document.getElementById("toast");
    if (!el) return;
    el.textContent = message;
    el.className = "toast" + (isError ? " toast-error" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 3500);
  }

  // Small confirm dialog (<dialog> element in base.html). Resolves true/false.
  function confirmDialog(message, okLabel) {
    var dlg = document.getElementById("confirm-dialog");
    if (!dlg || typeof dlg.showModal !== "function") {
      return Promise.resolve(window.confirm(message)); // very old browsers only
    }
    document.getElementById("confirm-message").textContent = message;
    document.getElementById("confirm-ok").textContent = okLabel || "OK";
    return new Promise(function (resolve) {
      dlg.returnValue = "";
      dlg.addEventListener("close", function done() {
        dlg.removeEventListener("close", done);
        resolve(dlg.returnValue === "ok");
      });
      dlg.showModal();
    });
  }

  // ---------------------------------------------------- generic confirm forms
  // Forms with data-confirm="..." (e.g. the owner's "Delete shop") ask first.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.dataset || !form.dataset.confirm || form.dataset.confirmed) return;
    e.preventDefault();
    confirmDialog(form.dataset.confirm, "Yes, continue").then(function (ok) {
      if (ok) { form.dataset.confirmed = "1"; form.submit(); }
    });
  });

  // Menu photos are optional: hide a thumbnail whose image fails to load.
  document.querySelectorAll("img[data-hide-on-error]").forEach(function (img) {
    img.addEventListener("error", function () { img.remove(); });
  });

  // ------------------------------------------------------------ cart steppers
  // The server is the source of truth. A tap updates the screen at once
  // (optimistic), then POSTs to /api/cart/set; the JSON answer contains the
  // cart as the server now has it (prices/totals from the DB) and the page is
  // re-drawn from that. If the server says no, the tap is rolled back.
  var cartApi = document.body.dataset.cartApi;
  var MAX_QTY = 10;
  var menuEl = document.getElementById("shop-menu");     // shop menu page
  var pageShopId = menuEl ? Number(menuEl.dataset.shopId) : null;
  var busy = {};                                          // item id -> request in flight

  function renderControl(control, qty) {
    var name = esc(control.dataset.itemName);
    control.dataset.qty = qty;
    if (qty <= 0) {
      control.innerHTML = '<button type="button" class="btn-add" data-set="1" aria-label="Add ' + name + '">Add ' +
                          icon("plus") + "</button>";
      return;
    }
    control.innerHTML =
      '<div class="stepper">' +
      '<button type="button" class="step-btn" data-set="' + (qty - 1) + '" aria-label="One less ' + name + '">' + icon("minus") + "</button>" +
      '<span class="step-qty" aria-live="polite">' + qty + "</span>" +
      '<button type="button" class="step-btn" data-set="' + (qty + 1) + '" aria-label="One more ' + name + '"' +
      (qty >= MAX_QTY ? " disabled" : "") + ">" + icon("plus") + "</button></div>";
  }

  function sendQty(itemId, qty, replace) {
    return fetch(cartApi, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ item_id: itemId, quantity: qty, replace_cart: replace ? 1 : 0 })
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    });
  }

  // Draw everything that depends on the cart from the server's answer.
  function applyCart(cart) {
    if (!cart) return;
    var count = cart.count, total = Number(cart.total);

    var pill = document.querySelector("[data-cart-count]");
    if (pill) { pill.textContent = count; pill.hidden = count === 0; }

    var bar = document.getElementById("cart-bar");
    if (bar) {
      bar.querySelector("[data-bar-count]").textContent = count;
      bar.querySelector("[data-bar-label]").textContent = count === 1 ? "item" : "items";
      bar.querySelector("[data-bar-total]").textContent = total.toFixed(2);
      bar.hidden = count === 0;
      document.body.classList.toggle("has-cart-bar", count > 0);
    }

    // Steppers: on a shop page, only this shop's cart counts.
    var sameShop = !menuEl || cart.shop_id === pageShopId;
    document.querySelectorAll(".qty-control").forEach(function (control) {
      var id = control.dataset.itemId;
      if (busy[id]) return;
      var qty = sameShop ? (cart.items[id] || 0) : 0;
      if (Number(control.dataset.qty) !== qty) renderControl(control, qty);
    });
    if (menuEl && (sameShop || count === 0)) {
      delete menuEl.dataset.otherShop;            // the cart now belongs to this shop
      var banner = document.querySelector("[data-other-shop-banner]");
      if (banner) banner.remove();
    }

    // Cart page: line subtotals, total, Place order button, empty state.
    var card = document.getElementById("cart-card");
    if (card) {
      card.querySelectorAll("[data-line-id]").forEach(function (li) {
        var line = cart.lines[li.dataset.lineId];
        if (!line) { li.remove(); return; }
        li.querySelector("[data-subtotal]").textContent = line.subtotal;
      });
      card.querySelector("[data-cart-total]").textContent = total.toFixed(2);
      var place = card.querySelector("[data-place-order]");
      if (place) place.disabled = !cart.can_order;
      var hint = card.querySelector("[data-remove-hint]");
      if (hint) hint.hidden = cart.can_order;
      if (count === 0) {
        card.remove();
        document.getElementById("cart-empty").hidden = false;
      }
    }
  }

  // Optimistic update of the counters before the server answers.
  function bumpCounters(deltaQty, price) {
    var pill = document.querySelector("[data-cart-count]");
    if (pill) {
      var n = Math.max(0, Number(pill.textContent) + deltaQty);
      pill.textContent = n; pill.hidden = n === 0;
    }
    var bar = document.getElementById("cart-bar");
    if (bar && (!menuEl || !menuEl.dataset.otherShop)) {
      var c = Math.max(0, Number(bar.querySelector("[data-bar-count]").textContent) + deltaQty);
      var t = Math.max(0, Number(bar.querySelector("[data-bar-total]").textContent) + deltaQty * price);
      bar.querySelector("[data-bar-count]").textContent = c;
      bar.querySelector("[data-bar-label]").textContent = c === 1 ? "item" : "items";
      bar.querySelector("[data-bar-total]").textContent = t.toFixed(2);
      bar.hidden = c === 0;
      document.body.classList.toggle("has-cart-bar", c > 0);
    }
  }

  function askToSwitch(fromShop) {
    var toShop = menuEl ? menuEl.dataset.shopName : "this shop";
    return confirmDialog("Your cart has items from " + fromShop + ". Clear it and start a new cart from " +
                         toShop + "?", "Clear and add");
  }

  function changeQty(control, itemId, qty, replace) {
    if (busy[itemId]) return;                      // no double submits
    qty = Math.max(0, Math.min(MAX_QTY, qty));

    // Adding the first item from a different shop: confirm before anything changes.
    if (control && !replace && menuEl && menuEl.dataset.otherShop && Number(control.dataset.qty) === 0) {
      askToSwitch(menuEl.dataset.otherShop).then(function (ok) {
        if (ok) changeQty(control, itemId, qty, true);
      });
      return;
    }

    var prev = control ? Number(control.dataset.qty) : 0;
    var price = control ? Number(control.dataset.price) || 0 : 0;
    var line = document.querySelector('[data-line-id="' + itemId + '"]');   // cart page row
    busy[itemId] = true;
    if (control) {
      control.classList.add("busy");
      renderControl(control, qty);                  // optimistic
      bumpCounters(qty - prev, price);
    }
    if (line && qty === 0) line.classList.add("removing");

    function rollBack() {
      if (control) renderControl(control, prev);
      if (line) line.classList.remove("removing");
    }

    sendQty(itemId, qty, replace).then(function (res) {
      busy[itemId] = false;
      if (control) control.classList.remove("busy");
      var data = res.data || {};
      if (data.ok) { applyCart(data.cart); return; }
      rollBack();
      if (data.cart) applyCart(data.cart); else bumpCounters(prev - qty, price);
      if (res.status === 409 && data.conflict) {    // cart is from another shop
        askToSwitch(data.cart_shop).then(function (ok) {
          if (ok) changeQty(control, itemId, qty, true);
        });
        return;
      }
      toast(data.error || "Could not update your cart.", true);
    }).catch(function () {
      busy[itemId] = false;
      if (control) control.classList.remove("busy");
      rollBack();
      bumpCounters(prev - qty, price);
      toast("Network problem. Please try again.", true);
    });
  }

  if (cartApi) {
    // Replace the no-JS forms with JS buttons.
    document.querySelectorAll(".qty-control").forEach(function (control) {
      renderControl(control, Number(control.dataset.qty));
    });
    var bar = document.getElementById("cart-bar");
    if (bar && !bar.hidden) document.body.classList.add("has-cart-bar");

    // Taps on Add / - / +
    document.addEventListener("click", function (e) {
      var btn = e.target.closest(".qty-control [data-set]");
      if (!btn || btn.disabled) return;
      var control = btn.closest(".qty-control");
      changeQty(control, control.dataset.itemId, Number(btn.dataset.set), false);
    });

    // Cart page "Remove" links (forms posting quantity 0).
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form.classList || !form.classList.contains("js-cart-form")) return;
      e.preventDefault();
      var itemId = form.elements.item_id.value;
      var control = document.querySelector('.qty-control[data-item-id="' + itemId + '"]');
      changeQty(control, itemId, Number(form.elements.quantity.value), false);
    });

    // Coming back with the browser's Back button: resync from the server.
    window.addEventListener("pageshow", function (e) {
      if (!e.persisted) return;
      fetch(cartApi.replace(/\/set$/, ""), { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (data) { if (data.ok) applyCart(data.cart); })
        .catch(function () {});
    });
  }

  // ---------------------------------- menu pages: expand/collapse and search
  (function () {
    var sections = Array.prototype.slice.call(document.querySelectorAll(".menu-section"));
    if (!sections.length) return;

    document.querySelectorAll("[data-expand]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var open = btn.dataset.expand === "all";
        sections.forEach(function (s) { s.open = open; });
      });
    });

    var search = document.getElementById("menu-search");
    var noResults = document.getElementById("no-results");
    if (!search) return;
    var initialOpen = sections.map(function (s) { return s.open; });

    // Only hides rows; the steppers inside them are never re-created.
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      var anyMatch = false;
      sections.forEach(function (section, i) {
        var matches = 0;
        section.querySelectorAll(".menu-row").forEach(function (row) {
          var hit = !q || row.dataset.name.indexOf(q) !== -1;
          row.hidden = !hit;
          if (hit) matches++;
        });
        section.hidden = q !== "" && matches === 0;
        section.open = q ? matches > 0 : initialOpen[i];
        if (matches) anyMatch = true;
      });
      if (noResults) noResults.hidden = !q || anyMatch;
    });
  })();

  // ------------------------- student order page: poll the status every 10 s
  (function () {
    var card = document.querySelector("[data-status-url]");
    if (!card) return;
    var badge = document.getElementById("status-badge");
    var steps = document.getElementById("status-steps");
    var note = document.getElementById("status-note");
    var order = ["Placed", "Preparing", "Ready"];
    var icons = { Placed: "clock", Preparing: "chef-hat", Ready: "circle-check" };

    function show(status) {
      badge.innerHTML = icon(icons[status] || "clock") + '<span class="badge-text">' + esc(status) + "</span>";
      badge.className = "badge badge-" + status.toLowerCase();
      var reached = order.indexOf(status);
      steps.querySelectorAll("li").forEach(function (li) {
        li.classList.toggle("done", order.indexOf(li.dataset.step) <= reached);
      });
      if (status === "Ready") note.textContent = "Your food is ready. Show this token at the counter.";
    }

    var timer;
    function poll() {
      fetch(card.dataset.statusUrl, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          show(data.status);
          if (data.status === "Ready") clearInterval(timer); // nothing more to wait for
        })
        .catch(function () { /* network blip: try again next tick */ });
    }

    show(steps.dataset.status);
    if (steps.dataset.status !== "Ready") timer = setInterval(poll, 10000);
  })();

  // ------------------- manager queue: reload periodically for new orders
  (function () {
    var el = document.querySelector("[data-autorefresh]");
    if (!el) return;
    var seconds = parseInt(el.dataset.autorefresh, 10) || 20;
    setInterval(function () {
      var a = document.activeElement;  // don't reload while the manager is typing
      if (!a || (a.tagName !== "INPUT" && a.tagName !== "SELECT")) location.reload();
    }, seconds * 1000);
  })();
})();
