(function () {
  "use strict";

  const Api = window.DataspaceApi;

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  function showToast(message, variant) {
    const container = document.getElementById("toast-container");
    const el = document.createElement("div");
    el.className = "toast align-items-center border-0 mb-2";
    el.setAttribute("role", "alert");
    const icon = variant === "error" ? "exclamation-circle text-danger" : "check-circle text-success";
    el.innerHTML =
      '<div class="d-flex"><div class="toast-body d-flex align-items-center gap-2">' +
      '<span class="fas fa-' + icon + '"></span><span>' + escapeHtml(message) + "</span></div>" +
      '<button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    container.appendChild(el);
    new bootstrap.Toast(el, { autohide: true, delay: 4000 }).show();
  }

  function parseCategoryTop(item) {
    if (item.category_path && item.category_path.length) return item.category_path[0];
    return "Other";
  }

  // ---- auth UI -------------------------------------------------------

  function setLoggedInUi(user) {
    document.getElementById("loggedOutNotice").classList.add("d-none");
    document.getElementById("dataspaceContent").classList.remove("d-none");
    document.getElementById("authStatusLoggedOut").classList.add("d-none");
    document.getElementById("authStatusLoggedIn").classList.remove("d-none");
    document.getElementById("signedInAs").classList.remove("d-none");
    document.getElementById("authUsername").textContent = user.username;
    document.getElementById("signedInAsUsername").textContent = user.username;
    document.getElementById("authUserEmail").textContent = user.email || "";
    document.getElementById("authUserInitial").textContent = (user.username || "?").charAt(0).toUpperCase();
  }

  function setLoggedOutUi() {
    document.getElementById("loggedOutNotice").classList.remove("d-none");
    document.getElementById("dataspaceContent").classList.add("d-none");
    document.getElementById("authStatusLoggedOut").classList.remove("d-none");
    document.getElementById("authStatusLoggedIn").classList.add("d-none");
    document.getElementById("signedInAs").classList.add("d-none");
  }

  async function doLogin() {
    const username = document.getElementById("loginUsername").value.trim();
    const password = document.getElementById("loginPassword").value;
    const errorEl = document.getElementById("loginError");
    errorEl.classList.add("d-none");
    try {
      const user = await Api.login(username, password);
      bootstrap.Modal.getOrCreateInstance(document.getElementById("loginModal")).hide();
      setLoggedInUi(user);
      showToast("Logged in as " + user.username);
      loadEverything();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove("d-none");
    }
  }

  function doLogout() {
    Api.logout();
    setLoggedOutUi();
    showToast("Logged out");
  }

  document.addEventListener("dataspace:session-expired", () => {
    setLoggedOutUi();
    showToast("Your session expired - please log in again.", "error");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("loginModal")).show();
  });

  // ---- My Data ---------------------------------------------------------

  async function loadMyData() {
    const entities = await Api.getConsumedData();
    document.getElementById("statEntities").textContent = entities.length;
    document.getElementById("myDataCount").textContent = entities.length + " files received";
    const body = document.getElementById("myDataBody");
    body.innerHTML = entities
      .map(
        (e) => `
      <tr>
        <td class="ps-2">
          <div class="fw-semibold text-body-emphasis">${escapeHtml(e.data_title)}</div>
          <div class="fs-9 text-body-tertiary">${escapeHtml(e.file_name)}</div>
        </td>
        <td>${escapeHtml(e.offering_title)}</td>
        <td>
          <div class="fw-semibold">${escapeHtml(e.provider_company_name)}</div>
          <div class="fs-9 text-body-tertiary">${escapeHtml(e.provider_username)}</div>
        </td>
        <td class="fs-9 text-body-tertiary">${escapeHtml((e.created_on || "").slice(0, 10))}</td>
        <td class="pe-2 text-end">
          <a class="btn btn-phoenix-secondary btn-sm" href="${Api.downloadUrl(e.id, e.file_name)}" download="${escapeHtml(e.file_name)}">Download</a>
        </td>
      </tr>`
      )
      .join("");
    return entities;
  }

  // ---- My Subscriptions ------------------------------------------------

  async function loadMySubscriptions() {
    const subs = await Api.getMySubscriptions();
    document.getElementById("statSubscriptions").textContent = subs.filter((s) => s.status === "accept").length;
    document.getElementById("mySubsCount").textContent = subs.length + " subscriptions";
    const list = document.getElementById("mySubsList");
    list.innerHTML = subs
      .map((s) => {
        const badge = s.status === "accept" ? "badge-phoenix-success" : "badge-phoenix-warning";
        const label = s.status === "accept" ? "Active" : s.status;
        return `
        <div class="border rounded-3 p-3 d-flex justify-content-between align-items-center">
          <div>
            <div class="fw-semibold text-body-emphasis">${escapeHtml(s.title)}</div>
            <div class="fs-9 text-body-tertiary">${escapeHtml(s.category_name)}</div>
          </div>
          <span class="badge badge-phoenix ${badge} fs-11"><span class="badge-label">${escapeHtml(label)}</span></span>
        </div>`;
      })
      .join("");
    return subs;
  }

  // ---- Browse Catalog ----------------------------------------------------

  let browseRows = [];

  function renderCategoryPills(items, activeCat) {
    const counts = {};
    items.forEach((i) => {
      const c = parseCategoryTop(i);
      counts[c] = (counts[c] || 0) + 1;
    });
    const pills = document.getElementById("browseCategoryPills");
    const allActive = !activeCat ? "active" : "";
    let html = `<li class="nav-item"><a class="nav-link fs-9 ${allActive}" href="#" data-cat="">All <span class="text-body-tertiary fw-semibold">(${items.length})</span></a></li>`;
    Object.keys(counts)
      .sort()
      .forEach((cat) => {
        const active = activeCat === cat ? "active" : "";
        html += `<li class="nav-item"><a class="nav-link fs-9 ${active}" href="#" data-cat="${escapeHtml(cat)}">${escapeHtml(cat)} <span class="text-body-tertiary fw-semibold">(${counts[cat]})</span></a></li>`;
      });
    pills.innerHTML = html;
    pills.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        applyBrowseFilter(a.dataset.cat, document.getElementById("browseSearchInput").value);
      });
    });
  }

  function applyBrowseFilter(activeCat, query) {
    renderCategoryPills(browseRows, activeCat);
    const q = (query || "").trim().toLowerCase();
    const body = document.getElementById("browseBody");
    const myUsername = (Api.getUser() || {}).username;
    const filtered = browseRows.filter((item) => {
      const matchesCat = !activeCat || parseCategoryTop(item) === activeCat;
      const haystack = (item.title + " " + item.category + " " + item.created_by_username).toLowerCase();
      return matchesCat && haystack.includes(q);
    });
    document.getElementById("browseEmptyHint").classList.toggle("d-none", filtered.length !== 0);
    body.innerHTML = filtered
      .map((item) => {
        const isMine = item.created_by_username === myUsername;
        const action = isMine
          ? '<span class="fs-9 text-body-tertiary fst-italic">Your offering</span>'
          : `<button class="btn btn-primary btn-sm" data-subscribe-id="${escapeHtml(item.cf_id)}">Subscribe</button>`;
        return `
        <tr>
          <td class="ps-2 fw-semibold text-body-emphasis">${escapeHtml(item.title)}</td>
          <td>${escapeHtml(parseCategoryTop(item))}</td>
          <td>
            <div class="fw-semibold">${escapeHtml(item.email)}</div>
            <div class="fs-9 text-body-tertiary">${escapeHtml(item.created_by_username)}</div>
          </td>
          <td class="pe-2 text-end">${action}</td>
        </tr>`;
      })
      .join("");

    body.querySelectorAll("[data-subscribe-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Subscribing...";
        try {
          await Api.subscribe(btn.dataset.subscribeId);
          btn.textContent = "Pending";
          btn.classList.remove("btn-primary");
          btn.classList.add("btn-phoenix-secondary");
          showToast("Subscription request sent");
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "Subscribe";
          showToast(err.message, "error");
        }
      });
    });
  }

  async function loadBrowseCatalog() {
    browseRows = await Api.getAvailableOfferings();
    document.getElementById("statCatalog").textContent = browseRows.length;
    const participants = new Set(browseRows.map((i) => i.created_by_username)).size;
    document.getElementById("statCatalogSub").textContent = "Across " + participants + " participants";
    applyBrowseFilter("", "");
    return browseRows;
  }

  document.getElementById("browseSearchInput").addEventListener("input", (e) => {
    const activeCat = document.querySelector("#browseCategoryPills a.active")?.dataset.cat || "";
    applyBrowseFilter(activeCat, e.target.value);
  });

  // ---- My Offerings --------------------------------------------------

  async function loadMyOfferings() {
    const offerings = await Api.getMyOfferings();
    document.getElementById("statOwned").textContent = offerings.length;
    document.getElementById("myOfferingsCount").textContent = offerings.length + " offerings owned";
    const body = document.getElementById("myOfferingsBody");
    body.innerHTML = offerings
      .map((o) => {
        const badge = o.status === "active" ? "badge-phoenix-success" : "badge-phoenix-secondary";
        return `
        <tr>
          <td class="ps-2">
            <div class="fw-semibold text-body-emphasis">${escapeHtml(o.title)}</div>
            <div class="fs-9 text-body-tertiary">${escapeHtml((o.cf_id || "").slice(0, 8))}&hellip;</div>
          </td>
          <td>${escapeHtml(parseCategoryTop(o))}</td>
          <td><span class="badge badge-phoenix ${badge} fs-11"><span class="badge-label">${escapeHtml(o.status)}</span></span></td>
          <td class="fs-9 text-body-tertiary">${escapeHtml((o.created_on || "").slice(0, 10))}</td>
          <td class="pe-2 text-end">
            <button class="btn btn-phoenix-secondary btn-sm" data-upload-for="${escapeHtml(o.cf_id)}" data-upload-title="${escapeHtml(o.title)}">Upload Data</button>
          </td>
        </tr>`;
      })
      .join("");

    body.querySelectorAll("[data-upload-for]").forEach((btn) => {
      btn.addEventListener("click", () => openUploadModal(btn.dataset.uploadFor, btn.dataset.uploadTitle));
    });
    return offerings;
  }

  function openUploadModal(offeringId, offeringTitle) {
    document.getElementById("uploadTargetId").value = offeringId;
    document.getElementById("uploadTargetTitle").textContent = offeringTitle;
    document.getElementById("uploadError").classList.add("d-none");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("uploadDataModal")).show();
  }

  document.getElementById("uploadSubmitBtn").addEventListener("click", async () => {
    const errorEl = document.getElementById("uploadError");
    errorEl.classList.add("d-none");
    const payload = {
      title: document.getElementById("uploadTitleInput").value.trim() || "Untitled upload",
      description: document.getElementById("uploadDescInput").value.trim() || null,
      filename: document.getElementById("uploadFilenameInput").value.trim() || "message.txt",
      file: document.getElementById("uploadContentInput").value,
      data_offering_id: document.getElementById("uploadTargetId").value,
    };
    try {
      await Api.provideData(payload);
      bootstrap.Modal.getOrCreateInstance(document.getElementById("uploadDataModal")).hide();
      showToast("Uploaded to " + document.getElementById("uploadTargetTitle").textContent);
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove("d-none");
    }
  });

  // ---- Create Offering -------------------------------------------------

  document.getElementById("createOfferingModal").addEventListener("show.bs.modal", async () => {
    const select = document.getElementById("offeringBoInput");
    select.innerHTML = '<option>Loading&hellip;</option>';
    try {
      const catalog = await Api.getCatalog();
      const byCategory = {};
      catalog.forEach((item) => {
        const cat = item.category_name || "Other";
        (byCategory[cat] = byCategory[cat] || []).push(item);
      });
      select.innerHTML = Object.keys(byCategory)
        .sort()
        .map((cat) => {
          const options = byCategory[cat]
            .map(
              (item) =>
                `<option value="${escapeHtml(item.cross_platform_service_id)}">${escapeHtml(item.business_object_name)} (${escapeHtml(item.business_object_code)})</option>`
            )
            .join("");
          return `<optgroup label="${escapeHtml(cat)}">${options}</optgroup>`;
        })
        .join("");
    } catch (err) {
      select.innerHTML = "";
      showToast("Couldn't load catalog: " + err.message, "error");
    }
  });

  document.getElementById("createOfferingSubmitBtn").addEventListener("click", async () => {
    const errorEl = document.getElementById("offeringError");
    errorEl.classList.add("d-none");
    const title = document.getElementById("offeringTitleInput").value.trim();
    const businessObjectId = document.getElementById("offeringBoInput").value;
    const profileSelector = document.getElementById("offeringProfileInput").value;
    if (!title || !businessObjectId) {
      errorEl.textContent = "Title and business object are required.";
      errorEl.classList.remove("d-none");
      return;
    }
    try {
      await Api.createOffering({
        title,
        data_catalog_business_object_id: businessObjectId,
        profile_selector: profileSelector,
      });
      bootstrap.Modal.getOrCreateInstance(document.getElementById("createOfferingModal")).hide();
      document.getElementById("offeringTitleInput").value = "";
      showToast("Offering created");
      loadMyOfferings();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.classList.remove("d-none");
    }
  });

  // ---- Incoming Requests -------------------------------------------------

  async function loadIncomingRequests() {
    const requests = await Api.getIncomingRequests();
    document.getElementById("requestsCount").textContent = requests.length + " pending requests";
    const list = document.getElementById("requestsList");
    const emptyState = document.getElementById("requestsEmptyState");
    emptyState.classList.toggle("d-none", requests.length !== 0);
    list.innerHTML = requests
      .map(
        (r) => `
      <div class="border rounded-3 p-3 d-flex justify-content-between align-items-center mb-2" data-request-row="${escapeHtml(r.request_id)}">
        <div>
          <div class="fw-semibold text-body-emphasis">${escapeHtml(r.title)}</div>
          <div class="fs-9 text-body-tertiary">Requested by ${escapeHtml(r.user_requesting)}</div>
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-outline-danger btn-sm" data-respond="${escapeHtml(r.request_id)}" data-decision="reject">Reject</button>
          <button class="btn btn-primary btn-sm" data-respond="${escapeHtml(r.request_id)}" data-decision="accept">Accept</button>
        </div>
      </div>`
      )
      .join("");

    list.querySelectorAll("[data-respond]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const requestId = btn.dataset.respond;
        const decision = btn.dataset.decision;
        list.querySelectorAll(`[data-respond="${requestId}"]`).forEach((b) => (b.disabled = true));
        try {
          await Api.respondToRequest(requestId, decision);
          showToast("Request " + decision + "ed");
          loadIncomingRequests();
        } catch (err) {
          showToast(err.message, "error");
          list.querySelectorAll(`[data-respond="${requestId}"]`).forEach((b) => (b.disabled = false));
        }
      });
    });
    return requests;
  }

  // ---- boot --------------------------------------------------------

  function loadEverything() {
    loadMyData().catch((e) => showToast(e.message, "error"));
    loadMySubscriptions().catch((e) => showToast(e.message, "error"));
    loadBrowseCatalog().catch((e) => showToast(e.message, "error"));
    loadMyOfferings().catch((e) => showToast(e.message, "error"));
    loadIncomingRequests().catch((e) => showToast(e.message, "error"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("loginSubmitBtn").addEventListener("click", doLogin);
    document.getElementById("loginPassword").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doLogin();
    });
    document.getElementById("logoutBtn").addEventListener("click", doLogout);

    const user = Api.getUser();
    if (user && Api.getToken()) {
      setLoggedInUi(user);
      loadEverything();
    } else {
      setLoggedOutUi();
    }
  });
})();
