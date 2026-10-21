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

  // "2026-10-13T09:47:14Z" -> "2026-10-13 12:47" in the viewer's local time.
  function formatDateTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  // Small outlined badge for a data format (json, csv, ...). Empty when unknown.
  function formatBadge(format) {
    if (!format) return "";
    return `<span class="badge badge-phoenix badge-phoenix-secondary fs-11 text-uppercase"><span class="badge-label">${escapeHtml(format)}</span></span>`;
  }

  function fileExtension(filename) {
    const i = (filename || "").lastIndexOf(".");
    return i > 0 ? filename.slice(i + 1).toLowerCase() : "";
  }

  // Joins the non-empty parts into one muted metadata line.
  function metaLine(parts) {
    return parts.filter(Boolean).map(escapeHtml).join(" &middot; ");
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
          ${e.data_description ? `<div class="fs-9 text-body-secondary">${escapeHtml(e.data_description)}</div>` : ""}
          <div class="fs-9 text-body-tertiary">${escapeHtml(e.file_name)} ${formatBadge(fileExtension(e.file_name))}</div>
        </td>
        <td>
          <div>${escapeHtml(e.offering_title)}</div>
          <div class="fs-9 text-body-tertiary">${metaLine([e.data_catalog_category_name, e.data_catalog_business_object_code, e.data_catalog_service_code])}</div>
        </td>
        <td>
          <div class="fw-semibold">${escapeHtml(e.provider_company_name)}</div>
          <div class="fs-9 text-body-tertiary">${escapeHtml(e.provider_username)}</div>
        </td>
        <td class="fs-9 text-body-tertiary">${escapeHtml(formatDateTime(e.created_on))}</td>
        <td class="pe-2 text-end">
          <a class="btn btn-phoenix-secondary btn-sm" href="${Api.downloadUrl(e.id, e.file_name)}" download="${escapeHtml(e.file_name)}">Download</a>
        </td>
      </tr>`
      )
      .join("");
    return entities;
  }

  // ---- Status tabs (All | Accepted | Rejected | Pending) ---------------

  const STATUS_TABS = [
    { key: "", label: "All" },
    { key: "accept", label: "Accepted" },
    { key: "reject", label: "Rejected" },
    { key: "pending", label: "Pending" },
  ];

  // The Middleware's status strings vary ("accept"/"accepted", "reject"/"rejected").
  function statusKey(status) {
    const s = (status || "").toLowerCase();
    if (s.startsWith("accept")) return "accept";
    if (s.startsWith("reject")) return "reject";
    return "pending";
  }

  function renderStatusTabs(containerId, rows, activeKey, onSelect) {
    const counts = { accept: 0, reject: 0, pending: 0 };
    rows.forEach((r) => counts[statusKey(r.status)]++);
    const container = document.getElementById(containerId);
    container.innerHTML = STATUS_TABS.map((t) => {
      const n = t.key ? counts[t.key] : rows.length;
      const active = activeKey === t.key ? "active" : "";
      return `<li class="nav-item"><a class="nav-link fs-9 ${active}" href="#" data-status="${t.key}">${t.label} <span class="text-body-tertiary fw-semibold">(${n})</span></a></li>`;
    }).join("");
    container.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        onSelect(a.dataset.status);
      });
    });
  }

  // ---- My Subscriptions ------------------------------------------------

  let mySubsRows = [];
  let mySubsStatus = "";

  function renderMySubscriptions() {
    renderStatusTabs("mySubsStatusTabs", mySubsRows, mySubsStatus, (key) => {
      mySubsStatus = key;
      renderMySubscriptions();
    });
    const shown = mySubsRows.filter((s) => !mySubsStatus || statusKey(s.status) === mySubsStatus);
    document.getElementById("mySubsCount").textContent = shown.length + " subscriptions";
    const badges = {
      accept: ["badge-phoenix-success", "Active"],
      reject: ["badge-phoenix-danger", "Rejected"],
      pending: ["badge-phoenix-warning", "Pending"],
    };
    document.getElementById("mySubsList").innerHTML = shown
      .map((s) => {
        const [badge, label] = badges[statusKey(s.status)];
        return `
        <div class="border rounded-3 p-3 d-flex justify-content-between align-items-center">
          <div>
            <div class="fw-semibold text-body-emphasis">${escapeHtml(s.title)} ${formatBadge(s.profile_selector)}</div>
            <div class="fs-9 text-body-tertiary">${metaLine([s.category_name && s.category_code ? s.category_name + " (" + s.category_code + ")" : s.category_name])}</div>
            <div class="fs-9 text-body-tertiary">${metaLine([s.provider_username && "Provider: " + s.provider_username, s.provider_email, s.created_at && "Requested " + formatDateTime(s.created_at)])}</div>
          </div>
          <span class="badge badge-phoenix ${badge} fs-11"><span class="badge-label">${label}</span></span>
        </div>`;
      })
      .join("");
  }

  async function loadMySubscriptions() {
    mySubsRows = await Api.getMySubscriptions();
    document.getElementById("statSubscriptions").textContent = mySubsRows.filter(
      (s) => statusKey(s.status) === "accept"
    ).length;
    renderMySubscriptions();
    return mySubsRows;
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
          <td class="ps-2">
            <div class="fw-semibold text-body-emphasis">${escapeHtml(item.title)} ${formatBadge(item.profile_selector)}</div>
            <div class="fs-9 text-body-tertiary">${metaLine([item.created_at && "Created " + formatDateTime(item.created_at)])}</div>
          </td>
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
            <div class="fs-9 text-body-tertiary">${formatBadge(o.profile_selector)} ${escapeHtml((o.cf_id || "").slice(0, 8))}&hellip;</div>
          </td>
          <td>${escapeHtml(parseCategoryTop(o))}</td>
          <td><span class="badge badge-phoenix ${badge} fs-11"><span class="badge-label">${escapeHtml(o.status)}</span></span></td>
          <td class="fs-9 text-body-tertiary">${escapeHtml(formatDateTime(o.created_at))}</td>
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

  // Prevent the browser's default "navigate to dropped file" behavior for a
  // drop that misses the dropzone - the dropzone's own handlers still run first.
  ["dragover", "drop"].forEach((evt) => {
    document.addEventListener(evt, (e) => e.preventDefault());
  });

  const DEFAULT_UPLOAD_FILE_LABEL = 'Drag &amp; drop a file here, or <span class="text-primary">browse</span>';
  const MAX_UPLOAD_FILE_SIZE = 50 * 1024 * 1024;

  function openUploadModal(offeringId, offeringTitle) {
    document.getElementById("uploadTargetId").value = offeringId;
    document.getElementById("uploadTargetTitle").textContent = offeringTitle;
    document.getElementById("uploadFileInput").value = "";
    document.getElementById("uploadFileLabel").innerHTML = DEFAULT_UPLOAD_FILE_LABEL;
    document.getElementById("uploadError").classList.add("d-none");
    bootstrap.Modal.getOrCreateInstance(document.getElementById("uploadDataModal")).show();
  }

  (function setUpUploadDropzone() {
    const dropzone = document.getElementById("uploadDropzone");
    const fileInput = document.getElementById("uploadFileInput");
    const fileLabel = document.getElementById("uploadFileLabel");
    if (!dropzone || !fileInput) return;

    function showSelectedFile(file) {
      fileLabel.textContent = file ? file.name : "";
      if (!file) fileLabel.innerHTML = DEFAULT_UPLOAD_FILE_LABEL;
    }

    fileInput.addEventListener("change", () => {
      showSelectedFile(fileInput.files && fileInput.files[0]);
    });

    // <label> doesn't natively activate its control on Enter/Space when
    // focused via tabindex, so wire that up for keyboard users.
    dropzone.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      fileInput.click();
    });

    ["dragenter", "dragover"].forEach((evt) => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.add("border-primary");
      });
    });
    ["dragleave", "drop"].forEach((evt) => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.remove("border-primary");
      });
    });
    dropzone.addEventListener("drop", (e) => {
      const files = e.dataTransfer && e.dataTransfer.files;
      if (!files || !files.length) return;
      fileInput.files = files;
      showSelectedFile(files[0]);
    });
  })();

  function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        const commaIdx = result.indexOf(",");
        resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
      };
      reader.onerror = () => reject(new Error("Could not read the selected file"));
      reader.readAsDataURL(file);
    });
  }

  document.getElementById("uploadSubmitBtn").addEventListener("click", async () => {
    const errorEl = document.getElementById("uploadError");
    errorEl.classList.add("d-none");
    const selectedFile = document.getElementById("uploadFileInput").files[0];
    if (!selectedFile) {
      errorEl.textContent = "Select a file to upload";
      errorEl.classList.remove("d-none");
      return;
    }
    if (selectedFile.size > MAX_UPLOAD_FILE_SIZE) {
      errorEl.textContent = "File is too large (max 50 MB)";
      errorEl.classList.remove("d-none");
      return;
    }
    try {
      const payload = {
        title: document.getElementById("uploadTitleInput").value.trim() || "Untitled upload",
        description: document.getElementById("uploadDescInput").value.trim() || null,
        filename: selectedFile.name,
        file: await readFileAsBase64(selectedFile),
        fileSize: String(selectedFile.size),
        data_offering_id: document.getElementById("uploadTargetId").value,
      };
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

  let requestRows = [];
  let requestStatus = "";

  function renderIncomingRequests() {
    renderStatusTabs("requestsStatusTabs", requestRows, requestStatus, (key) => {
      requestStatus = key;
      renderIncomingRequests();
    });
    const shown = requestRows.filter((r) => !requestStatus || statusKey(r.status) === requestStatus);
    document.getElementById("requestsCount").textContent = shown.length + " requests";
    const list = document.getElementById("requestsList");
    document.getElementById("requestsEmptyState").classList.toggle("d-none", shown.length !== 0);
    const badges = {
      accept: ["badge-phoenix-success", "Accepted"],
      reject: ["badge-phoenix-danger", "Rejected"],
    };
    list.innerHTML = shown
      .map((r) => {
        const key = statusKey(r.status);
        const right =
          key === "pending"
            ? `<div class="d-flex gap-2">
          <button class="btn btn-outline-danger btn-sm" data-respond="${escapeHtml(r.request_id)}" data-decision="reject">Reject</button>
          <button class="btn btn-primary btn-sm" data-respond="${escapeHtml(r.request_id)}" data-decision="accept">Accept</button>
        </div>`
            : `<span class="badge badge-phoenix ${badges[key][0]} fs-11"><span class="badge-label">${badges[key][1]}</span></span>`;
        return `
      <div class="border rounded-3 p-3 d-flex justify-content-between align-items-center mb-2" data-request-row="${escapeHtml(r.request_id)}">
        <div>
          <div class="fw-semibold text-body-emphasis">${escapeHtml(r.title)}</div>
          <div class="fs-9 text-body-tertiary">${metaLine([(r.category_path || []).join(" \u203a ")])}</div>
          <div class="fs-9 text-body-tertiary">${metaLine(["Requested by " + (r.requester_username || ""), r.requester_company, r.created_at && formatDateTime(r.created_at)])}</div>
        </div>
        ${right}
      </div>`;
      })
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
  }

  async function loadIncomingRequests() {
    requestRows = await Api.getIncomingRequests();
    renderIncomingRequests();
    return requestRows;
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
