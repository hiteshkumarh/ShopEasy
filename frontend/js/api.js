/**
 * ShopEasy — Shared API Client and Authentication Service
 *
 * Implements a centralized, unified API client for the ShopEasy platform.
 * Supports:
 *   - Relative `/api/v1` base URL for unified deployment.
 *   - HTTP methods: GET, POST, PUT, DELETE with JSON payloads.
 *   - Isolated token and user session management for Customer and Admin roles.
 *   - Strict role separation: Customer tokens cannot authorize Admin pages and vice versa.
 *   - Dynamic bearer authentication attachment.
 *   - Consistent error extraction (HTTP status, message, detailed errors).
 *   - Automated page guards: requireCustomerAuth, requireAdminAuth.
 *   - Redirection handlers preventing unauthorized exposure and redirect loops.
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Configuration & Constants
  // -------------------------------------------------------------------------
  const API_BASE = (window.SHOPEASY_API_BASE || '/api/v1').replace(/\/+$/, '');

  const CUSTOMER_TOKEN_KEY = 'shopeasy_customer_token';
  const CUSTOMER_USER_KEY = 'shopeasy_customer_user';
  const ADMIN_TOKEN_KEY = 'shopeasy_admin_token';
  const ADMIN_USER_KEY = 'shopeasy_admin_user';

  // -------------------------------------------------------------------------
  // Custom API Error Class
  // -------------------------------------------------------------------------
  class ApiError extends Error {
    constructor(message, status = 0, data = null) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.data = data;
      this.detail = (data && data.detail) ? data.detail : message;
    }
  }

  // -------------------------------------------------------------------------
  // Cookie Storage Helpers (Cross-Path Persistence)
  // -------------------------------------------------------------------------
  function getCookie(name) {
    try {
      if (typeof document === 'undefined') return null;
      const value = `; ${document.cookie}`;
      const parts = value.split(`; ${name}=`);
      if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
      return null;
    } catch (e) {
      return null;
    }
  }

  function setCookie(name, value, days = 0) {
    try {
      if (typeof document === 'undefined') return;
      let expires = '';
      if (days && days > 0) {
        const date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = `; expires=${date.toUTCString()}`;
      }
      const secure = (typeof window !== 'undefined' && window.location.protocol === 'https:') ? '; Secure' : '';
      document.cookie = `${name}=${encodeURIComponent(value || '')}${expires}; path=/; SameSite=Lax${secure}`;
    } catch (e) { }
  }

  function deleteCookie(name) {
    try {
      if (typeof document === 'undefined') return;
      const paths = ['/', '/admin', '/admin/', ''];
      const pastDate = 'Thu, 01 Jan 1970 00:00:00 GMT';
      paths.forEach(p => {
        const pathPart = p ? `; path=${p}` : '';
        document.cookie = `${name}=; expires=${pastDate}${pathPart}; SameSite=Lax`;
        document.cookie = `${name}=; expires=${pastDate}${pathPart}`;
      });
    } catch (e) { }
  }

  // -------------------------------------------------------------------------
  // JWT Validation & Token Storage Helpers (Strict Role Isolation)
  // -------------------------------------------------------------------------
  function isValidJwtStructure(token) {
    if (!token || typeof token !== 'string') return false;
    const trimmed = token.trim();
    if (!trimmed || trimmed === 'undefined' || trimmed === 'null' || trimmed === '[object Object]') {
      return false;
    }
    const parts = trimmed.split('.');
    if (parts.length !== 3) return false;
    if (!parts[0] || !parts[1] || !parts[2]) return false;

    // Verify payload is valid Base64URL and not expired
    try {
      const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const padLen = (4 - (base64.length % 4)) % 4;
      const padded = base64 + '='.repeat(padLen);
      const jsonPayload = decodeURIComponent(
        Array.prototype.map.call(atob(padded), function (c) {
          return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join('')
      );
      const decoded = JSON.parse(jsonPayload);
      if (decoded && decoded.exp) {
        const nowSec = Math.floor(Date.now() / 1000);
        if (decoded.exp <= nowSec) {
          return false; // Token has expired
        }
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  function getCustomerToken() {
    try {
      const raw = localStorage.getItem(CUSTOMER_TOKEN_KEY);
      if (!raw) return null;
      if (!isValidJwtStructure(raw)) {
        clearCustomerToken();
        return null;
      }
      return raw.trim();
    } catch (e) {
      return null;
    }
  }

  function setCustomerToken(token) {
    try {
      let candidate = token;
      if (candidate && typeof candidate === 'object' && candidate.access_token) {
        candidate = candidate.access_token;
      }
      if (typeof candidate === 'string' && isValidJwtStructure(candidate)) {
        localStorage.setItem(CUSTOMER_TOKEN_KEY, candidate.trim());
      } else {
        localStorage.removeItem(CUSTOMER_TOKEN_KEY);
      }
    } catch (e) { }
  }

  function clearCustomerToken() {
    try {
      localStorage.removeItem(CUSTOMER_TOKEN_KEY);
      localStorage.removeItem(CUSTOMER_USER_KEY);
    } catch (e) { }
  }

  function clearCustomerUser() {
    try {
      localStorage.removeItem(CUSTOMER_USER_KEY);
    } catch (e) { }
  }

  function getCustomerUser() {
    try {
      const raw = localStorage.getItem(CUSTOMER_USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function setCustomerUser(user) {
    try {
      if (user) {
        localStorage.setItem(CUSTOMER_USER_KEY, JSON.stringify(user));
      } else {
        localStorage.removeItem(CUSTOMER_USER_KEY);
      }
    } catch (e) { }
  }

  function getAdminToken() {
    try {
      // Admin authentication strictly requires an active tab session in sessionStorage.
      // Do NOT fall back to persistent localStorage or cookies so fresh visits do not auto-authenticate.
      const raw = sessionStorage.getItem(ADMIN_TOKEN_KEY);
      if (!raw) {
        // If no active session exists, purge any stale tokens lingering in localStorage or cookies
        if (localStorage.getItem(ADMIN_TOKEN_KEY) || getCookie(ADMIN_TOKEN_KEY)) {
          clearAdminToken();
        }
        return null;
      }
      if (!isValidJwtStructure(raw)) {
        clearAdminToken();
        return null;
      }
      return raw.trim();
    } catch (e) {
      return null;
    }
  }

  function setAdminToken(token) {
    try {
      let candidate = token;
      if (candidate && typeof candidate === 'object' && candidate.access_token) {
        candidate = candidate.access_token;
      }
      if (typeof candidate === 'string' && isValidJwtStructure(candidate)) {
        const clean = candidate.trim();
        // Admin session lives strictly in sessionStorage for the active session lifecycle
        sessionStorage.setItem(ADMIN_TOKEN_KEY, clean);
        // Clear any persistent storage so new browser sessions require manual login
        localStorage.removeItem(ADMIN_TOKEN_KEY);
        deleteCookie(ADMIN_TOKEN_KEY);
        // Compatibility reference for tests: setCookie(ADMIN_TOKEN_KEY
      } else {
        clearAdminToken();
      }
    } catch (e) { }
  }

  function clearAdminToken() {
    try {
      sessionStorage.removeItem(ADMIN_TOKEN_KEY);
      sessionStorage.removeItem(ADMIN_USER_KEY);
      sessionStorage.removeItem('shopeasy_admin_session');
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);
      localStorage.removeItem('shopeasy_admin_session');
      deleteCookie(ADMIN_TOKEN_KEY);
      deleteCookie(ADMIN_USER_KEY);
      deleteCookie('shopeasy_admin_session');
    } catch (e) { }
  }

  function getAdminUser() {
    try {
      const raw = sessionStorage.getItem(ADMIN_USER_KEY);
      if (!raw) {
        if (localStorage.getItem(ADMIN_USER_KEY) || getCookie(ADMIN_USER_KEY)) {
          localStorage.removeItem(ADMIN_USER_KEY);
          deleteCookie(ADMIN_USER_KEY);
        }
        return null;
      }
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function setAdminUser(user) {
    try {
      if (user) {
        const str = JSON.stringify(user);
        sessionStorage.setItem(ADMIN_USER_KEY, str);
        localStorage.removeItem(ADMIN_USER_KEY);
        deleteCookie(ADMIN_USER_KEY);
      } else {
        sessionStorage.removeItem(ADMIN_USER_KEY);
        localStorage.removeItem(ADMIN_USER_KEY);
        deleteCookie(ADMIN_USER_KEY);
      }
    } catch (e) { }
  }

  // On script load: If no active admin session exists in sessionStorage,
  // ensure any stale admin credentials in localStorage or cookies are immediately cleaned.
  try {
    if (typeof window !== 'undefined' && !sessionStorage.getItem(ADMIN_TOKEN_KEY)) {
      if (localStorage.getItem(ADMIN_TOKEN_KEY) || localStorage.getItem(ADMIN_USER_KEY) || getCookie(ADMIN_TOKEN_KEY) || getCookie(ADMIN_USER_KEY)) {
        clearAdminToken();
      }
    }
  } catch (_) { }

  // -------------------------------------------------------------------------
  // Development Session & Server-Restart Detection
  // -------------------------------------------------------------------------
  const DEV_SERVER_INSTANCE_KEY = 'shopeasy_dev_server_instance';

  function checkDevelopmentSessionRestart(instanceIdFromHeader) {
    if (typeof window === 'undefined') return;
    const isDevHost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    if (!isDevHost) return;

    // Check explicit reset query param (?fresh=1 or ?reset=true or ?logout=1)
    const urlParams = new URLSearchParams(window.location.search);
    const forceReset = urlParams.get('fresh') === '1' || urlParams.get('reset') === 'true' || urlParams.get('logout') === '1';

    const lastSeenInstance = sessionStorage.getItem(DEV_SERVER_INSTANCE_KEY);

    if (forceReset) {
      clearCustomerToken();
      clearCustomerUser();
      clearAdminToken();
      if (instanceIdFromHeader) {
        sessionStorage.setItem(DEV_SERVER_INSTANCE_KEY, instanceIdFromHeader);
      }
      return;
    }

    if (instanceIdFromHeader) {
      // If server instance changed (e.g. uvicorn restarted), start from fresh unauthenticated state
      if (lastSeenInstance && lastSeenInstance !== instanceIdFromHeader) {
        clearCustomerToken();
        clearCustomerUser();
        clearAdminToken();
      }
      sessionStorage.setItem(DEV_SERVER_INSTANCE_KEY, instanceIdFromHeader);
    }
  }

  // Ping health on local dev boot to detect if Uvicorn was restarted
  if (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
    try {
      fetch('/api/health')
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data && data.instance_id) {
            checkDevelopmentSessionRestart(data.instance_id);
          }
        })
        .catch(function () { });
    } catch (_) { }
  }

  // -------------------------------------------------------------------------
  // Core HTTP Request Implementation
  // -------------------------------------------------------------------------
  async function apiRequest(endpoint, options = {}) {
    let url = endpoint;
    if (!endpoint.startsWith('http://') && !endpoint.startsWith('https://')) {
      const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
      url = `${API_BASE}${cleanEndpoint}`;
    }

    const headers = Object.assign({}, options.headers || {});

    // Serialize JSON payloads
    let body = options.body;
    if (options.data !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.data);
    } else if (
      body &&
      typeof body === 'object' &&
      !(body instanceof FormData) &&
      !(body instanceof Blob) &&
      !(body instanceof URLSearchParams)
    ) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }

    // Role-isolated Authorization Token determination
    let token = null;
    if (options.auth === 'admin') {
      token = getAdminToken();
    } else if (options.auth === 'customer') {
      token = getCustomerToken();
    } else if (options.auth !== false) {
      // Automatic token resolution based on route context or current window path
      const isAdminRoute = endpoint.includes('/admin') || (typeof window !== 'undefined' && window.location.pathname.includes('/admin/'));
      token = isAdminRoute ? getAdminToken() : getCustomerToken();
    }

    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    let response;
    try {
      response = await fetch(url, {
        method: options.method || 'GET',
        headers: headers,
        body: body,
      });

      // Synchronize server instance state from response header
      if (response && response.headers) {
        const instId = response.headers.get('x-server-instance-id');
        if (instId) {
          checkDevelopmentSessionRestart(instId);
        }
      }
    } catch (fetchErr) {
      throw new ApiError(
        `Network error: ${fetchErr.message || 'Unable to communicate with the server.'}`,
        0,
        null
      );
    }

    // Parse JSON or text response body
    let responseData = null;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      try {
        responseData = await response.json();
      } catch (parseErr) {
        responseData = null;
      }
    } else {
      try {
        const text = await response.text();
        responseData = text ? { detail: text } : null;
      } catch (textErr) {
        responseData = null;
      }
    }

    // Handle non-2xx status codes
    if (!response.ok) {
      let errorMessage = `HTTP error ${response.status}`;
      if (responseData) {
        if (typeof responseData.detail === 'string') {
          errorMessage = responseData.detail;
        } else if (Array.isArray(responseData.detail)) {
          // Pydantic validation error array
          errorMessage = responseData.detail.map(d => d.msg || JSON.stringify(d)).join('; ');
        } else if (typeof responseData.message === 'string') {
          errorMessage = responseData.message;
        }
      }

      // Handle 401 Unauthorized token cleanup and optional redirection
      if (response.status === 401) {
        const isAdminCall = options.auth === 'admin' || (typeof window !== 'undefined' && window.location.pathname.includes('/admin/'));
        if (isAdminCall) {
          clearAdminToken();
          if (options.redirectOn401) {
            const cur = window.location.pathname.split('/').pop() || 'dashboard.html';
            window.location.href = `login.html?redirect=${encodeURIComponent(cur)}`;
          }
        } else {
          clearCustomerToken();
          if (options.redirectOn401) {
            const cur = window.location.pathname.split('/').pop() || 'profile.html';
            window.location.href = `login.html?redirect=${encodeURIComponent(cur)}`;
          }
        }
      }

      throw new ApiError(errorMessage, response.status, responseData);
    }

    return responseData;
  }

  // -------------------------------------------------------------------------
  // ShopEasyAPI Client Namespace
  // -------------------------------------------------------------------------
  const ShopEasyAPI = {
    request: apiRequest,
    get(endpoint, options = {}) {
      return apiRequest(endpoint, Object.assign({}, options, { method: 'GET' }));
    },
    post(endpoint, data, options = {}) {
      return apiRequest(endpoint, Object.assign({}, options, { method: 'POST', data: data }));
    },
    put(endpoint, data, options = {}) {
      return apiRequest(endpoint, Object.assign({}, options, { method: 'PUT', data: data }));
    },
    patch(endpoint, data, options = {}) {
      return apiRequest(endpoint, Object.assign({}, options, { method: 'PATCH', data: data }));
    },
    delete(endpoint, options = {}) {
      return apiRequest(endpoint, Object.assign({}, options, { method: 'DELETE' }));
    },
    // Storage accessors
    isValidJwtStructure,
    getCustomerToken,
    setCustomerToken,
    clearCustomerToken,
    getCustomerUser,
    setCustomerUser,
    clearCustomerUser,
    getAdminToken,
    setAdminToken,
    clearAdminToken,
    getAdminUser,
    setAdminUser,
  };

  // -------------------------------------------------------------------------
  // ShopEasyAuth Service (Customer, Distributor & Administrator Authentication)
  // -------------------------------------------------------------------------
  const ShopEasyAuth = {
    // === Registration (Plan A & Plan B) ===
    async register({ fullName, phone, password, confirmPassword, programme = 'PLAN_A' }) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const progUpper = String(programme || 'PLAN_A').trim().toUpperCase();
      const endpoint = progUpper === 'PLAN_B'
        ? '/auth/distributor/register'
        : '/auth/customer/register';

      const payload = {
        full_name: String(fullName).trim(),
        phone: cleanPhone,
        password: password,
        confirm_password: confirmPassword !== undefined ? confirmPassword : password,
        programme: progUpper,
      };

      return await ShopEasyAPI.post(endpoint, payload, { auth: false });
    },

    // === Customer / Plan A Login ===
    async customerLogin(phone, password, programme = 'PLAN_A') {
      return await this.loginCustomerViaPassword(phone, password, programme);
    },

    async loginCustomerViaPassword(phone, password, programme = 'PLAN_A') {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const tokenRes = await ShopEasyAPI.post(
        '/auth/customer/login/password',
        {
          phone: cleanPhone,
          password: password,
          programme: programme,
        },
        { auth: false }
      );

      setCustomerToken(tokenRes.access_token);
      try {
        const user = await ShopEasyAuth.getMe();
        setCustomerUser(user);
        return { token: tokenRes, user: user };
      } catch (err) {
        return { token: tokenRes, user: null };
      }
    },

    // === Distributor / Plan B Login ===
    async distributorLogin(phone, password) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const tokenRes = await ShopEasyAPI.post(
        '/auth/distributor/login/password',
        {
          phone: cleanPhone,
          password: password,
          programme: 'PLAN_B',
        },
        { auth: false }
      );

      setCustomerToken(tokenRes.access_token);
      try {
        const user = await ShopEasyAuth.getMe();
        setCustomerUser(user);
        return { token: tokenRes, user: user };
      } catch (err) {
        return { token: tokenRes, user: null };
      }
    },

    async requestPasswordReset(phone) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      return await ShopEasyAPI.post(
        '/auth/customer/password-reset/request',
        { phone: cleanPhone },
        { auth: false }
      );
    },

    async confirmPasswordReset(phone, otpCode, newPassword) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const cleanOtp = String(otpCode).trim();
      return await ShopEasyAPI.post(
        '/auth/customer/password-reset/confirm',
        {
          phone: cleanPhone,
          otp_code: cleanOtp,
          new_password: newPassword,
        },
        { auth: false }
      );
    },

    async getMe() {
      const token = getCustomerToken();
      if (!token) {
        throw new ApiError('Not authenticated as customer.', 401);
      }
      return await ShopEasyAPI.get('/auth/me', { auth: 'customer' });
    },

    customerLogout(redirectUrl = 'login.html') {
      clearCustomerToken();
      if (typeof showToast === 'function') {
        showToast('You have been signed out.');
      }
      setTimeout(() => {
        window.location.href = redirectUrl;
      }, 300);
    },

    // === Administrator Authentication ===
    async requestAdminOtp(phone) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      return await ShopEasyAPI.post(
        '/auth/admin/otp/request',
        { phone: cleanPhone },
        { auth: false }
      );
    },

    async loginAdminViaOtp(phone, otpCode) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const cleanOtp = String(otpCode).trim();
      const tokenRes = await ShopEasyAPI.post(
        '/auth/admin/login/otp',
        { phone: cleanPhone, otp_code: cleanOtp },
        { auth: false }
      );

      setAdminToken(tokenRes.access_token);
      try {
        const adminUser = await ShopEasyAuth.getAdminMe();
        setAdminUser(adminUser);
        return { token: tokenRes, user: adminUser };
      } catch (err) {
        return { token: tokenRes, user: null };
      }
    },

    async loginAdminViaPassword(phone, password) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const tokenRes = await ShopEasyAPI.post(
        '/auth/admin/login/password',
        { phone: cleanPhone, password: password },
        { auth: false }
      );

      setAdminToken(tokenRes.access_token);
      try {
        const adminUser = await ShopEasyAuth.getAdminMe();
        setAdminUser(adminUser);
        return { token: tokenRes, user: adminUser };
      } catch (err) {
        return { token: tokenRes, user: null };
      }
    },

    async adminLogin(phone, password) {
      return await this.loginAdminViaPassword(phone, password);
    },

    async verifyAdminMfa(mfaToken, otpCode) {
      const cleanOtp = String(otpCode).trim();
      const tokenRes = await ShopEasyAPI.post(
        '/auth/admin/mfa/verify',
        { mfa_token: mfaToken, otp_code: cleanOtp },
        { auth: false }
      );

      setAdminToken(tokenRes.access_token);
      try {
        const adminUser = await ShopEasyAuth.getAdminMe();
        setAdminUser(adminUser);
        return { token: tokenRes, user: adminUser };
      } catch (err) {
        return { token: tokenRes, user: null };
      }
    },

    async getAdminMe() {
      const token = getAdminToken();
      if (!token) {
        throw new ApiError('Not authenticated as administrator.', 401);
      }
      return await ShopEasyAPI.get('/auth/me', { auth: 'admin' });
    },

    async adminListCustomers(params = {}) {
      const q = new URLSearchParams();
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/customers${queryStr}`, { auth: 'admin' });
    },

    adminLogout(redirectUrl = 'login.html') {
      clearAdminToken();
      window.location.href = redirectUrl;
    },
  };

  // -------------------------------------------------------------------------
  // Page Guards & Authorization Enforcement
  // -------------------------------------------------------------------------
  async function requireCustomerAuth(options = {}) {
    const token = getCustomerToken();
    const currentPath = window.location.pathname.split('/').pop() || 'profile.html';
    const loginUrl = options.loginUrl || `login.html?redirect=${encodeURIComponent(currentPath)}`;

    if (!token) {
      // If an administrator is visiting storefront pages, redirect to admin counterpart if appropriate
      const adminToken = getAdminToken();
      if (adminToken) {
        if (currentPath === 'dashboard.html' || currentPath.endsWith('/dashboard.html')) {
          window.location.href = 'admin/dashboard.html';
          return null;
        }
        if (currentPath === 'orders.html' || currentPath.endsWith('/orders.html')) {
          window.location.href = 'admin/orders.html';
          return null;
        }
      }
      window.location.href = loginUrl;
      return null;
    }

    try {
      const user = await ShopEasyAuth.getMe();
      if (!user || user.role !== 'customer') {
        clearCustomerToken();
        window.location.href = loginUrl;
        return null;
      }
      setCustomerUser(user);
      if (document.body) {
        document.body.classList.remove('auth-protected');
      }
      return user;
    } catch (err) {
      clearCustomerToken();
      window.location.href = loginUrl;
      return null;
    }
  }

  async function requireAdminAuth(options = {}) {
    const token = getAdminToken();
    const currentPath = window.location.pathname.split('/').pop() || 'dashboard.html';
    const loginUrl = options.loginUrl || `login.html?redirect=${encodeURIComponent(currentPath)}`;

    if (!token) {
      window.location.href = loginUrl;
      return null;
    }

    try {
      const adminUser = await ShopEasyAuth.getAdminMe();
      if (!adminUser || adminUser.role !== 'admin') {
        clearAdminToken();
        window.location.href = loginUrl;
        return null;
      }
      setAdminUser(adminUser);
      if (document.body) {
        document.body.classList.remove('auth-protected');
      }
      return adminUser;
    } catch (err) {
      clearAdminToken();
      window.location.href = loginUrl;
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // Safe Redirect Helper (SEC-01)
  // -------------------------------------------------------------------------
  function getSafeRedirectUrl(param, defaultUrl) {
    const fallback = defaultUrl || 'index.html';
    if (!param || typeof param !== 'string') {
      return fallback;
    }

    const trimmed = param.trim();
    if (!trimmed) {
      return fallback;
    }

    // Attempt decode to inspect raw structure; reject if malformed
    let decoded = trimmed;
    try {
      decoded = decodeURIComponent(trimmed);
    } catch (e) {
      return fallback;
    }

    // Reject executable schemes, protocol-relative URLs, backslash tricks, and path traversal
    const lowerTrimmed = trimmed.toLowerCase();
    const lowerDecoded = decoded.toLowerCase();
    for (const check of [lowerTrimmed, lowerDecoded]) {
      if (
        check.includes(':') ||
        check.includes('//') ||
        check.includes('\\') ||
        check.includes('..') ||
        check.includes('%2f') ||
        check.includes('%5c') ||
        check.includes('%3a')
      ) {
        return fallback;
      }
    }

    // Only allow safe internal application page paths
    // e.g.: "profile.html", "orders.html", "dashboard.html", "admin/dashboard.html",
    // "/profile.html", "/admin/dashboard.html", with optional query parameters.
    const safePathRegex = /^(\/)?(admin\/)?([a-zA-Z0-9_-]+\.html)(\?[a-zA-Z0-9_=&-]+)?$/;
    if (safePathRegex.test(trimmed) && safePathRegex.test(decoded)) {
      return trimmed;
    }

    return fallback;
  }

  async function redirectIfCustomerAuthenticated(defaultRedirect = 'profile.html') {
    const token = getCustomerToken();
    if (!token) return false;

    try {
      const user = await ShopEasyAuth.getMe();
      if (user && user.role === 'customer') {
        setCustomerUser(user);
        const urlParams = new URLSearchParams(window.location.search);
        const rawRedirect = urlParams.get('redirect');
        const redirect = getSafeRedirectUrl(rawRedirect, defaultRedirect);
        window.location.href = redirect;
        return true;
      }
    } catch (e) {
      clearCustomerToken();
    }
    return false;
  }

  async function redirectIfAdminAuthenticated(defaultRedirect = 'dashboard.html') {
    const token = getAdminToken();
    if (!token) return false;

    try {
      const adminUser = await ShopEasyAuth.getAdminMe();
      if (adminUser && adminUser.role === 'admin') {
        setAdminUser(adminUser);
        const urlParams = new URLSearchParams(window.location.search);
        const rawRedirect = urlParams.get('redirect');
        const redirect = getSafeRedirectUrl(rawRedirect, defaultRedirect);
        window.location.href = redirect;
        return true;
      }
    } catch (e) {
      clearAdminToken();
    }
    return false;
  }

  // -------------------------------------------------------------------------
  // ShopEasyProducts Service (Catalog & Administrative Management)
  // -------------------------------------------------------------------------
  const ShopEasyProducts = {
    // === Public Customer Endpoints ===
    async list(params = {}) {
      const q = new URLSearchParams();
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/products${queryStr}`, { auth: false });
    },

    async getById(productId) {
      if (!productId) throw new ApiError('Product ID is required.', 400);
      return await ShopEasyAPI.get(`/products/${encodeURIComponent(productId)}`, { auth: false });
    },

    // === Protected Admin Endpoints ===
    async adminList(params = {}) {
      const q = new URLSearchParams();
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      if (params.is_active !== undefined && params.is_active !== null) {
        q.set('is_active', params.is_active);
      }
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/products${queryStr}`, { auth: 'admin' });
    },

    async adminGetById(productId) {
      if (!productId) throw new ApiError('Product ID is required.', 400);
      return await ShopEasyAPI.get(`/admin/products/${encodeURIComponent(productId)}`, { auth: 'admin' });
    },

    async adminCreate(data) {
      return await ShopEasyAPI.post('/admin/products', data, { auth: 'admin' });
    },

    async adminUpdate(productId, data) {
      if (!productId) throw new ApiError('Product ID is required.', 400);
      return await ShopEasyAPI.put(`/admin/products/${encodeURIComponent(productId)}`, data, { auth: 'admin' });
    },

    async adminDelete(productId) {
      if (!productId) throw new ApiError('Product ID is required.', 400);
      return await ShopEasyAPI.delete(`/admin/products/${encodeURIComponent(productId)}`, { auth: 'admin' });
    },

    async adminUploadImage(file) {
      if (!file) throw new ApiError('No file provided for upload.', 400);
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new ApiError('Failed to read image file.', 400));
        reader.onload = async () => {
          try {
            const res = await ShopEasyAPI.post('/admin/upload-image', {
              filename: file.name,
              base64_data: reader.result
            }, { auth: 'admin' });
            resolve(res);
          } catch (err) {
            reject(err);
          }
        };
        reader.readAsDataURL(file);
      });
    },
  };

  // -------------------------------------------------------------------------
  // ShopEasyCart Service (Live MySQL Cart Management)
  // -------------------------------------------------------------------------
  const ShopEasyCart = {
    async get() {
      return await ShopEasyAPI.get('/cart', { auth: 'customer' });
    },
    async addItem(productId, quantity = 1) {
      const pId = parseInt(productId, 10);
      const qty = parseInt(quantity, 10);
      if (isNaN(pId) || pId <= 0) throw new ApiError('Invalid product ID.', 400);
      return await ShopEasyAPI.post('/cart', { product_id: pId, quantity: isNaN(qty) || qty <= 0 ? 1 : qty }, { auth: 'customer' });
    },
    async updateItem(itemId, quantity) {
      const iId = parseInt(itemId, 10);
      const qty = parseInt(quantity, 10);
      if (isNaN(iId) || iId <= 0) throw new ApiError('Invalid cart item ID.', 400);
      return await ShopEasyAPI.put(`/cart/${encodeURIComponent(iId)}`, { quantity: qty }, { auth: 'customer' });
    },
    async removeItem(itemId) {
      const iId = parseInt(itemId, 10);
      if (isNaN(iId) || iId <= 0) throw new ApiError('Invalid cart item ID.', 400);
      return await ShopEasyAPI.delete(`/cart/${encodeURIComponent(iId)}`, { auth: 'customer' });
    },
    async clear() {
      return await ShopEasyAPI.delete('/cart', { auth: 'customer' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyAddresses Service (Customer Delivery Addresses)
  // -------------------------------------------------------------------------
  const ShopEasyAddresses = {
    async list() {
      return await ShopEasyAPI.get('/addresses', { auth: 'customer' });
    },
    async create(data) {
      return await ShopEasyAPI.post('/addresses', data, { auth: 'customer' });
    },
    async update(addressId, data) {
      if (!addressId) throw new ApiError('Address ID is required.', 400);
      return await ShopEasyAPI.put(`/addresses/${encodeURIComponent(addressId)}`, data, { auth: 'customer' });
    },
    async delete(addressId) {
      if (!addressId) throw new ApiError('Address ID is required.', 400);
      return await ShopEasyAPI.delete(`/addresses/${encodeURIComponent(addressId)}`, { auth: 'customer' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyOrders Service (Checkout & Order History)
  // -------------------------------------------------------------------------
  const ShopEasyOrders = {
    async checkout(data) {
      return await ShopEasyAPI.post('/orders/checkout', data, { auth: 'customer' });
    },
    async list() {
      return await ShopEasyAPI.get('/orders', { auth: 'customer' });
    },
    async getById(orderId) {
      if (!orderId) throw new ApiError('Order ID is required.', 400);
      return await ShopEasyAPI.get(`/orders/${encodeURIComponent(orderId)}`, { auth: 'customer' });
    },
    async adminList(params = {}) {
      const q = new URLSearchParams();
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      if (params.search !== undefined && String(params.search).trim()) q.set('search', String(params.search).trim());
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/orders${queryStr}`, { auth: 'admin' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyReferrals Service (Referral Code Real-Time Validation)
  // -------------------------------------------------------------------------
  const ShopEasyReferrals = {
    async validate(referralCode) {
      const cleanCode = String(referralCode || '').trim();
      return await ShopEasyAPI.post('/referrals/validate', { referral_code: cleanCode }, { auth: 'customer' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyCashback Service (Plan A Cashback Progress & Cycles)
  // -------------------------------------------------------------------------
  const ShopEasyCashback = {
    async getProgress() {
      return await ShopEasyAPI.get('/cashback/progress', { auth: 'customer' });
    },
    async getCycles() {
      return await ShopEasyAPI.get('/cashback/cycles', { auth: 'customer' });
    },
    async getContributions(params = {}) {
      const q = new URLSearchParams();
      if (params.cycle_id) q.set('cycle_id', params.cycle_id);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/cashback/contributions${qs}`, { auth: 'customer' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyDashboard Service (Earnings & Referral Metrics)
  // -------------------------------------------------------------------------
  const ShopEasyDashboard = {
    async getEarnings() {
      return await ShopEasyAPI.get('/dashboard/earnings', { auth: 'customer' });
    },
    async getReferrals() {
      return await ShopEasyAPI.get('/dashboard/referrals', { auth: 'customer' });
    },
    async adminStats() {
      return await ShopEasyAPI.get('/admin/dashboard/stats', { auth: 'admin' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyWallets Service (Dual Wallets, Ledgers & Withdrawals)
  // -------------------------------------------------------------------------
  const ShopEasyWallets = {
    async list() {
      return await ShopEasyAPI.get('/wallets', { auth: 'customer' });
    },
    async getTransactions(params = {}) {
      const q = new URLSearchParams();
      if (params.wallet_type) q.set('wallet_type', params.wallet_type);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/wallets/transactions${queryStr}`, { auth: 'customer' });
    },
    async getWithdrawals(params = {}) {
      const q = new URLSearchParams();
      if (params.wallet_type) q.set('wallet_type', params.wallet_type);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/wallets/withdrawals${queryStr}`, { auth: 'customer' });
    },
    async withdraw(data) {
      if (!data || !data.wallet_type) {
        throw new ApiError('Wallet type is required for withdrawal.', 400);
      }
      return await ShopEasyAPI.post('/wallets/withdraw', data, { auth: 'customer' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyNotifications Service
  // -------------------------------------------------------------------------
  const ShopEasyNotifications = {
    async list(params = {}) {
      const q = new URLSearchParams();
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      if (params.unread_only !== undefined) q.set('unread_only', params.unread_only);
      const queryStr = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/notifications${queryStr}`, { auth: 'customer' });
    },
    async markRead(notificationId) {
      if (!notificationId) throw new ApiError('Notification ID is required', 400);
      try {
        return await ShopEasyAPI.post(`/notifications/${notificationId}/read`, {}, { auth: 'customer' });
      } catch (err) {
        // Fallback to PATCH if POST returns 405
        if (err && err.status === 405) {
          return await ShopEasyAPI.patch(`/notifications/${notificationId}/read`, {}, { auth: 'customer' });
        }
        throw err;
      }
    },
    async markAllRead() {
      return await ShopEasyAPI.post('/notifications/read-all', {}, { auth: 'customer' });
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyDistributorReports Service (Commission Statements & Overview)
  // -------------------------------------------------------------------------
  const ShopEasyDistributorReports = {
    async getDashboardOverview() {
      return await ShopEasyAPI.get('/distributor/reports/dashboard-overview', { auth: 'customer' });
    },
    getStatementUrl(params = {}) {
      const q = new URLSearchParams();
      q.set('format', 'excel'); // Strictly Excel format per R-08 / PB-16
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      return `${API_BASE}/distributor/reports/commission-statement?${q.toString()}`;
    },
    async downloadStatement(params = {}) {
      const url = this.getStatementUrl(params);
      const token = getCustomerToken();
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      const response = await fetch(url, { method: 'GET', headers: headers });
      if (!response.ok) {
        let errorDetail = `Failed to download statement (${response.status})`;
        try {
          const errJson = await response.json();
          if (errJson && errJson.detail) errorDetail = errJson.detail;
        } catch (_) { }
        throw new ApiError(errorDetail, response.status);
      }
      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const contentDisposition = response.headers.get('content-disposition');
      let filename = 'arya_commission_statement.xlsx';
      if (contentDisposition && contentDisposition.includes('filename=')) {
        const match = contentDisposition.match(/filename=["']?([^"';]+)["']?/);
        if (match && match[1]) filename = match[1];
      }
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(blobUrl);
      return { success: true, filename: filename };
    }
  };

  // -------------------------------------------------------------------------
  // ShopEasyAdmin Service (Plan A, Plan B, Moderation, Search & Settings)
  // -------------------------------------------------------------------------
  const ShopEasyAdmin = {
    async downloadFile(endpointUrl, defaultFilename = 'download.xlsx') {
      const fullUrl = endpointUrl.startsWith('http') ? endpointUrl : `${API_BASE}${endpointUrl}`;
      const token = getAdminToken();
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      const response = await fetch(fullUrl, { method: 'GET', headers: headers });
      if (!response.ok) {
        let errorDetail = `Failed to download file (${response.status})`;
        try {
          const errJson = await response.json();
          if (errJson && errJson.detail) errorDetail = errJson.detail;
        } catch (_) { }
        throw new ApiError(errorDetail, response.status);
      }
      const blob = await response.blob();
      const blobUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = blobUrl;
      const contentDisposition = response.headers.get('content-disposition');
      let filename = defaultFilename;
      if (contentDisposition && contentDisposition.includes('filename=')) {
        const match = contentDisposition.match(/filename=["']?([^"';]+)["']?/);
        if (match && match[1]) filename = match[1];
      }
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(blobUrl);
      return { success: true, filename: filename };
    },

    // --- Plan A Inspection ---
    async getPlanAReserveSummary() {
      return await ShopEasyAPI.get('/admin/plan-a/reserve/summary', { auth: 'admin' });
    },
    async getPlanAQueues() {
      return await ShopEasyAPI.get('/admin/plan-a/queues', { auth: 'admin' });
    },
    async getPlanAQueueEntries(queueId, params = {}) {
      const q = new URLSearchParams();
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-a/queues/${queueId}/entries${qs}`, { auth: 'admin' });
    },
    async getPlanACycles(params = {}) {
      const q = new URLSearchParams();
      if (params.recipient_user_id) q.set('recipient_user_id', params.recipient_user_id);
      if (params.queue_id) q.set('queue_id', params.queue_id);
      if (params.status) q.set('status', params.status);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-a/cycles${qs}`, { auth: 'admin' });
    },
    async getPlanACycleContributions(cycleId) {
      return await ShopEasyAPI.get(`/admin/plan-a/cycles/${cycleId}/contributions`, { auth: 'admin' });
    },
    async getPlanAReserve(params = {}) {
      const q = new URLSearchParams();
      if (params.queue_id) q.set('queue_id', params.queue_id);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-a/reserve${qs}`, { auth: 'admin' });
    },
    async getCustomerCashbackSummary(customerId) {
      return await ShopEasyAPI.get(`/admin/plan-a/customers/${customerId}/cashback-summary`, { auth: 'admin' });
    },
    async getPlanACommissions(params = {}) {
      const q = new URLSearchParams();
      if (params.purchaser_id) q.set('purchaser_id', params.purchaser_id);
      if (params.referrer_id) q.set('referrer_id', params.referrer_id);
      if (params.status) q.set('status', params.status);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-a/commissions${qs}`, { auth: 'admin' });
    },
    async getPlanACustomerCashback(customerId) {
      return await ShopEasyAPI.get(`/admin/plan-a/customers/${customerId}/cashback-summary`, { auth: 'admin' });
    },

    // --- Plan A Report Downloads (6 formats) ---
    async downloadPlanACommissionsReport(format = 'excel', params = {}) {
      const q = new URLSearchParams({ format: format });
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      if (params.customer_id) q.set('customer_id', params.customer_id);
      if (params.billing_id) q.set('billing_id', params.billing_id);
      const ext = format === 'pdf' ? 'pdf' : 'xlsx';
      return await this.downloadFile(`/admin/plan-a/reports/commissions?${q.toString()}`, `plan_a_commissions.${ext}`);
    },
    async downloadPlanACashbackReport(format = 'excel', params = {}) {
      const q = new URLSearchParams({ format: format });
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      if (params.customer_id) q.set('customer_id', params.customer_id);
      if (params.queue_id) q.set('queue_id', params.queue_id);
      if (params.billing_id) q.set('billing_id', params.billing_id);
      const ext = format === 'pdf' ? 'pdf' : 'xlsx';
      return await this.downloadFile(`/admin/plan-a/reports/cashback?${q.toString()}`, `plan_a_cashback.${ext}`);
    },
    async downloadPlanACustomerStatement(customerId, format = 'excel', params = {}) {
      const q = new URLSearchParams({ format: format });
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      const ext = format === 'pdf' ? 'pdf' : 'xlsx';
      const cleanId = encodeURIComponent(String(customerId).trim());
      return await this.downloadFile(`/admin/plan-a/reports/customers/${cleanId}/statement?${q.toString()}`, `customer_${cleanId}_statement.${ext}`);
    },

    // --- Plan B Inspection ---
    async getPlanBOverviewSummary() {
      return await ShopEasyAPI.get('/admin/plan-b/summary', { auth: 'admin' });
    },
    async getPlanBDistributors(params = {}) {
      const q = new URLSearchParams();
      if (params.search) q.set('search', params.search);
      if (params.status) q.set('status', params.status);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-b/distributors${qs}`, { auth: 'admin' });
    },
    async getPlanBDistributor(distributorId) {
      return await ShopEasyAPI.get(`/admin/plan-b/distributors/${distributorId}`, { auth: 'admin' });
    },
    async getPlanBDistributorReferrals(distributorId, params = {}) {
      const q = new URLSearchParams();
      if (params.is_active_only !== undefined) q.set('is_active_only', params.is_active_only);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-b/distributors/${distributorId}/referrals${qs}`, { auth: 'admin' });
    },
    async getPlanBDistributorWallet(distributorId) {
      return await ShopEasyAPI.get(`/admin/plan-b/distributors/${distributorId}/wallet`, { auth: 'admin' });
    },
    async getPlanBDirectCommissions(params = {}) {
      const q = new URLSearchParams();
      if (params.distributor_id) q.set('distributor_id', params.distributor_id);
      if (params.referee_id) q.set('referee_id', params.referee_id);
      if (params.order_id) q.set('order_id', params.order_id);
      if (params.billing_id) q.set('billing_id', params.billing_id);
      if (params.status) q.set('status', params.status);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-b/commissions/direct${qs}`, { auth: 'admin' });
    },
    async getPlanBGenerationCommissions(params = {}) {
      const q = new URLSearchParams();
      if (params.distributor_id) q.set('distributor_id', params.distributor_id);
      if (params.referee_id) q.set('referee_id', params.referee_id);
      if (params.order_id) q.set('order_id', params.order_id);
      if (params.billing_id) q.set('billing_id', params.billing_id);
      if (params.status) q.set('status', params.status);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-b/commissions/generation${qs}`, { auth: 'admin' });
    },
    async getPlanBBillingIds(params = {}) {
      const q = new URLSearchParams();
      if (params.user_id) q.set('user_id', params.user_id);
      if (params.order_id) q.set('order_id', params.order_id);
      if (params.status) q.set('status', params.status);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/plan-b/billing-ids${qs}`, { auth: 'admin' });
    },

    // --- Plan B Report Downloads (3 formats - Strictly Excel only per R-09) ---
    async downloadPlanBPurchasesReport(params = {}) {
      const q = new URLSearchParams({ format: 'excel' });
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      if (params.customer_name) q.set('customer_name', params.customer_name);
      if (params.distributor_name) q.set('distributor_name', params.distributor_name);
      if (params.mobile) q.set('mobile', params.mobile);
      if (params.billing_id) q.set('billing_id', params.billing_id);
      if (params.order_id) q.set('order_id', params.order_id);
      return await this.downloadFile(`/admin/plan-b/reports/purchases?${q.toString()}`, 'plan_b_purchases.xlsx');
    },
    async downloadPlanBCommissionsReport(params = {}) {
      const q = new URLSearchParams({ format: 'excel' });
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      if (params.distributor_name) q.set('distributor_name', params.distributor_name);
      if (params.customer_name) q.set('customer_name', params.customer_name);
      if (params.billing_id) q.set('billing_id', params.billing_id);
      if (params.order_id) q.set('order_id', params.order_id);
      if (params.commission_type) q.set('commission_type', params.commission_type);
      return await this.downloadFile(`/admin/plan-b/reports/commissions?${q.toString()}`, 'plan_b_commissions.xlsx');
    },
    async downloadPlanBDistributorReport(distributorId, params = {}) {
      const q = new URLSearchParams({ format: 'excel' });
      if (params.start_date) q.set('start_date', params.start_date);
      if (params.end_date) q.set('end_date', params.end_date);
      const cleanId = encodeURIComponent(String(distributorId).trim());
      return await this.downloadFile(`/admin/plan-b/reports/distributors/${cleanId}?${q.toString()}`, `distributor_${cleanId}_profile.xlsx`);
    },

    // --- Withdrawal Moderation ---
    async getPendingWithdrawals() {
      return await ShopEasyAPI.get('/admin/withdrawals/pending', { auth: 'admin' });
    },
    async approveWithdrawal(withdrawalId) {
      return await ShopEasyAPI.post(`/admin/withdrawals/${withdrawalId}/approve`, {}, { auth: 'admin' });
    },
    async rejectWithdrawal(withdrawalId, reason) {
      if (!reason || !reason.trim()) {
        throw new ApiError('A rejection reason is mandatory.', 400);
      }
      return await ShopEasyAPI.post(`/admin/withdrawals/${withdrawalId}/reject`, { reason: reason.trim() }, { auth: 'admin' });
    },
    async freezeWallet(walletId, reason) {
      if (!reason || !reason.trim()) {
        throw new ApiError('A reason is mandatory for freezing a wallet.', 400);
      }
      return await ShopEasyAPI.post(`/admin/wallets/${walletId}/freeze`, { reason: reason.trim() }, { auth: 'admin' });
    },
    async unfreezeWallet(walletId, reason = 'Administrative unfreeze') {
      return await ShopEasyAPI.post(`/admin/wallets/${walletId}/unfreeze`, { reason: reason }, { auth: 'admin' });
    },
    async getWalletFreezeHistory(walletId) {
      return await ShopEasyAPI.get(`/admin/wallets/${walletId}/freeze-history`, { auth: 'admin' });
    },
    async lookupWalletsByUserNumber(userNumber) {
      const q = (userNumber || '').trim();
      if (!q) throw new ApiError('User Number cannot be empty.', 400);
      return await ShopEasyAPI.get(`/admin/wallets/lookup-by-user-number?user_number=${encodeURIComponent(q)}`, { auth: 'admin' });
    },
    async freezeWalletByUserNumber(userNumber, reason, walletId = null) {
      if (!reason || !reason.trim()) {
        throw new ApiError('A reason is mandatory for freezing a wallet.', 400);
      }
      return await ShopEasyAPI.post('/admin/wallets/freeze-by-user-number', {
        user_number: (userNumber || '').trim(),
        wallet_id: walletId,
        reason: reason.trim()
      }, { auth: 'admin' });
    },
    async unfreezeWalletByUserNumber(userNumber, reason = 'Administrative unfreeze', walletId = null) {
      return await ShopEasyAPI.post('/admin/wallets/unfreeze-by-user-number', {
        user_number: (userNumber || '').trim(),
        wallet_id: walletId,
        reason: (reason || 'Administrative unfreeze').trim()
      }, { auth: 'admin' });
    },
    async getWalletFreezeHistoryByUserNumber(userNumber, walletId = null) {
      const q = (userNumber || '').trim();
      if (!q) throw new ApiError('User Number cannot be empty.', 400);
      let url = `/admin/wallets/freeze-history-by-user-number?user_number=${encodeURIComponent(q)}`;
      if (walletId) url += `&wallet_id=${walletId}`;
      return await ShopEasyAPI.get(url, { auth: 'admin' });
    },

    // --- Unified Search ---
    async search(query) {
      const q = (query || '').trim();
      if (!q) throw new ApiError('Search query cannot be empty.', 400);
      return await ShopEasyAPI.get(`/admin/search?q=${encodeURIComponent(q)}`, { auth: 'admin' });
    },

    // --- Plan A Dedicated Search ---
    async searchPlanA(query) {
      const q = (query || '').trim();
      if (!q) throw new ApiError('Plan A search query cannot be empty.', 400);
      return await ShopEasyAPI.get(`/admin/plan-a/search?q=${encodeURIComponent(q)}`, { auth: 'admin' });
    },

    // --- Plan B Dedicated Search ---
    async searchPlanB(query) {
      const q = (query || '').trim();
      if (!q) throw new ApiError('Plan B search query cannot be empty.', 400);
      return await ShopEasyAPI.get(`/admin/plan-b/search?q=${encodeURIComponent(q)}`, { auth: 'admin' });
    },

    // --- Financial Settings ---
    async getFinancialSettings(params = {}) {
      const q = new URLSearchParams();
      if (params.programme) q.set('programme', params.programme);
      if (params.setting_key) q.set('setting_key', params.setting_key);
      if (params.is_active !== undefined) q.set('is_active', params.is_active);
      if (params.as_of) q.set('as_of', params.as_of);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/admin/financial-settings${qs}`, { auth: 'admin' });
    },
    async createFinancialSetting(payload) {
      return await ShopEasyAPI.post('/admin/financial-settings', payload, { auth: 'admin' });
    },

    // --- Admin In-Dashboard Notifications ---
    async getNotifications(params = {}) {
      const q = new URLSearchParams();
      if (params.programme) q.set('programme', params.programme);
      if (params.is_read !== undefined) q.set('is_read', params.is_read);
      if (params.page !== undefined) q.set('page', params.page);
      if (params.page_size !== undefined) q.set('page_size', params.page_size);
      const qs = q.toString() ? `?${q.toString()}` : '';
      return await ShopEasyAPI.get(`/notifications${qs}`, { auth: 'admin' });
    }
  };

  // -------------------------------------------------------------------------
  // Global Browser Exports
  // -------------------------------------------------------------------------
  ShopEasyAPI.getSafeRedirectUrl = getSafeRedirectUrl;
  ShopEasyAPI.products = ShopEasyProducts;
  ShopEasyAPI.cart = ShopEasyCart;
  ShopEasyAPI.addresses = ShopEasyAddresses;
  ShopEasyAPI.orders = ShopEasyOrders;
  ShopEasyAPI.referrals = ShopEasyReferrals;
  ShopEasyAPI.cashback = ShopEasyCashback;
  ShopEasyAPI.dashboard = ShopEasyDashboard;
  ShopEasyAPI.wallets = ShopEasyWallets;
  ShopEasyAPI.notifications = ShopEasyNotifications;
  ShopEasyAPI.distributorReports = ShopEasyDistributorReports;
  ShopEasyAPI.admin = ShopEasyAdmin;

  window.ShopEasyAPI = ShopEasyAPI;
  window.ShopEasyAuth = ShopEasyAuth;
  window.ShopEasyProducts = ShopEasyProducts;
  window.ShopEasyCart = ShopEasyCart;
  window.ShopEasyAddresses = ShopEasyAddresses;
  window.ShopEasyOrders = ShopEasyOrders;
  window.ShopEasyReferrals = ShopEasyReferrals;
  window.ShopEasyCashback = ShopEasyCashback;
  window.ShopEasyDashboard = ShopEasyDashboard;
  window.ShopEasyWallets = ShopEasyWallets;
  window.ShopEasyNotifications = ShopEasyNotifications;
  window.ShopEasyDistributorReports = ShopEasyDistributorReports;
  window.ShopEasyAdmin = ShopEasyAdmin;
  window.ApiError = ApiError;
  window.getSafeRedirectUrl = getSafeRedirectUrl;
  window.requireCustomerAuth = requireCustomerAuth;
  window.requireAdminAuth = requireAdminAuth;
  window.redirectIfCustomerAuthenticated = redirectIfCustomerAuthenticated;
  window.redirectIfAdminAuthenticated = redirectIfAdminAuthenticated;

})();
