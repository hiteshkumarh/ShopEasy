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
  // Token Storage Helpers (Strict Role Isolation)
  // -------------------------------------------------------------------------
  function getCustomerToken() {
    try {
      return localStorage.getItem(CUSTOMER_TOKEN_KEY);
    } catch (e) {
      return null;
    }
  }

  function setCustomerToken(token) {
    try {
      if (token) {
        localStorage.setItem(CUSTOMER_TOKEN_KEY, token);
      } else {
        localStorage.removeItem(CUSTOMER_TOKEN_KEY);
      }
    } catch (e) {}
  }

  function clearCustomerToken() {
    try {
      localStorage.removeItem(CUSTOMER_TOKEN_KEY);
      localStorage.removeItem(CUSTOMER_USER_KEY);
    } catch (e) {}
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
    } catch (e) {}
  }

  function getAdminToken() {
    try {
      return sessionStorage.getItem(ADMIN_TOKEN_KEY) || localStorage.getItem(ADMIN_TOKEN_KEY);
    } catch (e) {
      return null;
    }
  }

  function setAdminToken(token) {
    try {
      if (token) {
        sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
        localStorage.setItem(ADMIN_TOKEN_KEY, token);
      } else {
        sessionStorage.removeItem(ADMIN_TOKEN_KEY);
        localStorage.removeItem(ADMIN_TOKEN_KEY);
      }
    } catch (e) {}
  }

  function clearAdminToken() {
    try {
      sessionStorage.removeItem(ADMIN_TOKEN_KEY);
      sessionStorage.removeItem(ADMIN_USER_KEY);
      localStorage.removeItem(ADMIN_TOKEN_KEY);
      localStorage.removeItem(ADMIN_USER_KEY);
    } catch (e) {}
  }

  function getAdminUser() {
    try {
      const raw = sessionStorage.getItem(ADMIN_USER_KEY) || localStorage.getItem(ADMIN_USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function setAdminUser(user) {
    try {
      if (user) {
        sessionStorage.setItem(ADMIN_USER_KEY, JSON.stringify(user));
        localStorage.setItem(ADMIN_USER_KEY, JSON.stringify(user));
      } else {
        sessionStorage.removeItem(ADMIN_USER_KEY);
        localStorage.removeItem(ADMIN_USER_KEY);
      }
    } catch (e) {}
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
      if (response.status === 401 && options.redirectOn401) {
        if (options.auth === 'admin' || (typeof window !== 'undefined' && window.location.pathname.includes('/admin/'))) {
          clearAdminToken();
          const cur = window.location.pathname.split('/').pop() || 'dashboard.html';
          window.location.href = `login.html?redirect=${encodeURIComponent(cur)}`;
        } else {
          clearCustomerToken();
          const cur = window.location.pathname.split('/').pop() || 'profile.html';
          window.location.href = `login.html?redirect=${encodeURIComponent(cur)}`;
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
    delete(endpoint, options = {}) {
      return apiRequest(endpoint, Object.assign({}, options, { method: 'DELETE' }));
    },
    // Storage accessors
    getCustomerToken,
    setCustomerToken,
    clearCustomerToken,
    getCustomerUser,
    setCustomerUser,
    getAdminToken,
    setAdminToken,
    clearAdminToken,
    getAdminUser,
    setAdminUser,
  };

  // -------------------------------------------------------------------------
  // ShopEasyAuth Service (Customer & Administrator Authentication)
  // -------------------------------------------------------------------------
  const ShopEasyAuth = {
    // === Customer Authentication ===
    async register({ fullName, phone, password, confirmPassword }) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const payload = {
        full_name: String(fullName).trim(),
        phone: cleanPhone,
        password: password,
        confirm_password: confirmPassword !== undefined ? confirmPassword : password,
      };
      return await ShopEasyAPI.post(
        '/auth/customer/register',
        payload,
        { auth: false }
      );
    },

    async customerLogin(phone, password) {
      return await this.loginCustomerViaPassword(phone, password);
    },

    async requestCustomerOtp(phone) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      return await ShopEasyAPI.post(
        '/auth/customer/otp/request',
        { phone: cleanPhone },
        { auth: false }
      );
    },

    async loginCustomerViaOtp(phone, otpCode) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const cleanOtp = String(otpCode).trim();
      const tokenRes = await ShopEasyAPI.post(
        '/auth/customer/login/otp',
        { phone: cleanPhone, otp_code: cleanOtp },
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

    async loginCustomerViaPassword(phone, password) {
      const cleanPhone = String(phone).replace(/\D/g, '');
      const tokenRes = await ShopEasyAPI.post(
        '/auth/customer/login/password',
        { phone: cleanPhone, password: password },
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
  // Global Browser Exports
  // -------------------------------------------------------------------------
  ShopEasyAPI.getSafeRedirectUrl = getSafeRedirectUrl;
  ShopEasyAPI.products = ShopEasyProducts;
  ShopEasyAPI.cart = ShopEasyCart;
  ShopEasyAPI.addresses = ShopEasyAddresses;
  ShopEasyAPI.orders = ShopEasyOrders;
  ShopEasyAPI.referrals = ShopEasyReferrals;
  ShopEasyAPI.dashboard = ShopEasyDashboard;
  ShopEasyAPI.wallets = ShopEasyWallets;

  window.ShopEasyAPI = ShopEasyAPI;
  window.ShopEasyAuth = ShopEasyAuth;
  window.ShopEasyProducts = ShopEasyProducts;
  window.ShopEasyCart = ShopEasyCart;
  window.ShopEasyAddresses = ShopEasyAddresses;
  window.ShopEasyOrders = ShopEasyOrders;
  window.ShopEasyReferrals = ShopEasyReferrals;
  window.ShopEasyDashboard = ShopEasyDashboard;
  window.ShopEasyWallets = ShopEasyWallets;
  window.ApiError = ApiError;
  window.getSafeRedirectUrl = getSafeRedirectUrl;
  window.requireCustomerAuth = requireCustomerAuth;
  window.requireAdminAuth = requireAdminAuth;
  window.redirectIfCustomerAuthenticated = redirectIfCustomerAuthenticated;
  window.redirectIfAdminAuthenticated = redirectIfAdminAuthenticated;

})();
