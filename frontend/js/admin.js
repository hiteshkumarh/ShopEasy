/**
 * ShopEasy --- Admin Portal Logic
 * Manages Admin Login, Dashboard Metrics, and Product Catalog Management.
 * Follows strict architectural constraints:
 * - Admin accounts are pre-provisioned (no self-registration).
 * - Admin role cannot be self-selected.
 * - Admin accounts never receive referral codes.
 */

const ADMIN_SESSION_KEY = 'shopeasy_admin_session';
const ADMIN_PRODUCTS_KEY = 'shopeasy_admin_products';

// ---------------------------------------------------------------------------
// Admin Session & Navigation
// ---------------------------------------------------------------------------
function getAdminSession() {
  if (window.ShopEasyAPI) {
    return window.ShopEasyAPI.getAdminUser();
  }
  try {
    const raw = sessionStorage.getItem(ADMIN_SESSION_KEY) || localStorage.getItem(ADMIN_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function adminLogout(redirectUrl = 'login.html') {
  if (window.ShopEasyAuth) {
    window.ShopEasyAuth.adminLogout(redirectUrl);
  } else {
    try {
      sessionStorage.removeItem(ADMIN_SESSION_KEY);
      localStorage.removeItem(ADMIN_SESSION_KEY);
    } catch (e) {}
    window.location.href = redirectUrl;
  }
}

async function initAdminShell() {
  try { localStorage.removeItem('shopeasy_orders'); } catch (e) {}
  // Live administrator authentication guard
  let admin = null;
  if (window.requireAdminAuth) {
    admin = await window.requireAdminAuth();
    if (!admin) return null; // Handled by requireAdminAuth redirect
  } else {
    admin = getAdminSession() || { role: 'admin' };
  }

  // Highlight active sidebar navigation link
  const currentPath = window.location.pathname.split('/').pop() || 'dashboard.html';
  const navItems = document.querySelectorAll('.admin-nav-item');
  navItems.forEach(item => {
    const href = item.getAttribute('href');
    if (!href) return;
    const itemPath = href.split('/').pop().split('?')[0];
    if (itemPath === currentPath) {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });

  // Mobile sidebar drawer toggle
  const mobileToggle = document.querySelector('.admin-mobile-toggle');
  const sidebar = document.querySelector('.admin-sidebar');
  let backdrop = document.querySelector('.admin-sidebar-backdrop');

  if (mobileToggle && sidebar) {
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.className = 'admin-sidebar-backdrop';
      document.body.appendChild(backdrop);
    }

    mobileToggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      backdrop.classList.toggle('show');
    });

    backdrop.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('show');
    });
  }

  return admin;
}

// ---------------------------------------------------------------------------
// Admin Products Storage (localStorage)
// ---------------------------------------------------------------------------
function getCategoryFallbackImage(category, name) {
  if (name && /power\s*bank/i.test(name)) {
    return 'https://images.unsplash.com/photo-1609592426868-b8ce1fa46211?w=800&auto=format&fit=crop&q=80';
  }
  const fallbacks = {
    'electronics': 'https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=800&auto=format&fit=crop&q=80',
    'fashion': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&auto=format&fit=crop&q=80',
    'accessories': 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800&auto=format&fit=crop&q=80',
    'home': 'https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=800&auto=format&fit=crop&q=80',
    'beauty': 'https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?w=800&auto=format&fit=crop&q=80'
  };
  if (category && fallbacks[category]) {
    return fallbacks[category];
  }
  if (typeof getPlaceholderImage === 'function') {
    return getPlaceholderImage(name);
  }
  return 'https://images.unsplash.com/photo-1609592426868-b8ce1fa46211?w=800&auto=format&fit=crop&q=80';
}

/**
 * Downscales and compresses an image file to a lightweight JPEG data URL
 * to ensure products never exceed browser localStorage quotas (~5MB).
 */
