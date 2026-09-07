/*
 * Thin client for the EnergyGuard Data Space FastAPI gateway.
 * Talks to it directly from the browser (CORS is enabled on the gateway) -
 * Django never proxies these calls, it only serves this page's shell.
 */
(function (global) {
  "use strict";

  const BASE_URL = global.DATASPACE_GATEWAY_URL;
  const TOKEN_KEY = "dataspace_token";
  const USER_KEY = "dataspace_user";

  function getToken() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function getUser() {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  }

  function setSession(token, user) {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  }

  class ApiError extends Error {
    constructor(status, body) {
      const detail = body && body.detail;
      const message =
        (detail && typeof detail === "object" && detail.message) ||
        (typeof detail === "string" ? detail : null) ||
        "Request failed";
      super(message);
      this.status = status;
      this.errorCode = detail && typeof detail === "object" ? detail.error_code : null;
      this.body = body;
    }
  }

  async function request(method, path, { json, params, auth = true } = {}) {
    const url = new URL(BASE_URL.replace(/\/$/, "") + path);
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null) url.searchParams.set(k, v);
      });
    }

    const headers = { Accept: "application/json" };
    if (json) headers["Content-Type"] = "application/json";
    if (auth) {
      const token = getToken();
      if (token) headers["Authorization"] = "Bearer " + token;
    }

    const resp = await fetch(url.toString(), {
      method,
      headers,
      body: json ? JSON.stringify(json) : undefined,
    });

    if (!resp.ok) {
      let body = null;
      try {
        body = await resp.json();
      } catch (e) {
        /* non-JSON error body */
      }
      const error = new ApiError(resp.status, body);
      if (error.errorCode === "token_expired" || error.errorCode === "invalid_token") {
        clearSession();
        document.dispatchEvent(new CustomEvent("dataspace:session-expired"));
      }
      throw error;
    }

    const contentType = resp.headers.get("content-type") || "";
    return contentType.includes("application/json") ? resp.json() : resp;
  }

  const Api = {
    getToken,
    getUser,
    clearSession,

    async login(username, password) {
      const data = await request("POST", "/auth/login", { json: { username, password }, auth: false });
      setSession(data.accessToken, data.user);
      return data.user;
    },

    logout() {
      clearSession();
    },

    getCatalog() {
      return request("GET", "/offerings/catalog");
    },
    getMyOfferings() {
      return request("GET", "/offerings/mine");
    },
    getAvailableOfferings() {
      return request("GET", "/offerings/available");
    },
    createOffering(payload) {
      return request("POST", "/offerings", { json: payload });
    },

    getMySubscriptions() {
      return request("GET", "/subscriptions/mine");
    },
    getIncomingRequests() {
      return request("GET", "/subscriptions/requests");
    },
    subscribe(dataOfferingId) {
      return request("POST", "/subscriptions", { json: { data_catalog_data_offering_id: dataOfferingId } });
    },
    respondToRequest(requestId, status) {
      return request("POST", `/subscriptions/requests/${requestId}/respond`, { json: { status } });
    },

    getConsumedData() {
      return request("GET", "/data/consumed");
    },
    downloadUrl(entityId, filename) {
      const url = new URL(BASE_URL.replace(/\/$/, "") + `/data/consumed/${entityId}`);
      url.searchParams.set("token", getToken());
      if (filename) url.searchParams.set("filename", filename);
      return url.toString();
    },
    provideData(payload) {
      return request("POST", "/data/provide", { json: payload });
    },
  };

  global.DataspaceApi = Api;
  global.DataspaceApiError = ApiError;
})(window);
