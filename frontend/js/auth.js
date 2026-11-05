/**
 * ShopEasy — Authentication Interface Logic
 *
 * Implements three clearly visible options:
 *   1. Customer Login (10-digit mobile number + password)
 *   2. Admin Login (admin phone + password directly to admin portal)
 *   3. Customer Registration (full name, 10-digit phone, password, confirm password)
 *
 * Ensures:
 *   - Role separation: Customer login rejects admins, Admin login rejects customers.
 *   - Safe redirection with open redirect protection.
 *   - Clean success and error feedback messaging.
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Session Accessors (Backwards-compatibility with prototype UI)
  // -------------------------------------------------------------------------
  window.getCurrentCustomer = function () {
    return window.ShopEasyAPI ? window.ShopEasyAPI.getCustomerUser() : null;
  };

  window.setCustomerSession = function (user) {
    if (window.ShopEasyAPI) {
      window.ShopEasyAPI.setCustomerUser(user);
    }
  };

  window.logoutCustomer = function (redirectUrl = 'login.html') {
    if (window.ShopEasyAuth) {
      window.ShopEasyAuth.customerLogout(redirectUrl);
    } else {
      localStorage.removeItem('shopeasy_customer_token');
      localStorage.removeItem('shopeasy_customer_user');
      window.location.href = redirectUrl;
    }
  };

  // -------------------------------------------------------------------------
  // Message Banner Helpers
  // -------------------------------------------------------------------------
  function showAuthMessage(msg, type = 'error') {
    const banner = document.getElementById('auth-message-banner');
    if (!banner) return;
    banner.className = `auth-message-banner ${type}`;
    banner.textContent = msg;
    banner.style.display = 'block';
  }

  function clearAuthMessage() {
    const banner = document.getElementById('auth-message-banner');
    if (!banner) return;
    banner.className = 'auth-message-banner';
    banner.textContent = '';
    banner.style.display = 'none';
  }

  // -------------------------------------------------------------------------
  // Tab Switching Helpers (Supports: customer, admin, register)
  // -------------------------------------------------------------------------
  function switchTab(tabName) {
    clearAuthMessage();
    const validTabs = ['customer', 'admin', 'register'];
    const activeTab = validTabs.includes(tabName) ? tabName : 'customer';

    const tabs = document.querySelectorAll('.auth-tab');
    const panels = document.querySelectorAll('.auth-panel');

    tabs.forEach(t => {
      const isTarget = t.dataset.tab === activeTab || (activeTab === 'customer' && t.dataset.tab === 'password');
      t.classList.toggle('active', isTarget);
      t.setAttribute('aria-selected', isTarget ? 'true' : 'false');
    });

    panels.forEach(p => {
      p.classList.remove('active');
    });

    const targetPanel = document.getElementById(`panel-${activeTab}`) ||
                        (activeTab === 'customer' ? document.getElementById('panel-password') : null);
    if (targetPanel) {
      targetPanel.classList.add('active');
    }
  }

  window.switchTab = switchTab;

  // Harmless backward-compatibility stubs
  window.switchCustomerOtpStep = function () {};
  window.handleResendOtp = function () {};

  // -------------------------------------------------------------------------
  // Main Login Page Initializer
  // -------------------------------------------------------------------------
  window.initLoginPage = function () {
    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab') || 'customer';

    // 1. Check if user is already authenticated
    const customerToken = window.ShopEasyAPI ? window.ShopEasyAPI.getCustomerToken() : null;
    const adminToken = window.ShopEasyAPI ? window.ShopEasyAPI.getAdminToken() : null;

    if (initialTab === 'admin') {
      if (adminToken && window.redirectIfAdminAuthenticated) {
        window.redirectIfAdminAuthenticated('admin/dashboard.html');
      }
    } else {
      if (customerToken && window.redirectIfCustomerAuthenticated) {
        window.redirectIfCustomerAuthenticated('profile.html');
      }
    }

    // 2. Set Initial Active Tab
    switchTab(initialTab);

    // 3. Wire Tab Navigation
    const tabButtons = document.querySelectorAll('.auth-tab');
    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        switchTab(btn.dataset.tab);
      });
    });

    // 4. Quick-switch links between panels
    const linkGoToRegister = document.getElementById('link-go-to-register');
    if (linkGoToRegister) {
      linkGoToRegister.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab('register');
      });
    }

    const linkGoToLogin = document.getElementById('link-go-to-login');
    if (linkGoToLogin) {
      linkGoToLogin.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab('customer');
      });
    }

    // 5. Option 1: Customer Password Login Form
    const custForm = document.getElementById('customer-login-form') || document.getElementById('password-login-form');
    const custPhoneInput = document.getElementById('customer-phone-input') || document.getElementById('pwd-phone-input');
    const custPwdInput = document.getElementById('customer-password-input');
    const custBtn = document.getElementById('customer-login-btn') || document.getElementById('pwd-login-btn');

    if (custForm) {
      custForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearAuthMessage();

        const phoneVal = custPhoneInput ? custPhoneInput.value.trim().replace(/\D/g, '') : '';
        const pwdVal = custPwdInput ? custPwdInput.value : '';

        if (phoneVal.length !== 10) {
          showAuthMessage('Please enter a valid 10-digit customer mobile number.', 'error');
          if (custPhoneInput) custPhoneInput.focus();
          return;
        }

        if (!pwdVal) {
          showAuthMessage('Please enter your account password.', 'error');
          if (custPwdInput) custPwdInput.focus();
          return;
        }

        if (custBtn) {
          custBtn.disabled = true;
          custBtn.textContent = 'Signing In...';
        }

        try {
          const authRes = await window.ShopEasyAuth.customerLogin(phoneVal, pwdVal);
          showAuthMessage('Signed in successfully! Redirecting...', 'success');

          const rawRedirect = urlParams.get('redirect');
          const redirectParam = window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'profile.html') : 'profile.html';
          setTimeout(() => {
            window.location.href = redirectParam;
          }, 300);
        } catch (err) {
          showAuthMessage(err.detail || 'Invalid mobile number or password.', 'error');
        } finally {
          if (custBtn) {
            custBtn.disabled = false;
            custBtn.textContent = 'Sign In';
          }
        }
      });
    }

    // 6. Option 2: Admin Login Form
    const adminForm = document.getElementById('admin-login-form');
    const adminPhoneInput = document.getElementById('admin-phone-input');
    const adminPwdInput = document.getElementById('admin-password-input');
    const adminBtn = document.getElementById('admin-login-btn');

    if (adminForm) {
      adminForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearAuthMessage();

        const phoneVal = adminPhoneInput ? adminPhoneInput.value.trim().replace(/\D/g, '') : '';
        const pwdVal = adminPwdInput ? adminPwdInput.value : '';

        if (phoneVal.length !== 10) {
          showAuthMessage('Please enter a valid 10-digit administrator mobile number.', 'error');
          if (adminPhoneInput) adminPhoneInput.focus();
          return;
        }

        if (!pwdVal) {
          showAuthMessage('Please enter your administrator password.', 'error');
          if (adminPwdInput) adminPwdInput.focus();
          return;
        }

        if (adminBtn) {
          adminBtn.disabled = true;
          adminBtn.textContent = 'Authorizing...';
        }

        try {
          const authRes = await window.ShopEasyAuth.adminLogin(phoneVal, pwdVal);
          showAuthMessage('Admin authorized successfully! Redirecting...', 'success');

          const rawRedirect = urlParams.get('redirect');
          const destination = (rawRedirect && rawRedirect.includes('admin/'))
            ? (window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'admin/dashboard.html') : 'admin/dashboard.html')
            : 'admin/dashboard.html';

          setTimeout(() => {
            window.location.href = destination;
          }, 300);
        } catch (err) {
          showAuthMessage(err.detail || 'Invalid administrator credentials.', 'error');
        } finally {
          if (adminBtn) {
            adminBtn.disabled = false;
            adminBtn.textContent = 'Admin Login';
          }
        }
      });
    }

    // 7. Option 3: Customer Registration Form
    const regForm = document.getElementById('register-form');
    const regNameInput = document.getElementById('register-name-input');
    const regPhoneInput = document.getElementById('register-phone-input');
    const regPwdInput = document.getElementById('register-password-input');
    const regConfirmPwdInput = document.getElementById('register-confirm-password-input');
    const regBtn = document.getElementById('register-btn');

    if (regForm) {
      regForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearAuthMessage();

        const nameVal = regNameInput ? regNameInput.value.trim() : '';
        const phoneVal = regPhoneInput ? regPhoneInput.value.trim().replace(/\D/g, '') : '';
        const pwdVal = regPwdInput ? regPwdInput.value : '';
        const confirmVal = regConfirmPwdInput ? regConfirmPwdInput.value : '';

        if (!nameVal) {
          showAuthMessage('Please enter your full legal name.', 'error');
          if (regNameInput) regNameInput.focus();
          return;
        }

        if (phoneVal.length !== 10) {
          showAuthMessage('Please enter a valid 10-digit mobile number.', 'error');
          if (regPhoneInput) regPhoneInput.focus();
          return;
        }

        if (!pwdVal || pwdVal.length < 6) {
          showAuthMessage('Password must be at least 6 characters long.', 'error');
          if (regPwdInput) regPwdInput.focus();
          return;
        }

        if (pwdVal !== confirmVal) {
          showAuthMessage('Confirm password does not match password.', 'error');
          if (regConfirmPwdInput) regConfirmPwdInput.focus();
          return;
        }

        if (regBtn) {
          regBtn.disabled = true;
          regBtn.textContent = 'Creating Account...';
        }

        try {
          await window.ShopEasyAuth.register({
            fullName: nameVal,
            phone: phoneVal,
            password: pwdVal,
            confirmPassword: confirmVal,
          });

          showAuthMessage('Account created successfully! Signing in...', 'success');

          // Log in automatically upon registration
          try {
            await window.ShopEasyAuth.customerLogin(phoneVal, pwdVal);
            const rawRedirect = urlParams.get('redirect');
            const redirectParam = window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'profile.html') : 'profile.html';
            setTimeout(() => {
              window.location.href = redirectParam;
            }, 300);
          } catch (loginErr) {
            // Fallback: switch to customer login tab
            switchTab('customer');
            if (custPhoneInput) custPhoneInput.value = phoneVal;
            showAuthMessage('Account created successfully! Please sign in with your password.', 'success');
          }
        } catch (err) {
          showAuthMessage(err.detail || 'Failed to create account. Please try again.', 'error');
        } finally {
          if (regBtn) {
            regBtn.disabled = false;
            regBtn.textContent = 'Create Account';
          }
        }
      });
    }
  };

})();