function compressImageFile(file, maxWidth = 600, maxHeight = 600, quality = 0.8) {
  return new Promise((resolve) => {
    if (!file || !file.type || !file.type.startsWith('image/')) {
      return resolve(null);
    }

    const reader = new FileReader();
    reader.onerror = () => resolve(null);
    reader.onload = (e) => {
      const rawDataUrl = e.target.result;
      if (typeof Image === 'undefined' || typeof document === 'undefined') {
        return resolve(rawDataUrl);
      }

      const img = new Image();
      img.onerror = () => resolve(rawDataUrl);
      img.onload = () => {
        try {
          let width = img.naturalWidth || img.width;
          let height = img.naturalHeight || img.height;

          if (width > maxWidth || height > maxHeight) {
            if (width / height > maxWidth / maxHeight) {
              height = Math.round((height * maxWidth) / width);
              width = maxWidth;
            } else {
              width = Math.round((width * maxHeight) / height);
              height = maxHeight;
            }
          }

          const canvas = document.createElement('canvas');
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext('2d');
          if (!ctx) {
            return resolve(rawDataUrl);
          }

          ctx.drawImage(img, 0, 0, width, height);
          const compressed = canvas.toDataURL('image/jpeg', quality);
          resolve(compressed);
        } catch (err) {
          console.warn('Canvas compression error; using raw data URL fallback', err);
          resolve(rawDataUrl);
        }
      };
      img.src = rawDataUrl;
    };
    reader.readAsDataURL(file);
  });
}

let adminProductsList = [];

function getAdminProducts() {
  return adminProductsList;
}

async function getAdminProductById(id) {
  if (window.ShopEasyProducts && window.ShopEasyProducts.adminGetById) {
    try {
      return await window.ShopEasyProducts.adminGetById(id);
    } catch (err) {
      console.error('Failed to get product by id:', err);
      return null;
    }
  }
  return adminProductsList.find(p => p.id === id || String(p.id) === String(id)) || null;
}

async function deleteAdminProduct(id) {
  clearAdminMessage();
  const confirmed = window.confirm(`Are you sure you want to deactivate product #${id}?`);
  if (!confirmed) return;

  try {
    if (window.ShopEasyProducts && window.ShopEasyProducts.adminDelete) {
      await window.ShopEasyProducts.adminDelete(id);
      showAdminMessage(`Product #${id} has been deactivated successfully.`, 'success');
      await loadAdminProducts();
    }
  } catch (err) {
    showAdminMessage(err.detail || err.message || 'Failed to deactivate product.', 'error');
  }
}

// ---------------------------------------------------------------------------
// 1. Admin Login Page
// ---------------------------------------------------------------------------
let adminLoginMode = 'password'; // 'password' or 'otp'
let currentAdminPhone = '';
let pendingMfaToken = null;

function switchAdminMode(mode) {
  adminLoginMode = mode;
  pendingMfaToken = null;
  clearAdminMessage();

  const tabPassword = document.getElementById('admin-tab-password');
  const tabOtp = document.getElementById('admin-tab-otp');
  const passwordStep = document.getElementById('admin-password-step');
  const phoneStep = document.getElementById('admin-phone-step');
  const otpStep = document.getElementById('admin-otp-step');

  if (tabPassword) {
    const isPwd = mode === 'password';
    tabPassword.classList.toggle('active', isPwd);
    tabPassword.setAttribute('aria-selected', isPwd ? 'true' : 'false');
  }
  if (tabOtp) {
    const isOtp = mode === 'otp';
    tabOtp.classList.toggle('active', isOtp);
    tabOtp.setAttribute('aria-selected', isOtp ? 'true' : 'false');
  }

  if (otpStep) otpStep.classList.remove('active');

  if (mode === 'password') {
    if (passwordStep) passwordStep.style.display = 'block';
    if (phoneStep) phoneStep.style.display = 'none';
  } else {
    if (passwordStep) passwordStep.style.display = 'none';
    if (phoneStep) phoneStep.style.display = 'block';
  }
}

function switchAdminStep(step) {
  clearAdminMessage();
  const passwordStep = document.getElementById('admin-password-step');
  const phoneStep = document.getElementById('admin-phone-step');
  const otpStep = document.getElementById('admin-otp-step');

  if (step === 'back') {
    pendingMfaToken = null;
    if (otpStep) otpStep.classList.remove('active');
    if (adminLoginMode === 'password') {
      if (passwordStep) passwordStep.style.display = 'block';
      if (phoneStep) phoneStep.style.display = 'none';
    } else {
      if (passwordStep) passwordStep.style.display = 'none';
      if (phoneStep) phoneStep.style.display = 'block';
    }
  } else if (step === 'otp') {
    if (passwordStep) passwordStep.style.display = 'none';
    if (phoneStep) phoneStep.style.display = 'none';
    if (otpStep) {
      otpStep.classList.add('active');
      setupAdminOtpBoxes();
    }
  }
}

