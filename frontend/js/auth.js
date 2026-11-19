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
  // Tab Switching Helpers (Supports: customer, distributor, register, admin)
  // -------------------------------------------------------------------------
  function switchTab(tabName) {
    clearAuthMessage();
    const validTabs = ['customer', 'distributor', 'register', 'admin'];
    const activeTab = validTabs.includes(tabName) ? tabName : 'customer';

    const tabs = document.querySelectorAll('.auth-tab');
    const panels = document.querySelectorAll('.auth-panel');

    tabs.forEach(t => {
      const isTarget = t.dataset.tab === activeTab;
      t.classList.toggle('active', isTarget);
      t.setAttribute('aria-selected', isTarget ? 'true' : 'false');
      if (isTarget && typeof t.scrollIntoView === 'function') {
        try {
          t.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        } catch (_) {}
      }
    });

    panels.forEach(p => {
      p.classList.remove('active');
    });

    const targetPanel = document.getElementById(`panel-${activeTab}`);
    if (targetPanel) {
      targetPanel.classList.add('active');
    }
  }

  window.switchTab = switchTab;

  // Harmless backward-compatibility stubs
  window.switchCustomerOtpStep = function () {};
  window.handleResendOtp = function () {};

  // -------------------------------------------------------------------------
  // Password Visibility Toggle Helpers
  // -------------------------------------------------------------------------
  function initPasswordToggles() {
    const toggleBtns = document.querySelectorAll('.password-toggle-btn');
    toggleBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const targetId = btn.dataset.target;
        if (!targetId) return;
        const input = document.getElementById(targetId);
        if (!input) return;

        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';

        const eyeOpen = btn.querySelector('.eye-open');
        const eyeOff = btn.querySelector('.eye-off');

        if (isPassword) {
          if (eyeOpen) eyeOpen.style.display = 'none';
          if (eyeOff) eyeOff.style.display = 'block';
          btn.setAttribute('aria-label', 'Hide password');
          btn.setAttribute('title', 'Hide password');
          btn.setAttribute('aria-pressed', 'true');
        } else {
          if (eyeOpen) eyeOpen.style.display = 'block';
          if (eyeOff) eyeOff.style.display = 'none';
          btn.setAttribute('aria-label', 'Show password');
          btn.setAttribute('title', 'Show password');
          btn.setAttribute('aria-pressed', 'false');
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // Main Login Page Initializer
  // -------------------------------------------------------------------------
  window.initLoginPage = function () {
    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab') || 'customer';

    // 1. Check if user is already authenticated
    const customerToken = window.ShopEasyAPI ? window.ShopEasyAPI.getCustomerToken() : null;
    const adminToken = window.ShopEasyAPI ? window.ShopEasyAPI.getAdminToken() : null;
    const redirectParam = urlParams.get('redirect');

    // If an authenticated admin arrives via redirect or explicit admin tab navigation
    if (adminToken) {
      if (redirectParam && redirectParam.includes('admin/')) {
        if (window.redirectIfAdminAuthenticated) {
          window.redirectIfAdminAuthenticated(redirectParam);
          return;
        }
      }
      if (initialTab === 'admin') {
        if (window.redirectIfAdminAuthenticated) {
          window.redirectIfAdminAuthenticated('admin/dashboard.html');
          return;
        }
      }
    }

    if (initialTab === 'admin') {
      if (adminToken && window.redirectIfAdminAuthenticated) {
        window.redirectIfAdminAuthenticated('admin/dashboard.html');
        return;
      }
    } else {
      if (customerToken && window.redirectIfCustomerAuthenticated) {
        window.redirectIfCustomerAuthenticated('profile.html');
        return;
      }
    }

    // 2. Set Initial Active Tab
    switchTab(initialTab);

    // 3. Initialize Password Visibility Toggles
    initPasswordToggles();

    // 4. Ensure all phone fields load completely empty
    const phoneInputIds = [
      'customer-phone-input',
      'distributor-phone-input',
      'register-phone-input',
      'admin-phone-input'
    ];
    phoneInputIds.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });

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

    const linkGoToDistributor = document.getElementById('link-go-to-distributor');
    if (linkGoToDistributor) {
      linkGoToDistributor.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab('distributor');
      });
    }

    // -----------------------------------------------------------------------
    // Programme Selection Step Logic (RG-01)
    // -----------------------------------------------------------------------
    let selectedProgramme = null;
    const programmeCards = document.querySelectorAll('.programme-card');
    const proceedRegBtn = document.getElementById('btn-proceed-registration');
    const progSelectionStep = document.getElementById('programme-selection-step');
    const regFormStep = document.getElementById('registration-form-step');
    const selectedProgDisplay = document.getElementById('selected-programme-display');
    const changeProgBtn = document.getElementById('btn-change-programme');
    const hiddenProgInput = document.getElementById('register-programme-input');

    programmeCards.forEach(card => {
      card.addEventListener('click', () => {
        programmeCards.forEach(c => {
          c.classList.remove('selected');
          c.setAttribute('aria-checked', 'false');
        });
        card.classList.add('selected');
        card.setAttribute('aria-checked', 'true');
        selectedProgramme = card.dataset.programme;
        if (proceedRegBtn) {
          proceedRegBtn.disabled = false;
        }
      });
    });

    if (proceedRegBtn) {
      proceedRegBtn.addEventListener('click', () => {
        if (!selectedProgramme) {
          showAuthMessage('Please select either Plan A or Plan B before proceeding.', 'error');
          return;
        }
        clearAuthMessage();
        if (progSelectionStep) progSelectionStep.style.display = 'none';
        if (regFormStep) regFormStep.style.display = 'block';

        if (hiddenProgInput) {
          hiddenProgInput.value = selectedProgramme;
        }

        if (selectedProgDisplay) {
          const label = selectedProgramme === 'PLAN_B'
            ? 'Plan B (Arya Generation Growth Programme)'
            : 'Plan A (Arya Business Partner Programme)';
          selectedProgDisplay.textContent = `Selected: ${label}`;
        }
      });
    }

    if (changeProgBtn) {
      changeProgBtn.addEventListener('click', () => {
        if (regFormStep) regFormStep.style.display = 'none';
        if (progSelectionStep) progSelectionStep.style.display = 'block';
        clearAuthMessage();
      });
    }

    // -----------------------------------------------------------------------
    // Panel 1: Plan A Customer Password Login Form
    // -----------------------------------------------------------------------
    const custForm = document.getElementById('customer-login-form');
    const custPhoneInput = document.getElementById('customer-phone-input');
    const custPwdInput = document.getElementById('customer-password-input');
    const custBtn = document.getElementById('customer-login-btn');

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
          const authRes = await window.ShopEasyAuth.customerLogin(phoneVal, pwdVal, 'PLAN_A');
          showAuthMessage('Signed in to Plan A successfully! Redirecting...', 'success');

          const rawRedirect = urlParams.get('redirect');
          const redirectParam = window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'dashboard.html') : 'dashboard.html';
          setTimeout(() => {
            window.location.href = redirectParam;
          }, 350);
        } catch (err) {
          showAuthMessage(err.detail || 'Invalid mobile number or password for Plan A.', 'error');
        } finally {
          if (custBtn) {
            custBtn.disabled = false;
            custBtn.textContent = 'Sign In to Plan A';
          }
        }
      });
    }

    // -----------------------------------------------------------------------
    // Panel 2: Plan B Distributor Password Login Form (RG-12)
    // -----------------------------------------------------------------------
    const distForm = document.getElementById('distributor-login-form');
    const distPhoneInput = document.getElementById('distributor-phone-input');
    const distPwdInput = document.getElementById('distributor-password-input');
    const distBtn = document.getElementById('distributor-login-btn');

    if (distForm) {
      distForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        clearAuthMessage();

        const phoneVal = distPhoneInput ? distPhoneInput.value.trim().replace(/\D/g, '') : '';
        const pwdVal = distPwdInput ? distPwdInput.value : '';

        if (phoneVal.length !== 10) {
          showAuthMessage('Please enter a valid 10-digit distributor mobile number.', 'error');
          if (distPhoneInput) distPhoneInput.focus();
          return;
        }

        if (!pwdVal) {
          showAuthMessage('Please enter your distributor password.', 'error');
          if (distPwdInput) distPwdInput.focus();
          return;
        }

        if (distBtn) {
          distBtn.disabled = true;
          distBtn.textContent = 'Signing In...';
        }

        try {
          const authRes = await window.ShopEasyAuth.distributorLogin(phoneVal, pwdVal);
          showAuthMessage('Signed in to Plan B distributor portal! Redirecting...', 'success');

          const rawRedirect = urlParams.get('redirect');
          const redirectParam = window.ShopEasyAPI ? window.ShopEasyAPI.getSafeRedirectUrl(rawRedirect, 'distributor-dashboard.html') : 'distributor-dashboard.html';
          setTimeout(() => {
            window.location.href = redirectParam;
          }, 350);
        } catch (err) {
          showAuthMessage(err.detail || 'Invalid mobile number or password for Plan B.', 'error');
        } finally {
          if (distBtn) {
            distBtn.disabled = false;
            distBtn.textContent = 'Sign In to Plan B';
          }
        }
      });
    }

    // -----------------------------------------------------------------------
    // Panel 3: Registration Form Submission (RG-01)
    // -----------------------------------------------------------------------
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

        const progVal = hiddenProgInput ? hiddenProgInput.value : selectedProgramme;
        const nameVal = regNameInput ? regNameInput.value.trim() : '';
        const phoneVal = regPhoneInput ? regPhoneInput.value.trim().replace(/\D/g, '') : '';
        const pwdVal = regPwdInput ? regPwdInput.value : '';
        const confirmVal = regConfirmPwdInput ? regConfirmPwdInput.value : '';

        if (!progVal) {
          showAuthMessage('Please select either Plan A or Plan B before creating an account.', 'error');
          if (regFormStep) regFormStep.style.display = 'none';
          if (progSelectionStep) progSelectionStep.style.display = 'block';
          return;
        }

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
          showAuthMessage('Passwords do not match. Please re-enter your password confirmation.', 'error');
          if (regConfirmPwdInput) regConfirmPwdInput.focus();
          return;
        }

        if (regBtn) {
          regBtn.disabled = true;
          regBtn.textContent = 'Creating Account...';
        }

        try {
          const res = await window.ShopEasyAuth.register({
            fullName: nameVal,
            phone: phoneVal,
            password: pwdVal,
            confirmPassword: confirmVal,
            programme: progVal,
          });

          // Auto-Login: Hydrate authentication session immediately upon registration
          let authToken = res.access_token;
          if (!authToken && window.ShopEasyAuth) {
            try {
              const loginRes = res.programme === 'PLAN_B'
                ? await window.ShopEasyAuth.distributorLogin(phoneVal, pwdVal)
                : await window.ShopEasyAuth.customerLogin(phoneVal, pwdVal, res.programme);
              authToken = (loginRes && loginRes.token && loginRes.token.access_token) || (loginRes && loginRes.access_token) || null;
            } catch (autoLoginErr) {
              console.warn('Fallback auto-login attempt failed:', autoLoginErr);
            }
          }

          if (authToken && window.ShopEasyAPI) {
            window.ShopEasyAPI.setCustomerToken(authToken);
            window.ShopEasyAPI.setCustomerUser({
              id: res.id,
              full_name: res.full_name,
              phone: res.phone,
              role: res.role,
              programme: res.programme,
              referral_code: res.referral_code,
            });
          }

          showAuthMessage(`Welcome, ${res.full_name}! Registration successful. Redirecting to dashboard...`, 'success');

          // Seamless redirect directly to customer / distributor dashboard (or return URL)
          const urlParams = new URLSearchParams(window.location.search);
          const redirectUrl = urlParams.get('redirect');
          const defaultTarget = res.programme === 'PLAN_B' ? 'distributor-dashboard.html' : 'dashboard.html';
          const destination = redirectUrl || defaultTarget;

          setTimeout(() => {
            window.location.href = destination;
          }, 600);
        } catch (err) {
          showAuthMessage(err.detail || 'Registration failed. Please verify your details.', 'error');
        } finally {
          if (regBtn) {
            regBtn.disabled = false;
            regBtn.textContent = 'Create Account';
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
          }, 350);
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
  };

})();
