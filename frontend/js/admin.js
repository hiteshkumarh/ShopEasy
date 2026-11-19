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
    const raw = sessionStorage.getItem(ADMIN_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function adminLogout(redirectUrl = 'login.html') {
  try {
    sessionStorage.removeItem(ADMIN_SESSION_KEY);
    localStorage.removeItem(ADMIN_SESSION_KEY);
    sessionStorage.removeItem('shopeasy_admin_token');
    localStorage.removeItem('shopeasy_admin_token');
    sessionStorage.removeItem('shopeasy_admin_user');
    localStorage.removeItem('shopeasy_admin_user');
    if (window.ShopEasyAPI && typeof window.ShopEasyAPI.clearAdminToken === 'function') {
      window.ShopEasyAPI.clearAdminToken();
    }
    const paths = ['/', '/admin', '/admin/', ''];
    paths.forEach(p => {
      const pathPart = p ? `; path=${p}` : '';
      document.cookie = `shopeasy_admin_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT${pathPart}; SameSite=Lax`;
      document.cookie = `shopeasy_admin_user=; expires=Thu, 01 Jan 1970 00:00:00 GMT${pathPart}; SameSite=Lax`;
      document.cookie = `shopeasy_admin_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT${pathPart}`;
      document.cookie = `shopeasy_admin_user=; expires=Thu, 01 Jan 1970 00:00:00 GMT${pathPart}`;
    });
  } catch (e) {}

  if (window.ShopEasyAuth && typeof window.ShopEasyAuth.adminLogout === 'function') {
    window.ShopEasyAuth.adminLogout(redirectUrl);
  } else {
    window.location.href = redirectUrl;
  }
}

// ---------------------------------------------------------------------------
// Shared Admin Navigation Menu
// ---------------------------------------------------------------------------
const ADMIN_NAV_ITEMS = [
  {
    href: 'dashboard.html',
    label: 'Dashboard',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="9"></rect><rect x="14" y="3" width="7" height="5"></rect><rect x="14" y="12" width="7" height="9"></rect><rect x="3" y="16" width="7" height="5"></rect></svg>'
  },
  {
    href: 'plan-a.html',
    label: 'Plan A - Arya Business Partner Programme',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><polyline points="17 11 19 13 23 9"></polyline></svg>'
  },
  {
    href: 'plan-b.html',
    label: 'Plan B - Arya Generation Growth Programme',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7" r="4"></circle><polyline points="17 11 19 13 23 9"></polyline></svg>'
  },
  {
    href: 'withdrawals.html',
    label: 'Withdrawals',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"></rect><line x1="2" y1="10" x2="22" y2="10"></line></svg>'
  },
  {
    href: 'reports.html',
    label: 'Reports & Downloads',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>'
  },
  {
    href: 'settings.html',
    label: 'Financial Settings',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>'
  },
  {
    href: 'orders.html',
    label: 'Orders',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path><line x1="3" y1="6" x2="21" y2="6"></line><path d="M16 10a4 4 0 0 1-8 0"></path></svg>'
  },
  {
    href: 'products.html',
    label: 'Products',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>'
  },
  {
    href: 'customers.html',
    label: 'Customers',
    iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'
  }
];

function renderSharedAdminSidebar(sidebarEl) {
  if (!sidebarEl) return;

  const rawPath = window.location.pathname.split('/').pop().split('?')[0] || 'dashboard.html';
  const activeHref = (rawPath === 'product-form.html') ? 'products.html' : rawPath;

  const navHtml = ADMIN_NAV_ITEMS.map(item => {
    // Plan A Cashback & Queues retains neutral styling matching Plan B
    const isActive = (item.href === activeHref && item.href !== 'plan-a.html');
    return `
        <a href="${item.href}" class="admin-nav-item ${isActive ? 'active' : ''}">
          ${item.iconSvg}
          <span>${item.label}</span>
        </a>`.trim();
  }).join('\n        ');

  sidebarEl.innerHTML = `
      <div class="admin-sidebar-header">
        <a href="dashboard.html" class="admin-brand">
          <span class="brand-logo-mark" aria-hidden="true" style="width:28px;height:28px;">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;">
              <polygon points="12 2 2 22 22 22"></polygon>
              <line x1="12" y1="11" x2="12" y2="17"></line>
            </svg>
          </span>
          <span>Arya Global Digital</span>
        </a>
        <span class="admin-badge">Admin</span>
      </div>

      <nav class="admin-sidebar-nav">
        ${navHtml}
      </nav>

      <div class="admin-sidebar-footer">

        <a href="../index.html" class="admin-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
          <span>Return to Store</span>
        </a>

        <button type="button" class="admin-nav-item" onclick="adminLogout()" style="width:100%;text-align:left;background:none;border:none;cursor:pointer;">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <polyline points="16 17 21 12 16 7"></polyline>
            <line x1="21" y1="12" x2="9" y2="12"></line>
          </svg>
          <span>Logout</span>
        </button>
      </div>
  `;
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

  // Ensure sidebar is rendered and synchronized across all admin pages
  const sidebar = document.querySelector('.admin-sidebar');
  if (sidebar) {
    renderSharedAdminSidebar(sidebar);
  }

  // Highlight active sidebar navigation link (fallback / verification)
  const rawPath = window.location.pathname.split('/').pop().split('?')[0] || 'dashboard.html';
  const activeHref = (rawPath === 'product-form.html') ? 'products.html' : rawPath;
  const navItems = document.querySelectorAll('.admin-nav-item');
  navItems.forEach(item => {
    const href = item.getAttribute('href');
    if (!href) return;
    const itemPath = href.split('/').pop().split('?')[0];
    if (itemPath === activeHref && itemPath !== 'plan-a.html') {
      item.classList.add('active');
    } else {
      item.classList.remove('active');
    }
  });

  // Hydrate admin user chip with authenticated admin name if available
  const userChipName = document.querySelector('.admin-user-chip span:last-child');
  if (userChipName && admin && admin.full_name) {
    userChipName.textContent = admin.full_name;
  }

  // Mobile sidebar drawer toggle
  const mobileToggle = document.querySelector('.admin-mobile-toggle');
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

  // Wire Unified Search icon click listener (Section 3)
  const searchIcons = document.querySelectorAll('.admin-search-icon');
  searchIcons.forEach(icon => {
    icon.style.cursor = 'pointer';
    icon.addEventListener('click', () => {
      const input = document.getElementById('topbar-search-input');
      if (input && typeof window.executeUnifiedSearch === 'function') {
        window.executeUnifiedSearch(input.value);
      }
    });
  });

  // Load unread notifications count if bell badge exists
  const notifBadge = document.getElementById('admin-notif-count');
  if (notifBadge && window.ShopEasyAdmin && window.ShopEasyAdmin.getNotifications) {
    window.ShopEasyAdmin.getNotifications({ is_read: false, page: 1, page_size: 5 })
      .then(res => {
        const count = typeof res?.unread_count === 'number' ? res.unread_count : (typeof res?.total === 'number' ? res.total : (Array.isArray(res) ? res.length : 0));
        if (count > 0) {
          notifBadge.textContent = count;
          notifBadge.style.display = 'inline-block';
        } else {
          notifBadge.style.display = 'none';
        }
      })
      .catch(() => {});
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
  // If already authenticated as administrator in the active session, redirect to dashboard
  const activeToken = window.ShopEasyAPI ? window.ShopEasyAPI.getAdminToken() : null;
  if (activeToken && window.redirectIfAdminAuthenticated) {
    window.redirectIfAdminAuthenticated('dashboard.html');
    return;
  }

  // Ensure clean initial state for manual login
  clearAdminMessage();

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

  if (pwdPhoneInput && !pwdPhoneInput.value) {
    pwdPhoneInput.value = '';
  }
  if (pwdInput) {
    pwdInput.value = '';
  }

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
  let totalItemsSold = 0;
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
        totalItemsSold = Number(stats.total_items_sold) || 0;
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
  const elOrdersHint = document.getElementById('stat-total-orders-hint');
  const elCustomers = document.getElementById('stat-total-customers');
  const elRevenue = document.getElementById('stat-total-revenue');

  if (elProducts) elProducts.textContent = totalProducts;
  if (elOrders) elOrders.textContent = totalOrders;
  if (elOrdersHint) {
    elOrdersHint.textContent = `${totalOrders} Confirmed (${totalItemsSold} Units Sold)`;
  }
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
window._adminOrdersCache = [];

function renderAdminOrdersTable(orders) {
  const tbody = document.getElementById('admin-orders-table-body');
  if (!tbody) return;

  if (!orders || orders.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align:center;padding:var(--space-8);color:var(--color-muted);">
          No matching orders found.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = orders.map(o => {
    const dateStr = o.created_at ? new Date(o.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A';
    const badgeClass = o.order_status === 'confirmed' ? 'badge-success' : 'badge-primary';
    
    // Dedicated Company Billing ID
    const billingIdStr = (o.billing_id || (Array.isArray(o.billing_ids) && o.billing_ids.length > 0 ? o.billing_ids.join(', ') : '') || '').trim();
    const billingHtml = billingIdStr
      ? `<span class="billing-id-badge">${escapeHtml(billingIdStr)}</span>`
      : `<span class="badge badge-muted" style="color:var(--color-muted);font-size:11px;font-style:italic;">Not Generated</span>`;

    return `
      <tr>
        <td><strong style="font-family:var(--font-mono);">${escapeHtml(o.order_number)}</strong></td>
        <td>${billingHtml}</td>
        <td>
          <div style="font-weight:600;">${escapeHtml(o.customer_name)}</div>
          <div style="font-size:11px;color:var(--color-muted);">${escapeHtml(o.customer_phone || '')}</div>
        </td>
        <td>${escapeHtml(dateStr)}</td>
        <td><strong>${formatCurrency(Number(o.total_amount))}</strong></td>
        <td><span class="badge ${badgeClass}">${escapeHtml(o.order_status)}</span></td>
        <td><button type="button" class="table-action-btn" onclick="openOrderInspectModal('${escapeHtml(o.order_number)}')">Inspect</button></td>
      </tr>
    `;
  }).join('');
}

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

    window._adminOrdersCache = orders;
    renderAdminOrdersTable(orders);
  } catch (err) {
    console.error('Failed to load orders:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align:center;padding:var(--space-8);color:var(--color-danger);">
          Failed to load orders from backend.
        </td>
      </tr>
    `;
  }
}

function filterAdminOrdersTable(query) {
  const cleanQ = (query || '').trim().toLowerCase();
  if (!window._adminOrdersCache) return;

  if (!cleanQ) {
    renderAdminOrdersTable(window._adminOrdersCache);
    return;
  }

  const filtered = window._adminOrdersCache.filter(o => {
    const orderNum = (o.order_number || '').toLowerCase();
    const orderId = String(o.id || '');
    const billingId = (o.billing_id || '').toLowerCase();
    const allBids = Array.isArray(o.billing_ids) ? o.billing_ids.join(' ').toLowerCase() : '';
    const custName = (o.customer_name || '').toLowerCase();
    const custPhone = (o.customer_phone || '').toLowerCase();

    return (
      orderNum.includes(cleanQ) ||
      orderId === cleanQ ||
      billingId.includes(cleanQ) ||
      allBids.includes(cleanQ) ||
      custName.includes(cleanQ) ||
      custPhone.includes(cleanQ)
    );
  });

  renderAdminOrdersTable(filtered);
}

async function executeOrdersSearch(query) {
  const cleanQ = (query || '').trim();
  if (!cleanQ) {
    if (window._adminOrdersCache) renderAdminOrdersTable(window._adminOrdersCache);
    return;
  }

  // Filter client cache first
  filterAdminOrdersTable(cleanQ);

  // Also query backend /admin/orders?search=...
  try {
    if (window.ShopEasyOrders && window.ShopEasyOrders.adminList) {
      const res = await window.ShopEasyOrders.adminList({ search: cleanQ, page: 1, page_size: 50 });
      if (res && Array.isArray(res.items) && res.items.length > 0) {
        window._adminOrdersCache = res.items;
        renderAdminOrdersTable(res.items);
        return;
      }
    }
  } catch (e) {
    console.warn('Backend order search failed, falling back to local/unified search:', e);
  }

  // If still zero results, invoke executeUnifiedSearch
  const tbody = document.getElementById('admin-orders-table-body');
  if (tbody && tbody.innerText.includes('No matching orders found')) {
    executeUnifiedSearch(cleanQ);
  }
}

function openOrderInspectModal(orderNumber) {
  const modal = document.getElementById('order-inspect-modal');
  const container = document.getElementById('order-inspect-content');
  if (!modal || !container) return;

  const order = (window._adminOrdersCache || []).find(o => o.order_number === orderNumber) || null;
  if (!order) {
    alert(`Order details for "${orderNumber}" not found in current view.`);
    return;
  }

  const bids = Array.isArray(order.billing_ids) && order.billing_ids.length > 0
    ? order.billing_ids
    : (order.billing_id ? [order.billing_id] : []);

  const billingBadge = bids.length > 0
    ? `<div style="display:flex;flex-wrap:wrap;gap:4px;max-height:88px;overflow-y:auto;padding:2px 0;">${bids.map(b => `<span class="billing-id-badge" style="font-size:11px;padding:2px 6px;line-height:1.2;white-space:nowrap;">${escapeHtml(b)}</span>`).join('')}</div>`
    : `<span class="badge badge-muted">Not Generated (Payment Pending/Failed)</span>`;

  const dateStr = order.created_at ? new Date(order.created_at).toLocaleString('en-IN') : 'N/A';
  const badgeClass = order.order_status === 'confirmed' ? 'badge-success' : 'badge-primary';

  const itemsHtml = (order.items || []).map((item, idx) => `
    <tr>
      <td>${idx + 1}</td>
      <td><strong>${escapeHtml(item.product_name)}</strong></td>
      <td style="text-align:center;">${item.quantity}</td>
      <td style="text-align:right;">${formatCurrency(Number(item.unit_price))}</td>
      <td style="text-align:right;"><strong>${formatCurrency(Number(item.line_total))}</strong></td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:var(--space-4);background:#F8FAFC;border:1px solid #CBD5E1;border-radius:var(--radius-md);padding:var(--space-4);margin-bottom:var(--space-4);">
      <div>
        <div style="font-size:11px;color:var(--color-muted);text-transform:uppercase;font-weight:600;">Order Identifier</div>
        <div style="font-size:14px;font-weight:700;font-family:var(--font-mono);color:#1E3A8A;">${escapeHtml(order.order_number)}</div>
        <div style="font-size:11px;color:var(--color-muted);margin-top:2px;">Order ID #${order.id}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--color-muted);text-transform:uppercase;font-weight:600;">Company Billing ID (${bids.length})</div>
        <div style="margin-top:2px;">${billingBadge}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--color-muted);text-transform:uppercase;font-weight:600;">Customer Information</div>
        <div style="font-weight:600;font-size:13px;">${escapeHtml(order.customer_name)}</div>
        <div style="font-size:12px;color:var(--color-muted);">${escapeHtml(order.customer_phone)}</div>
      </div>
      <div>
        <div style="font-size:11px;color:var(--color-muted);text-transform:uppercase;font-weight:600;">Order Status &amp; Date</div>
        <div>
          <span class="badge ${badgeClass}">${escapeHtml(order.order_status)}</span>
          <span class="badge badge-subtle" style="margin-left:4px;">${escapeHtml(order.payment_status || 'N/A')}</span>
        </div>
        <div style="font-size:11px;color:var(--color-muted);margin-top:3px;">${escapeHtml(dateStr)}</div>
      </div>
    </div>

    <div style="margin-bottom:var(--space-2);font-weight:600;font-size:13px;">Purchased Items &amp; Allocation Snapshot</div>
    <div style="max-height:220px;overflow-y:auto;overflow-x:auto;border:1px solid #E2E8F0;border-radius:var(--radius-md);">
      <table class="admin-table" style="margin:0;font-size:12px;">
        <thead>
          <tr>
            <th style="width:30px;">#</th>
            <th>Product</th>
            <th style="text-align:center;">Qty</th>
            <th style="text-align:right;">Unit Price</th>
            <th style="text-align:right;">Line Total</th>
          </tr>
        </thead>
        <tbody>
          ${itemsHtml || '<tr><td colspan="5" style="text-align:center;padding:12px;color:var(--color-muted);">No line items snapshot recorded</td></tr>'}
        </tbody>
      </table>
    </div>

    <div style="display:flex;justify-content:flex-end;margin-top:var(--space-3);font-size:14px;">
      <div>Total Amount: <strong style="color:var(--color-primary);font-size:16px;">${formatCurrency(Number(order.total_amount))}</strong></div>
    </div>
  `;

  document.body.style.overflow = 'hidden';
  modal.style.display = 'flex';
}

function closeOrderInspectModal() {
  const modal = document.getElementById('order-inspect-modal');
  if (modal) modal.style.display = 'none';
  document.body.style.overflow = '';
}

// Close order inspect modal on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const modal = document.getElementById('order-inspect-modal');
    if (modal && modal.style.display === 'flex') {
      closeOrderInspectModal();
    }
  }
});

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
// 9. WP-12 Step 6: Unified Search Controller
// ---------------------------------------------------------------------------
async function executeUnifiedSearch(query) {
  const cleanQ = (query || '').trim();
  const modal = document.getElementById('unified-search-modal');
  const loadingEl = document.getElementById('unified-search-loading');
  const resultsContainer = document.getElementById('unified-search-results-container');

  if (!modal || !resultsContainer) return;
  modal.style.display = 'flex';

  if (!cleanQ) {
    if (loadingEl) loadingEl.style.display = 'none';
    resultsContainer.innerHTML = `
      <div style="padding:var(--space-6);text-align:center;color:var(--color-muted);">
        Please enter an exact Billing ID or Order ID/Number to search.
      </div>
    `;
    return;
  }

  if (loadingEl) loadingEl.style.display = 'block';
  resultsContainer.innerHTML = '';

  try {
    const res = await window.ShopEasyAdmin.search(cleanQ);
    if (loadingEl) loadingEl.style.display = 'none';

    if (!res || !Array.isArray(res.results) || res.results.length === 0) {
      resultsContainer.innerHTML = `
        <div style="padding:var(--space-6);text-align:center;color:var(--color-muted);">
          No exact matches found for <strong>"${escapeHtml(cleanQ)}"</strong> across Plan A or Plan B.
          <p style="font-size:var(--text-xs);margin-top:var(--space-2);">
            Per exact-match rule OR-13: searches require complete identifiers.
          </p>
        </div>
      `;
      return;
    }

    resultsContainer.innerHTML = res.results.map(item => {
      const progBadgeClass = item.programme === 'PLAN_A' ? 'badge-plan-a' : 'badge-plan-b';
      const recordType = escapeHtml(item.record_type || 'RECORD');
      const dateStr = item.created_at ? new Date(item.created_at).toLocaleString('en-IN') : 'N/A';
      
      let metaHtml = '';
      if (item.record_type === 'BILLING_ID') {
        const meta = item.metadata || {};
        metaHtml = `
          <div style="font-size:var(--text-xs);margin-top:var(--space-2);line-height:1.6;color:var(--color-muted);">
            <div><strong>Associated Order:</strong> #${escapeHtml(meta.order_number || item.order_number || 'N/A')}</div>
            <div><strong>Product:</strong> ${escapeHtml(meta.product_name || 'N/A')} (Unit #${item.metadata?.unit_index !== undefined ? item.metadata.unit_index + 1 : '1'})</div>
            ${meta.cycle_id ? `<div><strong>Active Cycle:</strong> #${meta.cycle_id}</div>` : ''}
            ${meta.contributions !== undefined ? `<div><strong>Completed Contributions:</strong> ${meta.contributions} / 16</div>` : ''}
          </div>
        `;
      } else if (item.record_type === 'ORDER') {
        const meta = item.metadata || {};
        const bids = Array.isArray(meta.billing_ids) ? meta.billing_ids.join(', ') : 'None';
        metaHtml = `
          <div style="font-size:var(--text-xs);margin-top:var(--space-2);line-height:1.6;color:var(--color-muted);">
            <div><strong>Total Amount:</strong> ${formatCurrency(Number(item.total_amount) || 0)}</div>
            <div><strong>Payment Status:</strong> ${escapeHtml(meta.payment_status || 'N/A')} &bull; <strong>Fulfilled:</strong> ${meta.is_fulfilled ? 'Yes' : 'No'}</div>
            <div><strong>Generated Billing IDs:</strong> <span style="font-family:var(--font-mono);">${escapeHtml(bids)}</span></div>
          </div>
        `;
      }

      return `
        <div style="background:#F8FAFC;border:1px solid #CBD5E1;border-radius:var(--radius-md);padding:var(--space-4);margin-bottom:var(--space-3);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2);">
            <div>
              <span class="badge ${progBadgeClass}" style="margin-right:6px;">${escapeHtml(item.programme)}</span>
              <span class="badge badge-muted">${recordType}</span>
            </div>
            <span class="badge ${item.status === 'ALLOCATED' || item.status === 'confirmed' ? 'badge-success' : 'badge-primary'}">${escapeHtml(item.status || 'Active')}</span>
          </div>
          <div style="font-size:var(--text-md);font-weight:700;font-family:var(--font-mono);color:#1E3A8A;margin-bottom:var(--space-1);">
            ${escapeHtml(item.identifier || cleanQ)}
          </div>
          <div style="font-size:var(--text-xs);color:var(--color-muted);">
            Customer: <strong>${escapeHtml(item.customer_name || 'Customer #' + item.customer_id)}</strong> &bull; Date: ${escapeHtml(dateStr)}
          </div>
          ${metaHtml}
        </div>
      `;
    }).join('');

  } catch (err) {
    if (loadingEl) loadingEl.style.display = 'none';
    resultsContainer.innerHTML = `
      <div style="padding:var(--space-6);text-align:center;color:var(--color-danger);">
        ${escapeHtml(err.detail || err.message || 'Unified search failed.')}
      </div>
    `;
  }
}

function closeUnifiedSearchModal() {
  const modal = document.getElementById('unified-search-modal');
  if (modal) modal.style.display = 'none';
}

function clearUnifiedSearch() {
  const input = document.getElementById('topbar-search-input');
  if (input) input.value = '';
  closeUnifiedSearchModal();
}

// ---------------------------------------------------------------------------
// 9A. Dedicated Plan A Search Controller (Section 5.A)
// ---------------------------------------------------------------------------
async function executePlanASearch() {
  const input = document.getElementById('plan-a-search-input');
  const clearBtn = document.getElementById('plan-a-search-clear-btn');
  const loadingEl = document.getElementById('plan-a-search-loading');
  const feedbackEl = document.getElementById('plan-a-search-feedback');
  const resultsEl = document.getElementById('plan-a-search-results');

  const query = (input ? input.value : '').trim();

  if (clearBtn) {
    clearBtn.style.display = query ? 'block' : 'none';
  }

  if (!query) {
    if (feedbackEl) {
      feedbackEl.style.display = 'block';
      feedbackEl.innerHTML = `
        <div style="padding:10px 14px;background:#FEF3C7;color:#92400E;border-radius:var(--radius-sm);font-size:var(--text-xs);">
          Please enter a Customer Name, Mobile Number, Customer ID, Billing ID, or Queue ID to search.
        </div>
      `;
    }
    if (resultsEl) resultsEl.style.display = 'none';
    return;
  }

  if (loadingEl) loadingEl.style.display = 'block';
  if (feedbackEl) feedbackEl.style.display = 'none';
  if (resultsEl) {
    resultsEl.style.display = 'none';
    resultsEl.innerHTML = '';
  }

  try {
    const res = await window.ShopEasyAdmin.searchPlanA(query);
    if (loadingEl) loadingEl.style.display = 'none';

    if (!res || !Array.isArray(res.results) || res.results.length === 0) {
      if (feedbackEl) {
        feedbackEl.style.display = 'block';
        feedbackEl.innerHTML = `
          <div style="padding:12px 16px;background:#F1F5F9;color:var(--color-muted);border-radius:var(--radius-sm);font-size:var(--text-sm);text-align:center;">
            No Plan A records found matching <strong>"${escapeHtml(query)}"</strong>.
          </div>
        `;
      }
      return;
    }

    if (resultsEl) {
      resultsEl.style.display = 'block';
      resultsEl.innerHTML = `
        <div style="margin-bottom:8px;font-size:var(--text-xs);font-weight:600;color:var(--color-muted);">
          Found ${res.total} Plan A record${res.total === 1 ? '' : 's'}:
        </div>
        <div style="display:grid;gap:var(--space-3);">
          ${res.results.map(item => {
            const dt = item.created_at ? new Date(item.created_at).toLocaleString('en-IN') : 'N/A';
            const details = item.details || {};
            let detailRows = '';
            if (item.record_type === 'CUSTOMER') {
              detailRows = `
                <div><strong>Customer ID:</strong> #${item.customer_id} &bull; <strong>Phone:</strong> ${escapeHtml(item.phone || 'N/A')}</div>
                <div><strong>Cashback Queue:</strong> ${details.has_queue ? 'Active (Queue #' + details.queue_id + ')' : 'None'}</div>
                <div><strong>Plan A Purchased Billing IDs:</strong> ${details.billing_ids_count || 0}</div>
                ${details.referral_code ? `<div><strong>Referral Code:</strong> <span style="font-family:var(--font-mono);">${escapeHtml(details.referral_code)}</span></div>` : ''}
              `;
            } else if (item.record_type === 'BILLING_ID') {
              detailRows = `
                <div><strong>Billing ID:</strong> <span style="font-family:var(--font-mono);font-weight:700;">${escapeHtml(item.identifier)}</span></div>
                <div><strong>Unit #${details.unit_index !== undefined ? details.unit_index + 1 : 1}</strong> &bull; Order #${details.order_id || 'N/A'}</div>
                <div><strong>Owner:</strong> ${escapeHtml(item.customer_name || 'Customer #' + item.customer_id)}</div>
              `;
            } else if (item.record_type === 'QUEUE') {
              detailRows = `
                <div><strong>Queue ID:</strong> #${item.entity_id} &bull; <strong>Root Customer:</strong> ${escapeHtml(item.customer_name || 'Customer #' + item.customer_id)}</div>
                <div><strong>Total Queue Entries:</strong> ${details.total_entries || 0} &bull; <strong>Active Cycle:</strong> #${details.active_cycle_id || 'N/A'}</div>
              `;
            }

            return `
              <div style="background:#F8FAFC;border:1px solid #CBD5E1;border-radius:var(--radius-sm);padding:12px 16px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                  <span class="badge badge-plan-a">${escapeHtml(item.record_type)}</span>
                  <span class="badge ${item.status === 'ACTIVE' || item.status === 'ALLOCATED' ? 'badge-success' : 'badge-primary'}">${escapeHtml(item.status || 'Active')}</span>
                </div>
                <div style="font-size:var(--text-md);font-weight:700;color:#1E3A8A;margin-bottom:4px;">
                  ${escapeHtml(item.identifier)}
                </div>
                <div style="font-size:var(--text-xs);color:var(--color-muted);line-height:1.6;">
                  ${detailRows}
                  <div><small>Created: ${escapeHtml(dt)}</small></div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }
  } catch (err) {
    if (loadingEl) loadingEl.style.display = 'none';
    if (feedbackEl) {
      feedbackEl.style.display = 'block';
      feedbackEl.innerHTML = `
        <div style="padding:10px 14px;background:#FEE2E2;color:#991B1B;border-radius:var(--radius-sm);font-size:var(--text-xs);">
          ${escapeHtml(err.detail || err.message || 'Plan A search failed.')}
        </div>
      `;
    }
  }
}

function clearPlanASearch() {
  const input = document.getElementById('plan-a-search-input');
  const clearBtn = document.getElementById('plan-a-search-clear-btn');
  const loadingEl = document.getElementById('plan-a-search-loading');
  const feedbackEl = document.getElementById('plan-a-search-feedback');
  const resultsEl = document.getElementById('plan-a-search-results');

  if (input) input.value = '';
  if (clearBtn) clearBtn.style.display = 'none';
  if (loadingEl) loadingEl.style.display = 'none';
  if (feedbackEl) {
    feedbackEl.innerHTML = '';
    feedbackEl.style.display = 'none';
  }
  if (resultsEl) {
    resultsEl.innerHTML = '';
    resultsEl.style.display = 'none';
  }
}

// ---------------------------------------------------------------------------
// 9B. Dedicated Plan B Search Controller (Section 5.B)
// ---------------------------------------------------------------------------
async function executePlanBSearch() {
  const input = document.getElementById('plan-b-search-input');
  const clearBtn = document.getElementById('plan-b-search-clear-btn');
  const loadingEl = document.getElementById('plan-b-search-loading');
  const feedbackEl = document.getElementById('plan-b-search-feedback');
  const resultsEl = document.getElementById('plan-b-search-results');

  const query = (input ? input.value : '').trim();

  if (clearBtn) {
    clearBtn.style.display = query ? 'block' : 'none';
  }

  if (!query) {
    if (feedbackEl) {
      feedbackEl.style.display = 'block';
      feedbackEl.innerHTML = `
        <div style="padding:10px 14px;background:#FEF3C7;color:#92400E;border-radius:var(--radius-sm);font-size:var(--text-xs);">
          Please enter a Distributor Name, Mobile Number, Distributor ID, Sponsor ID, or Ledger ID to search.
        </div>
      `;
    }
    if (resultsEl) resultsEl.style.display = 'none';
    return;
  }

  if (loadingEl) loadingEl.style.display = 'block';
  if (feedbackEl) feedbackEl.style.display = 'none';
  if (resultsEl) {
    resultsEl.style.display = 'none';
    resultsEl.innerHTML = '';
  }

  try {
    const res = await window.ShopEasyAdmin.searchPlanB(query);
    if (loadingEl) loadingEl.style.display = 'none';

    if (!res || !Array.isArray(res.results) || res.results.length === 0) {
      if (feedbackEl) {
        feedbackEl.style.display = 'block';
        feedbackEl.innerHTML = `
          <div style="padding:12px 16px;background:#F1F5F9;color:var(--color-muted);border-radius:var(--radius-sm);font-size:var(--text-sm);text-align:center;">
            No Plan B records found matching <strong>"${escapeHtml(query)}"</strong>.
          </div>
        `;
      }
      return;
    }

    if (resultsEl) {
      resultsEl.style.display = 'block';
      resultsEl.innerHTML = `
        <div style="margin-bottom:8px;font-size:var(--text-xs);font-weight:600;color:var(--color-muted);">
          Found ${res.total} Plan B record${res.total === 1 ? '' : 's'}:
        </div>
        <div style="display:grid;gap:var(--space-3);">
          ${res.results.map(item => {
            const dt = item.created_at ? new Date(item.created_at).toLocaleString('en-IN') : 'N/A';
            const details = item.details || {};
            let detailRows = '';
            if (item.record_type === 'DISTRIBUTOR') {
              detailRows = `
                <div><strong>Distributor ID:</strong> #${item.distributor_id} &bull; <strong>Phone:</strong> ${escapeHtml(item.phone || 'N/A')}</div>
                <div><strong>Sponsor ID:</strong> #${item.sponsor_id || 'None (Direct Root)'}</div>
                <div><strong>Direct Referees:</strong> ${details.direct_referees_count || 0}</div>
                <div><strong>Wallet Balance:</strong> ${formatCurrency(details.wallet_balance || 0)}</div>
                ${details.referral_code ? `<div><strong>Referral Code:</strong> <span style="font-family:var(--font-mono);">${escapeHtml(details.referral_code)}</span></div>` : ''}
              `;
            } else if (item.record_type === 'LEDGER') {
              detailRows = `
                <div><strong>Transaction ID:</strong> #${details.transaction_id || item.entity_id} &bull; <strong>Type:</strong> ${escapeHtml(details.transaction_type || 'N/A')}</div>
                <div><strong>Amount:</strong> ${formatCurrency(Number(item.amount) || 0)}</div>
                <div><strong>Distributor:</strong> ${escapeHtml(item.distributor_name || 'Distributor #' + item.distributor_id)}</div>
                <div><strong>Reference:</strong> ${escapeHtml(details.reference_id || 'N/A')}</div>
              `;
            } else if (item.record_type === 'COMMISSION') {
              detailRows = `
                <div><strong>Commission ID:</strong> #${details.commission_id || item.entity_id} &bull; <strong>Type:</strong> ${escapeHtml(details.commission_type || 'N/A')}</div>
                <div><strong>Net Amount:</strong> ${formatCurrency(Number(item.amount) || 0)} &bull; <strong>Gross:</strong> ${formatCurrency(details.gross_amount || 0)} (TDS: ${formatCurrency(details.tds_amount || 0)})</div>
                <div><strong>Distributor:</strong> ${escapeHtml(item.distributor_name || 'Distributor #' + item.distributor_id)}</div>
                <div><strong>Order ID:</strong> #${details.order_id || 'N/A'}</div>
              `;
            }

            return `
              <div style="background:#F8FAFC;border:1px solid #CBD5E1;border-radius:var(--radius-sm);padding:12px 16px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                  <span class="badge badge-plan-b">${escapeHtml(item.record_type)}</span>
                  <span class="badge ${item.status === 'ACTIVE' || item.status === 'COMPLETED' || item.status === 'CREDITED' ? 'badge-success' : 'badge-primary'}">${escapeHtml(item.status || 'Active')}</span>
                </div>
                <div style="font-size:var(--text-md);font-weight:700;color:#92400E;margin-bottom:4px;">
                  ${escapeHtml(item.identifier)}
                </div>
                <div style="font-size:var(--text-xs);color:var(--color-muted);line-height:1.6;">
                  ${detailRows}
                  <div><small>Created: ${escapeHtml(dt)}</small></div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }
  } catch (err) {
    if (loadingEl) loadingEl.style.display = 'none';
    if (feedbackEl) {
      feedbackEl.style.display = 'block';
      feedbackEl.innerHTML = `
        <div style="padding:10px 14px;background:#FEE2E2;color:#991B1B;border-radius:var(--radius-sm);font-size:var(--text-xs);">
          ${escapeHtml(err.detail || err.message || 'Plan B search failed.')}
        </div>
      `;
    }
  }
}

function clearPlanBSearch() {
  const input = document.getElementById('plan-b-search-input');
  const clearBtn = document.getElementById('plan-b-search-clear-btn');
  const loadingEl = document.getElementById('plan-b-search-loading');
  const feedbackEl = document.getElementById('plan-b-search-feedback');
  const resultsEl = document.getElementById('plan-b-search-results');

  if (input) input.value = '';
  if (clearBtn) clearBtn.style.display = 'none';
  if (loadingEl) loadingEl.style.display = 'none';
  if (feedbackEl) {
    feedbackEl.innerHTML = '';
    feedbackEl.style.display = 'none';
  }
  if (resultsEl) {
    resultsEl.innerHTML = '';
    resultsEl.style.display = 'none';
  }
}

// ---------------------------------------------------------------------------
// 10. WP-12 Step 6: In-Dashboard Notifications Controller
// ---------------------------------------------------------------------------
async function openNotificationsModal() {
  let modal = document.getElementById('admin-notifications-modal');
  let container = document.getElementById('admin-notifications-container');

  if (!modal) {
    const modalDiv = document.createElement('div');
    modalDiv.id = 'admin-notifications-modal';
    modalDiv.className = 'admin-modal-backdrop';
    modalDiv.innerHTML = `
      <div class="admin-modal-dialog" style="max-width:600px;">
        <div class="admin-modal-header">
          <h3 class="admin-modal-title">In-Dashboard Administrative Alerts</h3>
          <button type="button" class="admin-modal-close" onclick="closeNotificationsModal()">&times;</button>
        </div>
        <div class="admin-modal-body">
          <div id="admin-notifications-container" style="max-height:360px;overflow-y:auto;">
            <p style="text-align:center;padding:var(--space-4);color:var(--color-muted);">Loading alerts...</p>
          </div>
        </div>
        <div class="admin-modal-footer">
          <button type="button" class="btn btn-secondary btn-sm" onclick="markAllAdminNotificationsRead()">Mark All as Read</button>
          <button type="button" class="btn btn-primary btn-sm" onclick="closeNotificationsModal()">Done</button>
        </div>
      </div>
    `;
    document.body.appendChild(modalDiv);
    modal = modalDiv;
    container = document.getElementById('admin-notifications-container');
  }

  modal.style.display = 'flex';
  container.innerHTML = '<p style="text-align:center;padding:var(--space-4);color:var(--color-muted);">Loading alerts...</p>';

  try {
    const res = await window.ShopEasyAdmin.getNotifications({ page: 1, page_size: 20 });
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);
    
    if (items.length === 0) {
      container.innerHTML = '<p style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No administrative notifications recorded.</p>';
      return;
    }

    container.innerHTML = items.map(n => {
      const dateStr = n.created_at ? new Date(n.created_at).toLocaleString('en-IN') : '';
      const readBadge = n.is_read ? '<span class="badge badge-muted">Read</span>' : '<span class="badge badge-danger">Unread</span>';
      const progBadge = n.programme ? `<span class="badge ${n.programme === 'PLAN_A' ? 'badge-plan-a' : 'badge-plan-b'}" style="margin-left:4px;">${escapeHtml(n.programme)}</span>` : '';
      
      return `
        <div style="background:${n.is_read ? '#F8FAFC' : '#EFF6FF'};border:1px solid ${n.is_read ? '#E2E8F0' : '#BFDBFE'};border-radius:var(--radius-md);padding:var(--space-3);margin-bottom:var(--space-2);">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <div>
              <strong style="font-size:var(--text-xs);color:#1E3A8A;">${escapeHtml(n.title || n.event_type || 'Administrative Alert')}</strong>
              ${progBadge}
            </div>
            <div style="display:flex;align-items:center;gap:6px;">
              ${readBadge}
              <span style="font-size:10px;color:var(--color-muted);">${escapeHtml(dateStr)}</span>
            </div>
          </div>
          <div style="font-size:var(--text-xs);color:var(--color-text-subtle);line-height:1.4;">
            ${escapeHtml(n.message || n.description || '')}
          </div>
        </div>
      `;
    }).join('');

  } catch (err) {
    container.innerHTML = `<p style="text-align:center;padding:var(--space-4);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load notifications.')}</p>`;
  }
}

function closeNotificationsModal() {
  const modal = document.getElementById('admin-notifications-modal');
  if (modal) modal.style.display = 'none';
}

async function markAllAdminNotificationsRead() {
  try {
    await window.ShopEasyAPI.post('/notifications/read-all', {}, { auth: 'admin' });
    const countBadge = document.getElementById('admin-notif-count');
    if (countBadge) countBadge.style.display = 'none';
    await openNotificationsModal();
  } catch (err) {
    console.error('Failed to mark notifications read:', err);
  }
}

// ---------------------------------------------------------------------------
// 11. WP-12 Step 6: Plan A Administration Controller
// ---------------------------------------------------------------------------
let currentPlanACustomerId = null;

async function initAdminPlanAPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  await loadPlanAOverviewMetrics();
  await loadPlanAQueues();
}

async function loadPlanAOverviewMetrics() {
  // Reserve summary
  try {
    const resSummary = await window.ShopEasyAdmin.getPlanAReserveSummary();
    const reserveEl = document.getElementById('stat-plan-a-reserve');
    const entriesEl = document.getElementById('stat-plan-a-entries');
    if (reserveEl && resSummary) {
      reserveEl.textContent = formatCurrency(Number(resSummary.total_unallocated_amount ?? resSummary.total_unallocated_reserve ?? 0));
    }
    if (entriesEl && resSummary) {
      entriesEl.textContent = Number(resSummary.total_entries ?? resSummary.total_reserve_entries ?? 0);
    }
  } catch (e) {
    console.warn('Plan A reserve summary error:', e);
  }

  // Queues count
  try {
    const queuesRes = await window.ShopEasyAdmin.getPlanAQueues({ page: 1, page_size: 1 });
    const queuesEl = document.getElementById('stat-plan-a-queues-count');
    if (queuesEl && queuesRes) {
      queuesEl.textContent = typeof queuesRes.total === 'number' ? queuesRes.total : (Array.isArray(queuesRes) ? queuesRes.length : 0);
    }
  } catch (e) {}

  // Commissions count
  try {
    const commRes = await window.ShopEasyAdmin.getPlanACommissions({ page: 1, page_size: 1 });
    const commEl = document.getElementById('stat-plan-a-commissions-count');
    if (commEl && commRes) {
      commEl.textContent = typeof commRes.total === 'number' ? commRes.total : (Array.isArray(commRes) ? commRes.length : 0);
    }
  } catch (e) {}
}

function switchPlanATab(tabId) {
  const tabButtons = document.querySelectorAll('.admin-tabs .admin-tab');
  tabButtons.forEach(btn => {
    const isTarget = btn.getAttribute('onclick')?.includes(`'${tabId}'`);
    btn.classList.toggle('active', !!isTarget);
  });

  const sections = ['queues', 'cycles', 'reserve', 'commissions', 'customer-lookup'];
  sections.forEach(s => {
    const el = document.getElementById(`tab-${s}`);
    if (el) el.style.display = (s === tabId) ? 'block' : 'none';
  });

  if (tabId === 'queues') loadPlanAQueues();
  else if (tabId === 'cycles') loadPlanACycles();
  else if (tabId === 'reserve') loadPlanAReserve();
  else if (tabId === 'commissions') loadPlanACommissions();
}

async function loadPlanAQueues() {
  const tbody = document.getElementById('plan-a-queues-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:var(--space-6);">Loading queues...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanAQueues();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No Plan A cashback queues found.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(q => {
      const createdDate = q.created_at ? new Date(q.created_at).toLocaleDateString('en-IN') : 'N/A';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${q.id}</strong></td>
          <td>${escapeHtml(q.root_user_name || 'Root User')} <span style="font-size:11px;color:var(--color-muted);">(ID: #${q.root_user_id})</span></td>
          <td>${q.active_cycle_id ? `#${q.active_cycle_id}` : '<span style="color:var(--color-muted);">None</span>'}</td>
          <td>${q.last_allocated_position !== undefined ? q.last_allocated_position : 0}</td>
          <td><strong>${q.total_entries || 0}</strong></td>
          <td>${escapeHtml(createdDate)}</td>
          <td>
            <button type="button" class="table-action-btn" onclick="viewQueueEntries(${q.id})">View Entries</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load queues.')}</td></tr>`;
  }
}

async function viewQueueEntries(queueId) {
  const modal = document.getElementById('queue-entries-modal');
  const title = document.getElementById('queue-entries-modal-title');
  const tbody = document.getElementById('queue-entries-tbody');
  if (!modal || !tbody) return;

  if (title) title.textContent = `Queue #${queueId} Entries`;
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:var(--space-6);">Loading entries...</td></tr>';
  modal.style.display = 'flex';

  try {
    const res = await window.ShopEasyAdmin.getPlanAQueueEntries(queueId);
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No entries in this queue.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(e => {
      const enrolledDate = e.enrolled_at || e.created_at ? new Date(e.enrolled_at || e.created_at).toLocaleString('en-IN') : 'N/A';
      const statusBadge = e.status === 'ACTIVE' || e.status === 'COMPLETED' ? 'badge-success' : 'badge-primary';
      const bNumber = e.billing_number || (e.billing_id ? `BID-${e.billing_id}` : 'N/A');
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${e.id}</strong></td>
          <td><strong>Position #${e.position}</strong></td>
          <td>${escapeHtml(e.customer_name || 'Customer')} (#${e.user_id || e.customer_id})</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(bNumber)}</span></td>
          <td><span class="badge ${statusBadge}">${escapeHtml(e.status || 'Active')}</span></td>
          <td>${escapeHtml(enrolledDate)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load queue entries.')}</td></tr>`;
  }
}

function closeQueueEntriesModal() {
  const modal = document.getElementById('queue-entries-modal');
  if (modal) modal.style.display = 'none';
}

async function loadPlanACycles() {
  const tbody = document.getElementById('plan-a-cycles-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:var(--space-6);">Loading cycles...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanACycles();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No Plan A cycles found.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(c => {
      const contribs = c.completed_contributions !== undefined ? c.completed_contributions : 0;
      const bulbsCount = contribs * 3;
      const statusBadge = c.is_completed || c.status === 'COMPLETED' ? 'badge-success' : 'badge-primary';
      const bNumber = c.billing_number || (c.billing_id ? `BID-${c.billing_id}` : 'N/A');
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${c.id}</strong></td>
          <td>${escapeHtml(c.recipient_name || 'Customer')} (#${c.recipient_user_id || c.user_id})</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(bNumber)}</span></td>
          <td>Cycle #${c.cycle_number || 1}</td>
          <td><strong>${contribs} / 16</strong></td>
          <td><span class="badge badge-muted">${bulbsCount} / 48 bulbs</span></td>
          <td><strong style="color:#166534;">${formatCurrency(Number(c.total_earned || 0))}</strong></td>
          <td><span class="badge ${statusBadge}">${c.is_completed ? 'COMPLETED' : (c.status || 'ACTIVE')}</span></td>
          <td>
            <button type="button" class="table-action-btn" onclick="viewCycleContributions(${c.id})">Contributions</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load cycles.')}</td></tr>`;
  }
}

async function viewCycleContributions(cycleId) {
  const modal = document.getElementById('cycle-contribs-modal');
  const title = document.getElementById('cycle-contribs-modal-title');
  const tbody = document.getElementById('cycle-contribs-tbody');
  if (!modal || !tbody) return;

  if (title) title.textContent = `Cycle #${cycleId} Contributions (Max 16)`;
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:var(--space-6);">Loading contributions...</td></tr>';
  modal.style.display = 'flex';

  try {
    const res = await window.ShopEasyAdmin.getPlanACycleContributions(cycleId);
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No contributions recorded for this cycle yet.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(c => {
      const dateStr = c.allocated_at || c.created_at ? new Date(c.allocated_at || c.created_at).toLocaleString('en-IN') : 'N/A';
      const cNumber = c.contributing_billing_number || (c.contributing_billing_id ? `BID-${c.contributing_billing_id}` : 'N/A');
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${c.id}</strong></td>
          <td><strong>Contribution #${c.contribution_index || c.index || '-'}</strong></td>
          <td><strong>${c.amount != null ? formatCurrency(Number(c.amount)) : '—'}</strong></td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(cNumber)}</span></td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load cycle contributions.')}</td></tr>`;
  }
}

function closeCycleContribsModal() {
  const modal = document.getElementById('cycle-contribs-modal');
  if (modal) modal.style.display = 'none';
}

async function loadPlanAReserve() {
  const tbody = document.getElementById('plan-a-reserve-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:var(--space-6);">Loading reserve records...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanAReserve();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No unallocated reserve records.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(r => {
      const dateStr = r.reserved_at || r.created_at ? new Date(r.reserved_at || r.created_at).toLocaleString('en-IN') : 'N/A';
      const bNumber = r.billing_number || (r.billing_id ? `BID-${r.billing_id}` : 'N/A');
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${r.id}</strong></td>
          <td>Queue #${r.queue_id || '-'}</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(bNumber)}</span></td>
          <td>Customer #${r.customer_id || r.user_id || '-'}</td>
          <td><strong>${formatCurrency(Number(r.amount || 0))}</strong></td>
          <td><span class="badge" style="background:#FEF3C7;color:#92400E;font-size:11px;">COMPANY OWNED (BR-A4)</span></td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load reserve records.')}</td></tr>`;
  }
}

async function loadPlanACommissions() {
  const tbody = document.getElementById('plan-a-commissions-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);">Loading commissions...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanACommissions();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No direct commissions recorded.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(c => {
      const dateStr = c.processed_at || c.created_at ? new Date(c.processed_at || c.created_at).toLocaleString('en-IN') : 'N/A';
      const isUnallocated = c.status === 'UNALLOCATED_NO_REFERRER';
      const statusBadge = isUnallocated ? 'badge-warning' : (c.status === 'EARNED' || c.status === 'PAID' || c.status === 'PROCESSED' ? 'badge-success' : 'badge-primary');
      const badgeStyle = isUnallocated ? 'style="background:#FEF3C7;color:#92400E;font-size:11px;"' : '';
      const referrerDisplay = c.referrer_id ? `Customer #${c.referrer_id}` : '<span style="color:var(--color-muted);font-style:italic;">None (Company Reserve)</span>';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${c.id}</strong></td>
          <td>Customer #${c.purchaser_id || c.referee_id || '-'}</td>
          <td>${referrerDisplay}</td>
          <td><strong>${c.gross_amount != null ? formatCurrency(Number(c.gross_amount)) : '—'}</strong></td>
          <td style="color:#DC2626;">${c.tds_amount != null ? `-${formatCurrency(Number(c.tds_amount))}` : '—'}</td>
          <td><strong style="color:${isUnallocated ? '#64748B' : '#166534'};">${c.net_amount != null ? formatCurrency(Number(c.net_amount)) : '—'}</strong></td>
          <td><span class="badge ${statusBadge}" ${badgeStyle}>${escapeHtml(c.status || 'PAID')}</span></td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load commissions.')}</td></tr>`;
  }
}

async function inspectCustomerCashback() {
  const input = document.getElementById('lookup-customer-id');
  const resultContainer = document.getElementById('customer-lookup-result');
  if (!input || !resultContainer) return;

  const customerId = parseInt(input.value.trim(), 10);
  if (!customerId || isNaN(customerId) || customerId < 1) {
    alert('Please enter a valid positive numeric Customer User ID.');
    input.focus();
    return;
  }

  currentPlanACustomerId = customerId;

  try {
    const data = await window.ShopEasyAdmin.getPlanACustomerCashback(customerId);
    if (!data) throw new Error('Customer cashback profile not found.');

    const nameEl = document.getElementById('lookup-customer-name');
    const phoneEl = document.getElementById('lookup-customer-phone');
    const queueEl = document.getElementById('lookup-queue-pos');
    const contribsEl = document.getElementById('lookup-contribs');
    const bulbsEl = document.getElementById('lookup-bulbs');
    const earnedEl = document.getElementById('lookup-earned');
    const walletEl = document.getElementById('lookup-wallet');
    const lifetimeEl = document.getElementById('lookup-lifetime');

    if (nameEl) nameEl.textContent = data.customer_name || `Customer #${customerId}`;
    if (phoneEl) phoneEl.textContent = `Phone: ${data.customer_phone ? '+91 ' + data.customer_phone : 'N/A'}`;
    if (queueEl) queueEl.textContent = data.queue_position !== undefined && data.queue_position !== null ? `Position #${data.queue_position}` : 'Not in Queue';
    if (contribsEl) contribsEl.textContent = `${data.completed_contributions || 0} / 16`;
    if (bulbsEl) bulbsEl.textContent = data.bulbs_status || `${(data.completed_contributions || 0) * 3} of 48 bulbs`;
    if (earnedEl) earnedEl.textContent = formatCurrency(Number(data.cycle_total_earned || 0));
    if (walletEl) walletEl.textContent = formatCurrency(Number(data.wallet_balance || 0));
    if (lifetimeEl) lifetimeEl.textContent = formatCurrency(Number(data.lifetime_cashback || 0));

    resultContainer.style.display = 'block';
  } catch (err) {
    alert(err.detail || err.message || `Customer #${customerId} cashback lookup failed.`);
    resultContainer.style.display = 'none';
  }
}

async function downloadLookupStatement(format) {
  if (!currentPlanACustomerId) {
    alert('Please inspect a customer first.');
    return;
  }
  try {
    await window.ShopEasyAdmin.downloadPlanACustomerStatement(currentPlanACustomerId, format);
  } catch (err) {
    alert(err.detail || err.message || 'Statement download failed.');
  }
}

// ---------------------------------------------------------------------------
// 12. WP-12 Step 6: Plan B Administration Controller
// ---------------------------------------------------------------------------
async function initAdminPlanBPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  await loadPlanBOverviewMetrics();
  await loadPlanBDistributors();
}

async function loadPlanBOverviewMetrics() {
  const distEl = document.getElementById('stat-plan-b-distributors');
  const directEl = document.getElementById('stat-plan-b-direct');
  const genEl = document.getElementById('stat-plan-b-generation');
  const bidEl = document.getElementById('stat-plan-b-billing-ids');

  try {
    if (window.ShopEasyAdmin && window.ShopEasyAdmin.getPlanBOverviewSummary) {
      const summary = await window.ShopEasyAdmin.getPlanBOverviewSummary();
      if (summary) {
        if (distEl) distEl.textContent = summary.total_distributors ?? 0;
        if (directEl) directEl.textContent = summary.total_direct_commissions ?? 0;
        if (genEl) genEl.textContent = summary.total_generation_commissions ?? 0;
        if (bidEl) bidEl.textContent = summary.total_billing_ids ?? 0;
        return;
      }
    }
  } catch (e) {
    console.warn('Plan B summary endpoint fallback to list queries:', e);
  }

  try {
    const distRes = await window.ShopEasyAdmin.getPlanBDistributors({ page: 1, page_size: 100 });
    if (distEl && distRes) {
      distEl.textContent = typeof distRes.total === 'number' ? distRes.total : (Array.isArray(distRes) ? distRes.length : 0);
    }
  } catch (e) {}

  try {
    const directRes = await window.ShopEasyAdmin.getPlanBDirectCommissions({ page: 1, page_size: 100 });
    if (directEl && directRes) {
      directEl.textContent = typeof directRes.total === 'number' ? directRes.total : (Array.isArray(directRes) ? directRes.length : 0);
    }
  } catch (e) {}

  try {
    const genRes = await window.ShopEasyAdmin.getPlanBGenerationCommissions({ page: 1, page_size: 100 });
    if (genEl && genRes) {
      genEl.textContent = typeof genRes.total === 'number' ? genRes.total : (Array.isArray(genRes) ? genRes.length : 0);
    }
  } catch (e) {}

  try {
    const bidRes = await window.ShopEasyAdmin.getPlanBBillingIds({ page: 1, page_size: 100 });
    if (bidEl && bidRes) {
      bidEl.textContent = typeof bidRes.total === 'number' ? bidRes.total : (Array.isArray(bidRes) ? bidRes.length : 0);
    }
  } catch (e) {}
}

function switchPlanBTab(tabId) {
  const tabButtons = document.querySelectorAll('.admin-tabs .admin-tab');
  tabButtons.forEach(btn => {
    const isTarget = btn.getAttribute('onclick')?.includes(`'${tabId}'`);
    btn.classList.toggle('active', !!isTarget);
  });

  const sections = ['distributors', 'direct-commissions', 'generation-commissions', 'billing-ids', 'reports'];
  sections.forEach(s => {
    const el = document.getElementById(`tab-${s}`);
    if (el) el.style.display = (s === tabId) ? 'block' : 'none';
  });

  if (tabId === 'distributors') loadPlanBDistributors();
  else if (tabId === 'direct-commissions') loadPlanBDirectCommissions();
  else if (tabId === 'generation-commissions') loadPlanBGenerationCommissions();
  else if (tabId === 'billing-ids') loadPlanBBillingIds();
}

async function loadPlanBDistributors() {
  const tbody = document.getElementById('plan-b-distributors-tbody');
  const searchInput = document.getElementById('distributor-search-input');
  const statusSelect = document.getElementById('distributor-status-select');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);">Loading distributors...</td></tr>';

  const params = {};
  if (searchInput && searchInput.value.trim()) params.search = searchInput.value.trim();
  if (statusSelect && statusSelect.value) params.status = statusSelect.value;

  try {
    const res = await window.ShopEasyAdmin.getPlanBDistributors(params);
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No distributors found matching criteria.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(d => {
      const joinedDate = d.joined_at || d.created_at ? new Date(d.joined_at || d.created_at).toLocaleDateString('en-IN') : 'N/A';
      const statusClass = d.status === 'BLOCKED' ? 'badge-blocked' : (d.status === 'DEACTIVATED' ? 'badge-deactivated' : 'badge-active');
      const dName = escapeHtml(d.full_name || 'Distributor');
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${d.id}</strong></td>
          <td><strong>${dName}</strong></td>
          <td>+91 ${escapeHtml(d.phone || '')}</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;font-weight:600;color:#1E3A8A;">${escapeHtml(d.referral_code || 'N/A')}</span></td>
          <td><span class="badge ${statusClass}">${escapeHtml(d.status || 'ACTIVE')}</span></td>
          <td><strong>${d.direct_referees_count || 0}</strong></td>
          <td>${escapeHtml(joinedDate)}</td>
          <td>
            <div style="display:flex;gap:4px;">
              <button type="button" class="table-action-btn" onclick="viewDistributorWallet(${d.id}, '${dName}')">Wallet</button>
              <button type="button" class="table-action-btn" onclick="viewDistributorReferrals(${d.id}, '${dName}')">Referees</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load distributors.')}</td></tr>`;
  }
}

async function viewDistributorWallet(distributorId, distributorName) {
  const modal = document.getElementById('distributor-wallet-modal');
  const title = document.getElementById('distributor-wallet-modal-title');
  if (!modal) return;

  if (title) title.textContent = `Wallet Overview — ${distributorName || 'Distributor #' + distributorId}`;
  modal.style.display = 'flex';

  const balEl = document.getElementById('modal-wallet-balance');
  const earnEl = document.getElementById('modal-wallet-earned');
  const wEl = document.getElementById('modal-wallet-withdrawn');
  const frozenBadge = document.getElementById('modal-wallet-frozen-badge');
  const txTbody = document.getElementById('modal-wallet-tx-tbody');
  const wTbody = document.getElementById('modal-wallet-w-tbody');

  if (txTbody) txTbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:var(--space-4);">Loading transactions...</td></tr>';
  if (wTbody) wTbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:var(--space-4);">Loading withdrawals...</td></tr>';

  try {
    const data = await window.ShopEasyAdmin.getPlanBDistributorWallet(distributorId);
    if (!data) throw new Error('Distributor wallet data not returned.');

    if (balEl) balEl.textContent = formatCurrency(Number(data.balance || 0));
    if (earnEl) earnEl.textContent = formatCurrency(Number(data.total_earned || 0));
    if (wEl) wEl.textContent = formatCurrency(Number(data.total_withdrawn || 0));

    if (frozenBadge) {
      if (data.is_frozen) {
        frozenBadge.className = 'badge badge-blocked';
        frozenBadge.textContent = 'FROZEN';
      } else {
        frozenBadge.className = 'badge badge-active';
        frozenBadge.textContent = 'ACTIVE';
      }
    }

    if (txTbody) {
      const txs = Array.isArray(data.recent_transactions) ? data.recent_transactions : [];
      if (txs.length === 0) {
        txTbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:var(--space-4);color:var(--color-muted);">No transactions recorded.</td></tr>';
      } else {
        txTbody.innerHTML = txs.map(t => {
          const tDate = t.created_at ? new Date(t.created_at).toLocaleDateString('en-IN') : 'N/A';
          return `
            <tr>
              <td><span class="badge badge-muted">${escapeHtml(t.transaction_type || 'TX')}</span></td>
              <td><strong>${formatCurrency(Number(t.amount || 0))}</strong></td>
              <td>${formatCurrency(Number(t.balance_after || 0))}</td>
              <td><span style="font-size:11px;color:var(--color-muted);">${escapeHtml(t.reference_id || '-')}</span></td>
              <td>${escapeHtml(tDate)}</td>
            </tr>
          `;
        }).join('');
      }
    }

    if (wTbody) {
      const withdrawals = Array.isArray(data.recent_withdrawals) ? data.recent_withdrawals : [];
      if (withdrawals.length === 0) {
        wTbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:var(--space-4);color:var(--color-muted);">No withdrawal requests recorded.</td></tr>';
      } else {
        wTbody.innerHTML = withdrawals.map(w => {
          const wDate = w.requested_at ? new Date(w.requested_at).toLocaleDateString('en-IN') : 'N/A';
          const badgeClass = w.status === 'COMPLETED' ? 'badge-success' : (w.status === 'REJECTED' ? 'badge-danger' : 'badge-warning');
          return `
            <tr>
              <td><strong>${formatCurrency(Number(w.amount || 0))}</strong></td>
              <td><span class="badge ${badgeClass}">${escapeHtml(w.status || 'PENDING')}</span></td>
              <td style="font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(w.payout_reference || w.rejection_reason || '-')}</td>
              <td>${escapeHtml(wDate)}</td>
            </tr>
          `;
        }).join('');
      }
    }

  } catch (err) {
    if (balEl) balEl.textContent = 'Error';
    if (txTbody) txTbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load wallet.')}</td></tr>`;
  }
}

function closeDistributorWalletModal() {
  const modal = document.getElementById('distributor-wallet-modal');
  if (modal) modal.style.display = 'none';
}

async function viewDistributorReferrals(distributorId, distributorName) {
  const modal = document.getElementById('distributor-referrals-modal');
  const title = document.getElementById('distributor-referrals-modal-title');
  const tbody = document.getElementById('distributor-referrals-tbody');
  if (!modal || !tbody) return;

  if (title) title.textContent = `Direct Referees — ${distributorName || 'Distributor #' + distributorId}`;
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:var(--space-6);">Loading direct referees...</td></tr>';
  modal.style.display = 'flex';

  try {
    const res = await window.ShopEasyAdmin.getPlanBDistributorReferrals(distributorId);
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No direct referees registered for this distributor.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(r => {
      const boundDate = r.bound_at || r.created_at ? new Date(r.bound_at || r.created_at).toLocaleDateString('en-IN') : 'N/A';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${r.referee_id || r.id}</strong></td>
          <td><strong>${escapeHtml(r.referee_name || r.full_name || 'Referee')}</strong></td>
          <td>+91 ${escapeHtml(r.referee_phone || r.phone || '')}</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(r.referral_code_used || r.referral_code || '-')}</span></td>
          <td><span class="badge badge-muted">${escapeHtml(r.acquisition_channel || 'DIRECT')}</span></td>
          <td>${escapeHtml(boundDate)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load referrals.')}</td></tr>`;
  }
}

function closeDistributorReferralsModal() {
  const modal = document.getElementById('distributor-referrals-modal');
  if (modal) modal.style.display = 'none';
}

async function loadPlanBDirectCommissions() {
  const tbody = document.getElementById('plan-b-direct-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:var(--space-6);">Loading direct commissions...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanBDirectCommissions();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No direct commissions recorded.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(c => {
      const dateStr = c.processed_at || c.created_at ? new Date(c.processed_at || c.created_at).toLocaleString('en-IN') : 'N/A';
      const bNumber = c.billing_number || (c.billing_id ? `BID-${c.billing_id}` : 'N/A');
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${c.id}</strong></td>
          <td>Distributor #${c.distributor_id}</td>
          <td>Purchaser #${c.referee_id || c.purchaser_id || '-'}</td>
          <td>#${c.order_id || '-'}</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(bNumber)}</span></td>
          <td><strong>${formatCurrency(Number(c.gross_amount || 0))}</strong></td>
          <td style="color:#DC2626;">-${formatCurrency(Number(c.tds_amount || 0))}</td>
          <td><strong style="color:#166534;">${formatCurrency(Number(c.net_amount || 0))}</strong></td>
          <td><span class="badge badge-success">${escapeHtml(c.status || 'PAID')}</span></td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load commissions.')}</td></tr>`;
  }
}

async function loadPlanBGenerationCommissions() {
  const tbody = document.getElementById('plan-b-gen-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:var(--space-6);">Loading generation commissions...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanBGenerationCommissions();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No generation commissions recorded.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(c => {
      const dateStr = c.processed_at || c.created_at ? new Date(c.processed_at || c.created_at).toLocaleString('en-IN') : 'N/A';
      const bNumber = c.billing_number || (c.billing_id ? `BID-${c.billing_id}` : 'N/A');
      const genLevel = c.generation_level || 1;
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${c.id}</strong></td>
          <td>Distributor #${c.distributor_id}</td>
          <td>Purchaser #${c.referee_id || c.purchaser_id || '-'}</td>
          <td>#${c.order_id || '-'}</td>
          <td><span style="font-family:var(--font-mono);font-size:12px;">${escapeHtml(bNumber)}</span></td>
          <td><span class="badge" style="background:#EEF2FF;color:#4338CA;font-size:11px;">Level ${genLevel} (Direct Referee)</span></td>
          <td><strong>${c.gross_amount != null ? formatCurrency(Number(c.gross_amount)) : '—'}</strong></td>
          <td style="color:#DC2626;">${c.tds_amount != null ? `-${formatCurrency(Number(c.tds_amount))}` : '—'}</td>
          <td><strong style="color:#166534;">${c.net_amount != null ? formatCurrency(Number(c.net_amount)) : '—'}</strong></td>
          <td><span class="badge badge-success">${escapeHtml(c.status || 'PAID')}</span></td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load generation commissions.')}</td></tr>`;
  }
}

async function loadPlanBBillingIds() {
  const tbody = document.getElementById('plan-b-bids-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);">Loading Billing IDs...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPlanBBillingIds();
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No Plan B Billing IDs found.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(b => {
      const dateStr = b.allocated_at || b.created_at ? new Date(b.allocated_at || b.created_at).toLocaleString('en-IN') : 'N/A';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${b.id}</strong></td>
          <td><strong style="font-family:var(--font-mono);color:#1E3A8A;">${escapeHtml(b.billing_number || '')}</strong></td>
          <td>#${b.sequence_number || '-'}</td>
          <td>#${b.order_id || '-'}</td>
          <td>User #${b.user_id || '-'}</td>
          <td>Unit #${b.unit_index !== undefined ? b.unit_index + 1 : '1'}</td>
          <td><span class="badge badge-success">${escapeHtml(b.status || 'ALLOCATED')}</span></td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load Billing IDs.')}</td></tr>`;
  }
}

async function downloadPlanBPurchases() {
  try {
    await window.ShopEasyAdmin.downloadPlanBPurchasesReport();
  } catch (err) {
    alert(err.detail || err.message || 'Download failed.');
  }
}

async function downloadPlanBCommissions() {
  try {
    await window.ShopEasyAdmin.downloadPlanBCommissionsReport();
  } catch (err) {
    alert(err.detail || err.message || 'Download failed.');
  }
}

async function downloadIndividualDistributorReport() {
  const input = document.getElementById('report-distributor-id');
  if (!input) return;
  const dId = parseInt(input.value.trim(), 10);
  if (!dId || isNaN(dId) || dId < 1) {
    alert('Please enter a valid numeric Distributor ID.');
    input.focus();
    return;
  }
  try {
    await window.ShopEasyAdmin.downloadPlanBDistributorReport(dId);
  } catch (err) {
    alert(err.detail || err.message || `Download failed for distributor #${dId}.`);
  }
}

// ---------------------------------------------------------------------------
// 13. WP-12 Step 6: Withdrawal Moderation Controller
// ---------------------------------------------------------------------------
let activeApprovalWithdrawalId = null;
let activeRejectWithdrawalId = null;

async function initAdminWithdrawalsPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  await loadPendingWithdrawals();
}

function switchWithdrawalsTab(tabId) {
  const tabButtons = document.querySelectorAll('.admin-tabs .admin-tab');
  tabButtons.forEach(btn => {
    const isTarget = btn.getAttribute('onclick')?.includes(`'${tabId}'`);
    btn.classList.toggle('active', !!isTarget);
  });

  const tabPending = document.getElementById('tab-pending-withdrawals');
  const tabControl = document.getElementById('tab-wallet-control');

  if (tabPending) tabPending.style.display = (tabId === 'pending') ? 'block' : 'none';
  if (tabControl) tabControl.style.display = (tabId === 'wallet-control') ? 'block' : 'none';

  if (tabId === 'pending') loadPendingWithdrawals();
}

async function loadPendingWithdrawals() {
  const tbody = document.getElementById('pending-withdrawals-tbody');
  const countEl = document.getElementById('stat-pending-withdrawals');
  const amountEl = document.getElementById('stat-pending-amount');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-6);">Loading pending requests...</td></tr>';

  try {
    const res = await window.ShopEasyAdmin.getPendingWithdrawals();
    const items = Array.isArray(res) ? res : (res && Array.isArray(res.items) ? res.items : []);

    let totalPendingAmount = 0;
    items.forEach(w => {
      totalPendingAmount += Number(w.amount || 0);
    });

    if (countEl) countEl.textContent = items.length;
    if (amountEl) amountEl.textContent = formatCurrency(totalPendingAmount);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:var(--space-8);color:var(--color-muted);">No pending withdrawals requiring administrative review.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(w => {
      const dateStr = w.requested_at ? new Date(w.requested_at).toLocaleString('en-IN') : 'N/A';
      const wType = w.wallet?.wallet_type || w.wallet_type || 'COMMISSION';
      const isPlanA = wType.includes('PLAN_A') || wType.includes('SEQUENTIAL');
      const badgeClass = isPlanA ? 'badge-plan-a' : 'badge-plan-b';

      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${w.id}</strong></td>
          <td>User #${w.user_id}</td>
          <td>Wallet #${w.wallet_id}</td>
          <td><span class="badge ${badgeClass}">${escapeHtml(wType)}</span></td>
          <td><strong style="font-size:var(--text-md);color:#1E3A8A;">${formatCurrency(Number(w.amount || 0))}</strong></td>
          <td><span class="badge badge-warning">${escapeHtml(w.status || 'REQUESTED')}</span></td>
          <td>${escapeHtml(dateStr)}</td>
          <td>
            <div style="display:flex;gap:4px;">
              <button type="button" class="table-action-btn" style="color:#166534;border-color:#BBF7D0;" onclick="openApproveModal(${w.id}, ${w.amount})">Approve</button>
              <button type="button" class="table-action-btn delete" onclick="openRejectModal(${w.id}, ${w.amount})">Reject</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load pending withdrawals.')}</td></tr>`;
  }
}

function openApproveModal(withdrawalId, amount) {
  activeApprovalWithdrawalId = withdrawalId;
  const modal = document.getElementById('approve-withdrawal-modal');
  const widEl = document.getElementById('approve-modal-wid');
  const amtEl = document.getElementById('approve-modal-amount');
  if (widEl) widEl.textContent = `#${withdrawalId}`;
  if (amtEl) amtEl.textContent = formatCurrency(Number(amount));
  if (modal) modal.style.display = 'flex';
}

function closeApproveModal() {
  activeApprovalWithdrawalId = null;
  const modal = document.getElementById('approve-withdrawal-modal');
  if (modal) modal.style.display = 'none';
}

async function submitApproveWithdrawal() {
  if (!activeApprovalWithdrawalId) return;
  const btn = document.getElementById('confirm-approve-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Approving...';
  }

  try {
    await window.ShopEasyAdmin.approveWithdrawal(activeApprovalWithdrawalId);
    alert(`Withdrawal #${activeApprovalWithdrawalId} approved successfully.`);
    closeApproveModal();
    await loadPendingWithdrawals();
  } catch (err) {
    alert(err.detail || err.message || 'Failed to approve withdrawal.');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Confirm & Approve';
    }
  }
}

function openRejectModal(withdrawalId, amount) {
  activeRejectWithdrawalId = withdrawalId;
  const modal = document.getElementById('reject-withdrawal-modal');
  const widEl = document.getElementById('reject-modal-wid');
  const amtEl = document.getElementById('reject-modal-amount');
  const reasonInput = document.getElementById('reject-modal-reason');

  if (widEl) widEl.textContent = `#${withdrawalId}`;
  if (amtEl) amtEl.textContent = formatCurrency(Number(amount));
  if (reasonInput) reasonInput.value = '';
  if (modal) modal.style.display = 'flex';
}

function closeRejectModal() {
  activeRejectWithdrawalId = null;
  const modal = document.getElementById('reject-withdrawal-modal');
  if (modal) modal.style.display = 'none';
}

async function submitRejectWithdrawal() {
  if (!activeRejectWithdrawalId) return;
  const reasonInput = document.getElementById('reject-modal-reason');
  const reason = reasonInput ? reasonInput.value.trim() : '';

  if (!reason) {
    alert('A rejection reason is mandatory.');
    if (reasonInput) reasonInput.focus();
    return;
  }

  const btn = document.getElementById('confirm-reject-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Rejecting...';
  }

  try {
    await window.ShopEasyAdmin.rejectWithdrawal(activeRejectWithdrawalId, reason);
    alert(`Withdrawal #${activeRejectWithdrawalId} rejected successfully.`);
    closeRejectModal();
    await loadPendingWithdrawals();
  } catch (err) {
    alert(err.detail || err.message || 'Failed to reject withdrawal.');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Confirm Rejection';
    }
  }
}

async function resolveUserWalletInfo() {
  const userNumberInput = document.getElementById('freeze-user-number');
  const infoBox = document.getElementById('wallet-user-info-box');
  const infoText = document.getElementById('wallet-user-info-text');
  const multiSelector = document.getElementById('wallet-multi-selector');
  const walletIdHidden = document.getElementById('freeze-wallet-id');
  if (!userNumberInput || !infoBox || !infoText) return null;

  const userNumber = userNumberInput.value.trim();
  if (!userNumber) {
    infoBox.style.display = 'none';
    if (walletIdHidden) walletIdHidden.value = '';
    return null;
  }

  try {
    infoBox.style.display = 'block';
    infoText.innerHTML = '<span style="color:var(--color-muted);">Looking up user and wallets...</span>';
    if (multiSelector) multiSelector.style.display = 'none';

    const res = await window.ShopEasyAdmin.lookupWalletsByUserNumber(userNumber);
    const wallets = res.wallets || [];

    if (wallets.length === 0) {
      infoText.innerHTML = `<span style="color:#B45309;">User <strong>${escapeHtml(res.full_name)}</strong> (${escapeHtml(res.phone)}) found, but has no associated wallets.</span>`;
      if (walletIdHidden) walletIdHidden.value = '';
      return res;
    }

    if (wallets.length === 1) {
      const w = wallets[0];
      if (walletIdHidden) walletIdHidden.value = w.id;
      infoText.innerHTML = `
        <div style="color:#0F172A;font-weight:600;margin-bottom:2px;">User: ${escapeHtml(res.full_name)} (ID: #${res.user_id || res.id}, Phone: ${escapeHtml(res.phone)}) &bull; Role: ${escapeHtml(res.role || 'CUSTOMER')}${res.programme ? ' &bull; ' + escapeHtml(res.programme) : ''}</div>
        <div style="font-size:11px;color:#475569;">
          Wallet #${w.id} (${escapeHtml(w.wallet_type)}) &bull; Balance: ₹${parseFloat(w.balance).toFixed(2)} &bull; Status: <span class="badge ${w.is_frozen ? 'badge-danger' : 'badge-success'}">${w.is_frozen ? 'FROZEN' : 'ACTIVE'}</span>
        </div>
      `;
      if (multiSelector) multiSelector.style.display = 'none';
      return res;
    }

    // Multiple wallets: allow administrative selection
    infoText.innerHTML = `<div style="color:#0F172A;font-weight:600;margin-bottom:4px;">User: ${escapeHtml(res.full_name)} (ID: #${res.user_id || res.id}, Phone: ${escapeHtml(res.phone)}) &bull; Role: ${escapeHtml(res.role || 'CUSTOMER')}${res.programme ? ' &bull; ' + escapeHtml(res.programme) : ''} (Multiple Wallets)</div>`;
    if (multiSelector) {
      multiSelector.style.display = 'block';
      multiSelector.innerHTML = `
        <div style="font-size:11px;font-weight:600;color:#334155;margin-bottom:4px;">Select Target Wallet:</div>
        <div style="display:flex;flex-direction:column;gap:4px;">
          ${wallets.map((w, idx) => `
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;background:#FFFFFF;padding:4px 8px;border:1px solid #CBD5E1;border-radius:4px;">
              <input type="radio" name="selected_wallet_target" value="${w.id}" ${idx === 0 ? 'checked' : ''} onchange="document.getElementById('freeze-wallet-id').value = this.value">
              <span><strong>Wallet #${w.id}</strong> (${escapeHtml(w.wallet_type)}) &bull; ₹${parseFloat(w.balance).toFixed(2)} &bull; <span class="badge ${w.is_frozen ? 'badge-danger' : 'badge-success'}" style="font-size:10px;">${w.is_frozen ? 'FROZEN' : 'ACTIVE'}</span></span>
            </label>
          `).join('')}
        </div>
      `;
      if (walletIdHidden) walletIdHidden.value = wallets[0].id;
    }
    return res;
  } catch (err) {
    infoBox.style.display = 'block';
    infoText.innerHTML = `<span style="color:var(--color-danger);">${escapeHtml(err.detail || 'User lookup failed.')}</span>`;
    if (multiSelector) multiSelector.style.display = 'none';
    if (walletIdHidden) walletIdHidden.value = '';
    return null;
  }
}

async function executeWalletFreezeAction(isFreeze) {
  const userNumberInput = document.getElementById('freeze-user-number');
  const walletIdInput = document.getElementById('freeze-wallet-id');
  const reasonInput = document.getElementById('freeze-reason');
  if (!reasonInput) return;

  const reason = reasonInput.value.trim();

  if (isFreeze && !reason) {
    alert('A reason is mandatory for freezing a wallet.');
    reasonInput.focus();
    return;
  }

  // Branch 1: User Number (Primary flow per Prompt 11)
  if (userNumberInput) {
    const userNumber = userNumberInput.value.trim();
    if (!userNumber) {
      alert('Please enter a valid User Number (e.g. 9876543210).');
      userNumberInput.focus();
      return;
    }

    const selectedWalletId = walletIdInput && walletIdInput.value ? parseInt(walletIdInput.value, 10) : null;

    const confirmMsg = isFreeze
      ? `Are you sure you want to FREEZE this wallet? The user will be unable to request withdrawals until unfrozen.\n\nReason: "${reason}"`
      : `Are you sure you want to UNFREEZE this wallet and restore withdrawal access?`;
    if (!window.confirm(confirmMsg)) {
      return;
    }

    try {
      let res;
      if (isFreeze) {
        res = await window.ShopEasyAdmin.freezeWalletByUserNumber(userNumber, reason, selectedWalletId);
        alert(res.message || `Wallet frozen successfully for user ${userNumber}.`);
      } else {
        res = await window.ShopEasyAdmin.unfreezeWalletByUserNumber(userNumber, reason || 'Administrative unfreeze', selectedWalletId);
        alert(res.message || `Wallet unfrozen successfully for user ${userNumber}.`);
      }
      reasonInput.value = '';
      await resolveUserWalletInfo();
      await loadWalletFreezeHistory();
    } catch (err) {
      if (err.status === 409 || err.statusCode === 409) {
        await resolveUserWalletInfo();
        alert(err.detail || 'Multiple wallets found for this user. Please select the target wallet from the options displayed.');
      } else {
        alert(err.detail || err.message || `Failed to ${isFreeze ? 'freeze' : 'unfreeze'} wallet.`);
      }
    }
    return;
  }

  // Branch 2: Legacy fallback to numeric Wallet ID if userNumberInput not present
  if (walletIdInput) {
    const walletId = parseInt(walletIdInput.value.trim(), 10);
    if (!walletId || isNaN(walletId) || walletId < 1) {
      alert('Please enter a valid numeric Wallet ID or User Number.');
      walletIdInput.focus();
      return;
    }

    try {
      if (isFreeze) {
        await window.ShopEasyAdmin.freezeWallet(walletId, reason);
        alert(`Wallet #${walletId} frozen successfully.`);
      } else {
        await window.ShopEasyAdmin.unfreezeWallet(walletId, reason || 'Administrative unfreeze');
        alert(`Wallet #${walletId} unfrozen successfully.`);
      }
      reasonInput.value = '';
      await loadWalletFreezeHistory();
    } catch (err) {
      alert(err.detail || err.message || `Failed to ${isFreeze ? 'freeze' : 'unfreeze'} wallet.`);
    }
  }
}

async function loadWalletFreezeHistory() {
  const userNumberInput = document.getElementById('freeze-user-number');
  const walletIdInput = document.getElementById('freeze-wallet-id');
  const container = document.getElementById('wallet-freeze-history-container');
  const tbody = document.getElementById('wallet-freeze-history-tbody');
  if (!container || !tbody) return;

  const userNumber = userNumberInput ? userNumberInput.value.trim() : '';
  const walletId = walletIdInput && walletIdInput.value ? parseInt(walletIdInput.value.trim(), 10) : null;

  if (!userNumber && (!walletId || isNaN(walletId) || walletId < 1)) {
    alert('Please enter a User Number (e.g. 9876543210) to inspect freeze history.');
    if (userNumberInput) userNumberInput.focus();
    else if (walletIdInput) walletIdInput.focus();
    return;
  }

  container.style.display = 'block';
  tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:var(--space-4);">Loading freeze audit history...</td></tr>';

  try {
    let res;
    if (userNumber) {
      res = await window.ShopEasyAdmin.getWalletFreezeHistoryByUserNumber(userNumber, walletId);
    } else {
      res = await window.ShopEasyAdmin.getWalletFreezeHistory(walletId);
    }

    const items = Array.isArray(res) ? res : (res && Array.isArray(res.items) ? res.items : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:var(--space-4);color:var(--color-muted);">No freeze/unfreeze actions recorded for this user/wallet.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(h => {
      const dateStr = h.created_at ? new Date(h.created_at).toLocaleString('en-IN') : 'N/A';
      const actionBadge = h.action === 'FREEZE' ? 'badge-danger' : 'badge-success';
      return `
        <tr>
          <td><strong style="font-family:var(--font-mono);">#${h.id}</strong> (Wallet #${h.wallet_id})</td>
          <td><span class="badge ${actionBadge}">${escapeHtml(h.action)}</span></td>
          <td>Admin #${h.admin_id}</td>
          <td>${escapeHtml(h.reason || '-')}</td>
          <td>${escapeHtml(dateStr)}</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:var(--space-4);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load wallet freeze history.')}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// 14. WP-12 Step 6: Centralized Reports & Downloads Controller
// ---------------------------------------------------------------------------
async function initAdminReportsPage() {
  const admin = await initAdminShell();
  if (!admin) return;
}

function clearReportDateFilters() {
  const s = document.getElementById('reports-start-date');
  const e = document.getElementById('reports-end-date');
  if (s) s.value = '';
  if (e) e.value = '';
}

function getReportDateFilters() {
  const startDate = document.getElementById('reports-start-date')?.value || undefined;
  const endDate = document.getElementById('reports-end-date')?.value || undefined;
  const params = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  return params;
}

async function downloadReport(reportType, format) {
  const params = getReportDateFilters();
  try {
    if (reportType === 'plan-a-commissions') {
      await window.ShopEasyAdmin.downloadPlanACommissionsReport({ format, ...params });
    } else if (reportType === 'plan-a-cashback') {
      await window.ShopEasyAdmin.downloadPlanACashbackReport({ format, ...params });
    } else if (reportType === 'plan-b-purchases') {
      await window.ShopEasyAdmin.downloadPlanBPurchasesReport(params);
    } else if (reportType === 'plan-b-commissions') {
      await window.ShopEasyAdmin.downloadPlanBCommissionsReport(params);
    }
  } catch (err) {
    alert(err.detail || err.message || `Download failed for report: ${reportType}`);
  }
}

async function downloadCustomerStatement(format) {
  const input = document.getElementById('statement-customer-id');
  if (!input) return;
  const rawIdentifier = (input.value || '').trim();
  if (!rawIdentifier) {
    alert('Please enter a Customer User ID (e.g. 30001) or 10-digit registered phone number (e.g. 9019443501).');
    input.focus();
    return;
  }

  const btnId = format === 'pdf' ? 'btn-customer-stmt-pdf' : 'btn-customer-stmt-excel';
  const btn = document.getElementById(btnId);
  const origText = btn ? btn.innerHTML : '';

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" style="display:inline-block;width:12px;height:12px;border:2px solid #FFFFFF;border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite;margin-right:6px;vertical-align:middle;"></span> Generating ${format.toUpperCase()}...`;
    }

    const params = getReportDateFilters();
    await window.ShopEasyAdmin.downloadPlanACustomerStatement(rawIdentifier, format, params);
  } catch (err) {
    alert(err.detail || err.message || `Download failed for customer statement: "${rawIdentifier}".`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

async function downloadDistributorProfileReport() {
  const input = document.getElementById('statement-distributor-id');
  if (!input) return;
  const rawIdentifier = (input.value || '').trim();
  if (!rawIdentifier) {
    alert('Please enter a Distributor User ID or 10-digit registered phone number.');
    input.focus();
    return;
  }

  const btn = document.getElementById('btn-distributor-report-excel');
  const origText = btn ? btn.innerHTML : '';

  try {
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner" style="display:inline-block;width:12px;height:12px;border:2px solid #FFFFFF;border-top-color:transparent;border-radius:50%;animation:spin 0.6s linear infinite;margin-right:6px;vertical-align:middle;"></span> Generating Excel...`;
    }

    const params = getReportDateFilters();
    await window.ShopEasyAdmin.downloadPlanBDistributorReport(rawIdentifier, params);
  } catch (err) {
    alert(err.detail || err.message || `Download failed for distributor profile: "${rawIdentifier}".`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

// ---------------------------------------------------------------------------
// 15. WP-12 Step 6: Financial Settings & Effective Dating Controller
// ---------------------------------------------------------------------------
async function initAdminSettingsPage() {
  const admin = await initAdminShell();
  if (!admin) return;

  await loadFinancialSettings();
}

async function loadFinancialSettings() {
  const tbody = document.getElementById('financial-settings-tbody');
  const progSelect = document.getElementById('settings-programme-filter');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:var(--space-6);">Loading settings...</td></tr>';

  const params = {};
  if (progSelect && progSelect.value) params.programme = progSelect.value;

  try {
    const res = await window.ShopEasyAdmin.getFinancialSettings(params);
    const items = res && Array.isArray(res.items) ? res.items : (Array.isArray(res) ? res : []);

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">No financial settings found.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(s => {
      const fromStr = s.effective_from ? new Date(s.effective_from).toLocaleString('en-IN') : 'Immediate';
      const toStr = s.effective_to ? new Date(s.effective_to).toLocaleString('en-IN') : '<span style="color:#166534;font-weight:600;">Indefinite</span>';
      const isSecret = s.is_secret === true;
      const displayVal = isSecret ? '••••••••' : `${formatCurrency(Number(s.setting_value))} (${s.currency || 'INR'})`;
      const progBadge = s.programme === 'PLAN_A' ? 'badge-plan-a' : 'badge-plan-b';
      const statusBadge = s.is_active ? 'badge-success' : 'badge-muted';

      return `
        <tr>
          <td><span class="badge ${progBadge}">${escapeHtml(s.programme)}</span></td>
          <td><strong style="font-family:var(--font-mono);">${escapeHtml(s.setting_key)}</strong></td>
          <td><strong>${escapeHtml(displayVal)}</strong></td>
          <td><span class="badge badge-primary">v${s.version}</span></td>
          <td>${escapeHtml(fromStr)}</td>
          <td>${toStr}</td>
          <td><span class="badge ${statusBadge}">${s.is_active ? 'Active' : 'Superseded'}</span></td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:var(--space-6);color:var(--color-danger);">${escapeHtml(err.detail || 'Failed to load financial settings.')}</td></tr>`;
  }
}

function openProposeSettingModal() {
  const modal = document.getElementById('propose-setting-modal');
  const dateInput = document.getElementById('form-effective-from');
  const errBox = document.getElementById('form-setting-error');

  if (errBox) {
    errBox.textContent = '';
    errBox.style.display = 'none';
  }

  // Pre-fill effective_from with tomorrow UTC
  if (dateInput) {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setMinutes(tomorrow.getMinutes() - tomorrow.getTimezoneOffset());
    dateInput.value = tomorrow.toISOString().slice(0, 16);
  }

  if (modal) modal.style.display = 'flex';
}

function closeProposeSettingModal() {
  const modal = document.getElementById('propose-setting-modal');
  if (modal) modal.style.display = 'none';
}

async function submitProposeSetting(event) {
  event.preventDefault();

  const progInput = document.getElementById('form-setting-programme');
  const keyInput = document.getElementById('form-setting-key');
  const valInput = document.getElementById('form-setting-value');
  const dateInput = document.getElementById('form-effective-from');
  const reasonInput = document.getElementById('form-setting-reason');
  const errBox = document.getElementById('form-setting-error');
  const btn = document.getElementById('submit-setting-btn');

  const programme = progInput ? progInput.value : 'PLAN_A';
  const settingKey = keyInput ? keyInput.value.trim().toUpperCase() : '';
  const settingVal = valInput ? parseFloat(valInput.value) : NaN;
  const effectiveFrom = dateInput ? dateInput.value : '';
  const reason = reasonInput ? reasonInput.value.trim() : '';

  if (!settingKey) {
    if (errBox) { errBox.textContent = 'Please enter a setting key.'; errBox.style.display = 'block'; }
    return;
  }
  if (isNaN(settingVal) || settingVal < 0) {
    if (errBox) { errBox.textContent = 'Please enter a valid numeric value (0 or greater).'; errBox.style.display = 'block'; }
    return;
  }
  if (!effectiveFrom) {
    if (errBox) { errBox.textContent = 'Please select a prospective effective date.'; errBox.style.display = 'block'; }
    return;
  }

  const selectedDate = new Date(effectiveFrom);
  if (selectedDate.getTime() <= Date.now()) {
    if (errBox) {
      errBox.textContent = 'Prospective Invariant Violation: Effective date must be in the future per rule ED-02.';
      errBox.style.display = 'block';
    }
    return;
  }

  if (!reason) {
    if (errBox) { errBox.textContent = 'A mandatory governance/audit reason is required.'; errBox.style.display = 'block'; }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Submitting...';
  }
  if (errBox) errBox.style.display = 'none';

  try {
    const payload = {
      programme: programme,
      setting_key: settingKey,
      setting_value: settingVal,
      currency: 'INR',
      effective_from: selectedDate.toISOString(),
      change_reason: reason
    };

    await window.ShopEasyAdmin.createFinancialSetting(payload);
    alert(`Financial setting ${settingKey} proposed successfully with prospective effective date.`);
    closeProposeSettingModal();
    await loadFinancialSettings();
  } catch (err) {
    if (errBox) {
      errBox.textContent = err.detail || err.message || 'Failed to submit setting update.';
      errBox.style.display = 'block';
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Submit Update';
    }
  }
}


// ---------------------------------------------------------------------------
// Global Window Exports
// ---------------------------------------------------------------------------
window.initAdminShell = initAdminShell;
window.initAdminDashboard = initAdminDashboard;
window.initAdminOrdersPage = initAdminOrdersPage;
window.renderAdminOrdersTable = renderAdminOrdersTable;
window.filterAdminOrdersTable = filterAdminOrdersTable;
window.executeOrdersSearch = executeOrdersSearch;
window.openOrderInspectModal = openOrderInspectModal;
window.closeOrderInspectModal = closeOrderInspectModal;
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

// WP-12 Step 6 Window Exports
window.executeUnifiedSearch = executeUnifiedSearch;
window.closeUnifiedSearchModal = closeUnifiedSearchModal;
window.openNotificationsModal = openNotificationsModal;
window.closeNotificationsModal = closeNotificationsModal;
window.markAllAdminNotificationsRead = markAllAdminNotificationsRead;

window.initAdminPlanAPage = initAdminPlanAPage;
window.switchPlanATab = switchPlanATab;
window.loadPlanAQueues = loadPlanAQueues;
window.viewQueueEntries = viewQueueEntries;
window.closeQueueEntriesModal = closeQueueEntriesModal;
window.loadPlanACycles = loadPlanACycles;
window.viewCycleContributions = viewCycleContributions;
window.closeCycleContribsModal = closeCycleContribsModal;
window.loadPlanAReserve = loadPlanAReserve;
window.loadPlanACommissions = loadPlanACommissions;
window.inspectCustomerCashback = inspectCustomerCashback;
window.downloadLookupStatement = downloadLookupStatement;

window.initAdminPlanBPage = initAdminPlanBPage;
window.switchPlanBTab = switchPlanBTab;
window.loadPlanBDistributors = loadPlanBDistributors;
window.viewDistributorWallet = viewDistributorWallet;
window.closeDistributorWalletModal = closeDistributorWalletModal;
window.viewDistributorReferrals = viewDistributorReferrals;
window.closeDistributorReferralsModal = closeDistributorReferralsModal;
window.loadPlanBDirectCommissions = loadPlanBDirectCommissions;
window.loadPlanBGenerationCommissions = loadPlanBGenerationCommissions;
window.loadPlanBBillingIds = loadPlanBBillingIds;
window.downloadPlanBPurchases = downloadPlanBPurchases;
window.downloadPlanBCommissions = downloadPlanBCommissions;
window.downloadIndividualDistributorReport = downloadIndividualDistributorReport;

window.initAdminWithdrawalsPage = initAdminWithdrawalsPage;
window.switchWithdrawalsTab = switchWithdrawalsTab;
window.loadPendingWithdrawals = loadPendingWithdrawals;
window.openApproveModal = openApproveModal;
window.closeApproveModal = closeApproveModal;
window.submitApproveWithdrawal = submitApproveWithdrawal;
window.openRejectModal = openRejectModal;
window.closeRejectModal = closeRejectModal;
window.submitRejectWithdrawal = submitRejectWithdrawal;
window.executeWalletFreezeAction = executeWalletFreezeAction;
window.loadWalletFreezeHistory = loadWalletFreezeHistory;
window.resolveUserWalletInfo = resolveUserWalletInfo;

window.initAdminReportsPage = initAdminReportsPage;
window.clearReportDateFilters = clearReportDateFilters;
window.downloadReport = downloadReport;
window.downloadCustomerStatement = downloadCustomerStatement;
window.downloadDistributorProfileReport = downloadDistributorProfileReport;

window.initAdminSettingsPage = initAdminSettingsPage;
window.loadFinancialSettings = loadFinancialSettings;
window.openProposeSettingModal = openProposeSettingModal;
window.closeProposeSettingModal = closeProposeSettingModal;
window.submitProposeSetting = submitProposeSetting;

// Shared Admin Navigation exports
window.ADMIN_NAV_ITEMS = ADMIN_NAV_ITEMS;
window.renderSharedAdminSidebar = renderSharedAdminSidebar;

// Module Search Controllers exports
window.executePlanASearch = executePlanASearch;
window.clearPlanASearch = clearPlanASearch;
window.executePlanBSearch = executePlanBSearch;
window.clearPlanBSearch = clearPlanBSearch;
window.clearUnifiedSearch = clearUnifiedSearch;