function initAdminLogin() {
  // If already authenticated as administrator, redirect to dashboard
  if (window.redirectIfAdminAuthenticated) {
    window.redirectIfAdminAuthenticated('dashboard.html');
  }

  // Wire Tab Switches
  const tabPassword = document.getElementById('admin-tab-password');
  const tabOtp = document.getElementById('admin-tab-otp');
  if (tabPassword) {
    tabPassword.addEventListener('click', () => switchAdminMode('password'));
  }
  if (tabOtp) {
    tabOtp.addEventListener('click', () => switchAdminMode('otp'));
  }

  // 1. Password Login Form
  const pwdForm = document.getElementById('admin-password-form');
  const pwdPhoneInput = document.getElementById('admin-pwd-phone');
  const pwdInput = document.getElementById('admin-pwd-input');
  const pwdBtn = document.getElementById('admin-pwd-btn');
  const displayPhone = document.getElementById('admin-display-phone');
  const otpTitle = document.getElementById('admin-otp-title');
  const otpSubtitle = document.getElementById('admin-otp-subtitle');

  if (pwdForm) {
    pwdForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAdminMessage();

      const rawPhone = pwdPhoneInput.value.trim().replace(/\D/g, '');
      const rawPwd = pwdInput.value;

      if (rawPhone.length !== 10) {
        showAdminMessage('Please enter a valid 10-digit administrator mobile number.', 'error');
        pwdPhoneInput.focus();
        return;
      }

      if (!rawPwd) {
        showAdminMessage('Please enter your administrator password.', 'error');
        pwdInput.focus();
        return;
      }

      currentAdminPhone = rawPhone;
      if (displayPhone) displayPhone.textContent = `+91 ${rawPhone}`;

      if (pwdBtn) {
        pwdBtn.disabled = true;
        pwdBtn.textContent = 'Verifying Password...';
      }

      try {
        const authRes = await window.ShopEasyAuth.loginAdminViaPassword(rawPhone, rawPwd);
        showAdminMessage('Signed in successfully! Redirecting...', 'success');

        if (pwdBtn) {
          pwdBtn.textContent = 'Access Authorized ✓';
          pwdBtn.classList.remove('btn-primary');
          pwdBtn.classList.add('btn-secondary');
        }

        const rawRedirect = new URLSearchParams(window.location.search).get('redirect');
        const redirectParam = window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'dashboard.html') : 'dashboard.html';
        setTimeout(() => {
          window.location.href = redirectParam;
        }, 300);
      } catch (err) {
        showAdminMessage(err.detail || 'Invalid administrator mobile number or password.', 'error');
      } finally {
        if (pwdBtn && !pwdBtn.classList.contains('btn-secondary')) {
          pwdBtn.disabled = false;
          pwdBtn.textContent = 'Sign In as Admin';
        }
      }
    });
  }

  // 2. Direct Phone OTP Form
  const phoneForm = document.getElementById('admin-phone-form');
  const phoneInput = document.getElementById('admin-phone-input');
  const sendBtn = document.getElementById('admin-send-otp-btn');

  if (phoneForm) {
    phoneForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAdminMessage();

      const rawPhone = phoneInput.value.trim().replace(/\D/g, '');
      if (rawPhone.length !== 10) {
        showAdminMessage('Please enter a valid 10-digit mobile number.', 'error');
        phoneInput.focus();
        return;
      }

      currentAdminPhone = rawPhone;
      pendingMfaToken = null;
      if (displayPhone) displayPhone.textContent = `+91 ${rawPhone}`;

      if (sendBtn) {
        sendBtn.disabled = true;
        sendBtn.textContent = 'Requesting OTP...';
      }

      try {
        const res = await window.ShopEasyAuth.requestAdminOtp(rawPhone);
        if (otpTitle) otpTitle.textContent = 'Verify Admin OTP';
        if (otpSubtitle) {
          otpSubtitle.innerHTML = `Enter the 6-digit one-time password delivered to <strong>+91 ${rawPhone}</strong>`;
        }

        switchAdminStep('otp');

        let msg = res.message || `OTP sent to +91 ${rawPhone}.`;
        if (res.dev_otp) {
          msg += ` (Dev OTP: ${res.dev_otp})`;
          const boxes = document.querySelectorAll('.admin-otp-box');
          for (let i = 0; i < res.dev_otp.length && i < boxes.length; i++) {
            boxes[i].value = res.dev_otp[i];
          }
        }
        showAdminMessage(msg, 'success');
      } catch (err) {
        showAdminMessage(err.detail || 'Failed to generate administrator OTP.', 'error');
      } finally {
        if (sendBtn) {
          sendBtn.disabled = false;
          sendBtn.textContent = 'Send OTP';
        }
      }
    });
  }

  // 3. OTP & MFA Verification Form
  const otpForm = document.getElementById('admin-otp-form');
  const verifyBtn = document.getElementById('admin-verify-btn');

  if (otpForm) {
    otpForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAdminMessage();

      const boxes = document.querySelectorAll('.admin-otp-box');
      let code = '';
      boxes.forEach(box => (code += box.value.trim()));

      if (code.length !== 6) {
        showAdminMessage('Please enter the complete 6-digit verification code.', 'error');
        return;
      }

      if (verifyBtn) {
        verifyBtn.disabled = true;
        verifyBtn.textContent = 'Verifying Credentials...';
      }

      try {
        if (pendingMfaToken) {
          // Complete MFA Challenge
          await window.ShopEasyAuth.verifyAdminMfa(pendingMfaToken, code);
        } else {
          // Direct OTP Login
          await window.ShopEasyAuth.loginAdminViaOtp(currentAdminPhone, code);
        }

        showAdminMessage('Authentication successful. Administrator access authorized.', 'success');

        if (verifyBtn) {
          verifyBtn.textContent = 'Access Authorized ✓';
          verifyBtn.classList.remove('btn-primary');
          verifyBtn.classList.add('btn-secondary');
        }

        const rawRedirect = new URLSearchParams(window.location.search).get('redirect');
        const redirectParam = window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'dashboard.html') : 'dashboard.html';
        setTimeout(() => {
          window.location.href = redirectParam;
        }, 400);
      } catch (err) {
        showAdminMessage(err.detail || 'Invalid or expired verification code.', 'error');
      } finally {
        if (verifyBtn) {
          verifyBtn.disabled = false;
          verifyBtn.textContent = 'Verify & Continue';
        }
      }
    });
  }
}

function setupAdminOtpBoxes() {
  const boxes = document.querySelectorAll('.admin-otp-box');
  if (boxes.length === 0) return;
  boxes[0].focus();

  boxes.forEach((box, index) => {
    box.oninput = (e) => {
      const val = e.target.value.replace(/\D/g, '');
      box.value = val ? val[val.length - 1] : '';
      if (box.value && index < boxes.length - 1) {
        boxes[index + 1].focus();
      }
    };

    box.onkeydown = (e) => {
      if (e.key === 'Backspace' && !box.value && index > 0) {
        boxes[index - 1].focus();
      }
    };

    box.onpaste = (e) => {
      e.preventDefault();
      const pasteText = (e.clipboardData || window.clipboardData)
        .getData('text')
        .replace(/\D/g, '')
        .slice(0, 6);
      if (pasteText) {
        for (let i = 0; i < pasteText.length; i++) {
          if (boxes[i]) boxes[i].value = pasteText[i];
        }
        const nextIdx = Math.min(pasteText.length, boxes.length - 1);
        boxes[nextIdx].focus();
      }
    };
  });
}

async function handleAdminResendOtp() {
  clearAdminMessage();
  const boxes = document.querySelectorAll('.admin-otp-box');
  boxes.forEach(b => (b.value = ''));
  if (boxes[0]) boxes[0].focus();

  if (pendingMfaToken) {
    showAdminMessage('To request a new second-factor MFA code, please re-submit your password.', 'error');
    switchAdminStep('back');
    return;
  }

  if (!currentAdminPhone) {
    showAdminMessage('Please re-enter your mobile number to request an OTP.', 'error');
    switchAdminStep('back');
    return;
  }

  try {
    const res = await window.ShopEasyAuth.requestAdminOtp(currentAdminPhone);
    let msg = res.message || `A new OTP has been sent to +91 ${currentAdminPhone}.`;
    if (res.dev_otp) {
      msg += ` (Dev OTP: ${res.dev_otp})`;
    }
    showAdminMessage(msg, 'success');
  } catch (err) {
    showAdminMessage(err.detail || 'Failed to resend administrator OTP.', 'error');
  }
}

function showAdminMessage(msg, type = 'error') {
  const banner = document.getElementById('admin-message-banner');
  if (!banner) return;
  banner.textContent = msg;
  banner.className = `admin-message-banner ${type}`;
  banner.style.display = 'block';
}

function clearAdminMessage() {
  const banner = document.getElementById('admin-message-banner');
  if (!banner) return;
  banner.textContent = '';
  banner.className = 'admin-message-banner';
  banner.style.display = 'none';
}

// ---------------------------------------------------------------------------
// 2. Admin Dashboard Overview
// ---------------------------------------------------------------------------
async function initAdminDashboard() {
  const admin = await initAdminShell();
  if (!admin) return;

  let totalProducts = 0;
  let totalOrders = 0;
  let totalCustomers = 0;
  let totalRevenue = 0;
  let recentOrders = [];

  // Fetch real-time dashboard stats from backend
  try {
    if (window.ShopEasyDashboard && window.ShopEasyDashboard.adminStats) {
      const stats = await window.ShopEasyDashboard.adminStats();
      if (stats) {
        totalProducts = Number(stats.total_products) || 0;
        totalOrders = Number(stats.total_orders) || 0;
        totalCustomers = Number(stats.total_customers) || 0;
        totalRevenue = Number(stats.total_revenue) || 0;
      }
    } else if (window.ShopEasyProducts && window.ShopEasyProducts.adminList) {
      const prodRes = await window.ShopEasyProducts.adminList({ page: 1, page_size: 1 });
      totalProducts = (prodRes && typeof prodRes.total === 'number') ? prodRes.total : 0;
    }
  } catch (e) {
    console.warn('Dashboard stats fetch failed:', e);
  }

  // Fetch real recent orders from backend
  try {
    if (window.ShopEasyOrders && window.ShopEasyOrders.adminList) {
      const ordersRes = await window.ShopEasyOrders.adminList({ page: 1, page_size: 5 });
      if (ordersRes && Array.isArray(ordersRes.items)) {
        recentOrders = ordersRes.items;
      }
    }
  } catch (e) {
    console.warn('Dashboard orders fetch failed:', e);
  }

  // Update stat cards
  const elProducts = document.getElementById('stat-total-products');
  const elOrders = document.getElementById('stat-total-orders');
  const elCustomers = document.getElementById('stat-total-customers');
  const elRevenue = document.getElementById('stat-total-revenue');

  if (elProducts) elProducts.textContent = totalProducts;
  if (elOrders) elOrders.textContent = totalOrders;
  if (elCustomers) elCustomers.textContent = totalCustomers;
  if (elRevenue) elRevenue.textContent = formatCurrency(totalRevenue);

  // Render Recent Orders Table
  const ordersTableBody = document.getElementById('recent-orders-table-body');
  if (ordersTableBody) {
    if (recentOrders.length === 0) {
      ordersTableBody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">
            No orders recorded yet.
          </td>
        </tr>
      `;
    } else {
      ordersTableBody.innerHTML = recentOrders.map(o => {
        const itemNames = (o.items || []).map(i => `${escapeHtml(i.product_name)} (x${i.quantity})`).join(', ') || 'Catalog items';
        const badgeClass = o.order_status === 'confirmed' ? 'badge-success' : 'badge-primary';
        return `
          <tr>
            <td><strong style="font-family:var(--font-mono);">${escapeHtml(o.order_number)}</strong></td>
            <td>${escapeHtml(o.customer_name)}</td>
            <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(itemNames)}">${escapeHtml(itemNames)}</td>
            <td><strong>${formatCurrency(Number(o.total_amount))}</strong></td>
            <td><span class="badge ${badgeClass}">${escapeHtml(o.order_status)}</span></td>
          </tr>
        `;
      }).join('');
    }
  }
}

// ---------------------------------------------------------------------------
// 3. Admin Products Management Page
// ---------------------------------------------------------------------------
let adminCatalogState = {
  search: '',
  category: 'all'
};

async function initAdminProductsPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  const searchInput = document.getElementById('admin-product-search');
  const catSelect = document.getElementById('admin-category-filter');

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      adminCatalogState.search = e.target.value.trim().toLowerCase();
      renderAdminProductsTable();
    });
  }

  if (catSelect) {
    catSelect.addEventListener('change', (e) => {
      adminCatalogState.category = e.target.value;
      renderAdminProductsTable();
    });
  }

  await loadAdminProducts();
}

async function loadAdminProducts() {
  const tbody = document.getElementById('admin-products-table-body');
  const countEl = document.getElementById('admin-products-count');
  if (!tbody) return;

  tbody.innerHTML = `
    <tr>
      <td colspan="6" style="text-align:center;padding:var(--space-8);color:var(--color-muted);">
        <span class="spinner" style="display:inline-block;width:18px;height:18px;border:2px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:8px;"></span>
        Loading catalog products...
      </td>
    </tr>
  `;

  try {
    if (window.ShopEasyProducts && window.ShopEasyProducts.adminList) {
      const res = await window.ShopEasyProducts.adminList({ page: 1, page_size: 100 });
      adminProductsList = (res && Array.isArray(res.items)) ? res.items : [];
    } else {
      adminProductsList = [];
    }
    renderAdminProductsTable();
  } catch (err) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center;padding:var(--space-8);color:var(--color-danger);">
          <p style="margin-bottom:var(--space-3);">${escapeHtml(err.detail || err.message || 'Failed to load products from server.')}</p>
          <button type="button" class="btn btn-secondary btn-sm" onclick="loadAdminProducts()">Retry</button>
        </td>
      </tr>
    `;
    if (countEl) countEl.textContent = 'Error loading products';
    showAdminMessage(err.detail || 'Failed to load products.', 'error');
  }
}

function renderAdminProductsTable() {
  const tbody = document.getElementById('admin-products-table-body');
  const countEl = document.getElementById('admin-products-count');
  if (!tbody) return;

  let products = [...adminProductsList];

  // Search filter
  if (adminCatalogState.search) {
    const q = adminCatalogState.search.toLowerCase();
    products = products.filter(p =>
      (p.name && p.name.toLowerCase().includes(q)) ||
      (String(p.id).includes(q)) ||
      (p.product_code && p.product_code.toLowerCase().includes(q)) ||
      (p.description && p.description.toLowerCase().includes(q))
    );
  }

  if (countEl) {
    countEl.textContent = `Showing ${products.length} product${products.length === 1 ? '' : 's'}`;
  }

  if (products.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center;padding:var(--space-10);color:var(--color-muted);">
          No matching products found.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = products.map(p => {
    const stockBadge = p.stock > 10
      ? `<span class="badge badge-success">${p.stock} in stock</span>`
      : p.stock > 0
        ? `<span class="badge badge-warning">${p.stock} low stock</span>`
        : `<span class="badge badge-danger">Out of stock</span>`;

    const displayImg = p.image_url || getCategoryFallbackImage('electronics', p.name);

    return `
      <tr>
        <td>
          <div class="table-product-cell">
            <img
              src="${escapeHtml(displayImg)}"
              alt="${escapeHtml(p.name || 'Product')}"
              class="table-product-thumb"
              onerror="this.onerror=null;if(typeof getPlaceholderImage==='function'){this.src=getPlaceholderImage(this.alt);}"
            >
            <div class="table-product-info">
              <span class="table-product-name">${escapeHtml(p.name || 'Untitled Product')}</span>
              <span class="table-product-id">ID: #${p.id}${p.product_code ? ` &bull; SKU: ${escapeHtml(p.product_code)}` : ''}</span>
            </div>
          </div>
        </td>
        <td><span class="badge badge-muted">${p.is_power_bank ? 'Power Bank' : 'General'}</span></td>
        <td><strong>${formatCurrency(Number(p.price) || 0)}</strong></td>
        <td>${stockBadge}</td>
        <td>
          <span class="badge ${p.is_active ? 'badge-primary' : 'badge-muted'}">
            ${p.is_active ? 'Active' : 'Inactive'}
          </span>
        </td>
        <td>
          <div class="table-actions">
            <a href="product-form.html?id=${p.id}" class="table-action-btn" title="Edit product">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
              Edit
            </a>
            <button type="button" class="table-action-btn delete" onclick="deleteAdminProduct(${p.id})" title="Deactivate product">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
              Deactivate
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// ---------------------------------------------------------------------------
// 4. Product Add / Edit Form Page
// ---------------------------------------------------------------------------
async function initProductForm() {
  const admin = await initAdminShell();
  if (!admin) return;

  const urlParams = new URLSearchParams(window.location.search);
  const editId = urlParams.get('id');

  const pageTitle = document.getElementById('form-page-title');
  const form = document.getElementById('admin-product-form');
  const previewImg = document.getElementById('product-image-preview');
  const previewPlaceholder = document.getElementById('image-preview-placeholder');
  const imageFileInput = document.getElementById('product-image-file');
  const imageUrlInput = document.getElementById('product-image-url');
  const productCodeInput = document.getElementById('product-code');
  const hintEl = document.getElementById('image-upload-hint');

  let editingProduct = null;

  function setPreviewImage(src) {
    if (previewImg && previewPlaceholder) {
      previewImg.src = src;
      previewImg.style.display = 'block';
      previewPlaceholder.style.display = 'none';
    }
  }

  if (editId) {
    if (pageTitle) pageTitle.textContent = `Edit Product #${editId}`;
    document.title = `Edit Product #${editId} — ShopEasy Admin`;

    try {
      editingProduct = await getAdminProductById(editId);
      if (editingProduct) {
        if (pageTitle) pageTitle.textContent = `Edit Product — ${editingProduct.name}`;
        document.title = `Edit Product — ShopEasy Admin`;

        const nameEl = document.getElementById('product-name');
        const priceEl = document.getElementById('product-price');
        const stockEl = document.getElementById('product-stock');
        const statusEl = document.getElementById('product-status');
        const descEl = document.getElementById('product-description');

        if (nameEl) nameEl.value = editingProduct.name || '';
        if (priceEl) priceEl.value = editingProduct.price || '';
        if (stockEl) stockEl.value = editingProduct.stock !== undefined ? editingProduct.stock : '';
        if (statusEl) statusEl.value = editingProduct.is_active ? 'active' : 'inactive';
        if (descEl) descEl.value = editingProduct.description || '';
        if (productCodeInput && editingProduct.product_code) {
          productCodeInput.value = editingProduct.product_code;
        }

        if (editingProduct.image_url) {
          if (imageUrlInput) imageUrlInput.value = editingProduct.image_url;
          setPreviewImage(editingProduct.image_url);
        }
      } else {
        showAdminMessage(`Product #${editId} not found.`, 'error');
      }
    } catch (err) {
      showAdminMessage(err.detail || 'Failed to load product details.', 'error');
    }
  }

  // Handle Image File selection -> Automatic upload & Live preview
  if (imageFileInput) {
    imageFileInput.addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      // Show immediate local preview
      try {
        const localPreviewUrl = URL.createObjectURL(file);
        setPreviewImage(localPreviewUrl);
      } catch (err) {}

      if (hintEl) {
        hintEl.textContent = 'Uploading image to catalog...';
        hintEl.style.color = 'var(--color-primary)';
      }

      try {
        if (window.ShopEasyProducts && window.ShopEasyProducts.adminUploadImage) {
          const res = await window.ShopEasyProducts.adminUploadImage(file);
          if (res && res.url) {
            if (imageUrlInput) imageUrlInput.value = res.url;
            setPreviewImage(res.url);
            if (hintEl) {
              hintEl.textContent = 'Image uploaded and saved to product successfully!';
              hintEl.style.color = 'var(--color-success)';
            }
          }
        }
      } catch (err) {
        console.error('Image upload failed:', err);
        if (hintEl) {
          hintEl.textContent = 'Direct upload failed. You can paste an image URL in the field below.';
          hintEl.style.color = 'var(--color-danger)';
        }
      }
    });
  }

  // Handle Image URL input -> Live preview
  if (imageUrlInput) {
    imageUrlInput.addEventListener('input', (e) => {
      const url = e.target.value.trim();
      if (url) {
        setPreviewImage(url);
      }
    });
  }

  // Form Submit (Save Product)
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAdminMessage();

      const nameInput = document.getElementById('product-name');
      const priceInput = document.getElementById('product-price');
      const stockInput = document.getElementById('product-stock');
      const statusInput = document.getElementById('product-status');
      const descInput = document.getElementById('product-description');

      const name = nameInput ? nameInput.value.trim() : '';
      const priceVal = priceInput ? priceInput.value.trim() : '';
      const stockVal = stockInput ? stockInput.value.trim() : '';
      const status = statusInput ? statusInput.value : 'active';
      const description = descInput ? descInput.value.trim() : '';
      const productCode = productCodeInput ? productCodeInput.value.trim() : '';
      const imageUrl = imageUrlInput ? imageUrlInput.value.trim() : '';

      // Validation
      if (!name) {
        showAdminMessage('Please enter a product name.', 'error');
        if (nameInput) nameInput.focus();
        return;
      }
      const price = parseFloat(priceVal);
      if (isNaN(price) || price <= 0) {
        showAdminMessage('Please enter a valid price in INR (must be greater than 0).', 'error');
        if (priceInput) priceInput.focus();
        return;
      }
      const stock = parseInt(stockVal, 10);
      if (isNaN(stock) || stock < 0) {
        showAdminMessage('Please enter a valid stock quantity (must be 0 or greater).', 'error');
        if (stockInput) stockInput.focus();
        return;
      }
      if (imageUrl && imageUrl.length > 500) {
        showAdminMessage('Product image URL must not exceed 500 characters.', 'error');
        if (imageUrlInput) imageUrlInput.focus();
        return;
      }

      // Strict schema payload (extra='forbid')
      const payload = {
        name: name,
        price: price,
        stock: stock,
        is_active: status === 'active'
      };
      if (description) {
        payload.description = description;
      }
      if (imageUrl) {
        payload.image_url = imageUrl;
      }
      if (productCode) {
        payload.product_code = productCode;
      }

      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Saving...';
      }

      try {
        if (editId) {
          await window.ShopEasyProducts.adminUpdate(editId, payload);
          showAdminMessage('Product updated successfully! Redirecting to catalog...', 'success');
        } else {
          await window.ShopEasyProducts.adminCreate(payload);
          showAdminMessage('Product created successfully! Redirecting to catalog...', 'success');
        }
        setTimeout(() => {
          window.location.href = 'products.html';
        }, 800);
      } catch (err) {
        showAdminMessage(err.detail || err.message || 'Failed to save product.', 'error');
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Save Product';
        }
      }
    });
  }
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// 7. Admin Orders Fulfillment Page
// ---------------------------------------------------------------------------
async function initAdminOrdersPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  const tbody = document.getElementById('admin-orders-table-body');
  if (!tbody) return;

  try {
    let orders = [];
    if (window.ShopEasyOrders && window.ShopEasyOrders.adminList) {
      const res = await window.ShopEasyOrders.adminList({ page: 1, page_size: 50 });
      if (res && Array.isArray(res.items)) {
        orders = res.items;
      }
    }

    if (orders.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" style="text-align:center;padding:var(--space-8);color:var(--color-muted);">
            No orders recorded yet.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = orders.map(o => {
      const dateStr = o.created_at ? new Date(o.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A';
      const badgeClass = o.order_status === 'confirmed' ? 'badge-success' : 'badge-primary';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">${escapeHtml(o.order_number)}</strong></td>
          <td>${escapeHtml(o.customer_name)}</td>
          <td>${escapeHtml(dateStr)}</td>
          <td><strong>${formatCurrency(Number(o.total_amount))}</strong></td>
          <td><span class="badge ${badgeClass}">${escapeHtml(o.order_status)}</span></td>
          <td><button type="button" class="table-action-btn" onclick="alert('Order: ' + escapeHtml('${escapeHtml(o.order_number)}'))">Inspect</button></td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load orders:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align:center;padding:var(--space-8);color:var(--color-danger);">
          Failed to load orders from backend.
        </td>
      </tr>
    `;
  }
}

// ---------------------------------------------------------------------------
// 8. Admin Customers Directory Page
// ---------------------------------------------------------------------------
async function initAdminCustomersPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  const tbody = document.getElementById('admin-customers-table-body');
  if (!tbody) return;

  try {
    let customers = [];
    if (window.ShopEasyAuth && window.ShopEasyAuth.adminListCustomers) {
      const res = await window.ShopEasyAuth.adminListCustomers({ page: 1, page_size: 50 });
      if (res && Array.isArray(res.items)) {
        customers = res.items;
      }
    }

    if (customers.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align:center;padding:var(--space-8);color:var(--color-muted);">
            No customers registered yet.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = customers.map(c => {
      const dateStr = c.created_at ? new Date(c.created_at).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' }) : 'N/A';
      return `
        <tr>
          <td>
            <div style="font-weight:600;">${escapeHtml(c.full_name)}</div>
            ${c.referral_code ? `<span style="font-size:11px;color:var(--color-muted);">Code: ${escapeHtml(c.referral_code)}</span>` : ''}
          </td>
          <td>+91 ${escapeHtml(c.phone)}</td>
          <td>${escapeHtml(dateStr)}</td>
          <td><strong>${c.total_orders} orders (${formatCurrency(Number(c.total_spent))})</strong></td>
          <td><span class="badge ${c.is_active ? 'badge-success' : 'badge-danger'}">${c.is_active ? 'Active Customer' : 'Inactive'}</span></td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    console.error('Failed to load customers:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align:center;padding:var(--space-8);color:var(--color-danger);">
          Failed to load customers from backend.
        </td>
      </tr>
    `;
  }
}

// Helpers
// ---------------------------------------------------------------------------
function formatCurrency(amount) {
  if (typeof amount !== 'number') return '₹0';
  return '₹' + amount.toLocaleString('en-IN');
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---------------------------------------------------------------------------
// Global Window Exports
// ---------------------------------------------------------------------------
window.initAdminShell = initAdminShell;
window.initAdminDashboard = initAdminDashboard;
window.initAdminOrdersPage = initAdminOrdersPage;
window.initAdminCustomersPage = initAdminCustomersPage;
window.initAdminProductsPage = initAdminProductsPage;
window.initProductForm = initProductForm;
window.initAdminLogin = initAdminLogin;
window.adminLogout = adminLogout;
window.deleteAdminProduct = deleteAdminProduct;
window.loadAdminProducts = loadAdminProducts;
window.renderAdminProductsTable = renderAdminProductsTable;
window.getAdminProductById = getAdminProductById;
window.getAdminProducts = getAdminProducts;
window.formatCurrency = formatCurrency;
window.escapeHtml = escapeHtml;
