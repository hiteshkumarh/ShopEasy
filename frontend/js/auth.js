/**
 * ShopEasy --- Phone & OTP Authentication UI Prototype
 * Simulates phone verification flow. No real SMS or backend integration.
 */

const USER_SESSION_KEY = 'shopeasy_customer_session';

// Get current simulated customer session
function getCurrentCustomer() {
  try {
    const raw = localStorage.getItem(USER_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

// Set simulated session
function setCustomerSession(customer) {
  try {
    localStorage.setItem(USER_SESSION_KEY, JSON.stringify(customer));
  } catch (e) {
    console.error('Failed to set session', e);
  }
}

// Clear customer session
function logoutCustomer() {
  localStorage.removeItem(USER_SESSION_KEY);
  showToast('You have been signed out.');
  setTimeout(() => {
    window.location.href = 'login.html';
  }, 600);
}

// Initialize Login Page
function initLoginPage() {
  const phoneForm = document.getElementById('phone-form');
  const otpForm = document.getElementById('otp-form');
  const phoneStep = document.getElementById('phone-step');
  const otpStep = document.getElementById('otp-step');
  const phoneInput = document.getElementById('phone-number-input');
  const displayPhone = document.getElementById('display-phone-number');

  if (!phoneForm || !otpForm) return;

  let enteredPhone = '';

  // Handle Phone Submit (Send OTP)
  phoneForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const phoneVal = phoneInput.value.trim().replace(/\D/g, '');

    if (phoneVal.length !== 10) {
      showToast('Please enter a valid 10-digit phone number', 'error');
      phoneInput.focus();
      return;
    }

    enteredPhone = phoneVal;
    if (displayPhone) displayPhone.textContent = `+91 ${phoneVal}`;

    const sendBtn = document.getElementById('send-otp-btn');
    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.textContent = 'Sending OTP...';
    }

    // Simulate OTP delivery delay
    setTimeout(() => {
      if (phoneStep) phoneStep.style.display = 'none';
      if (otpStep) {
        otpStep.classList.add('active');
        setupOtpInputs();
      }
      showToast(`Development OTP generated for +91 ${enteredPhone}`);
    }, 600);
  });

  // Handle OTP Submit (Verify OTP)
  otpForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const otpDigits = document.querySelectorAll('.otp-digit');
    let code = '';
    otpDigits.forEach(input => code += input.value.trim());

    if (code.length < 6) {
      showToast('Please enter the full 6-digit OTP code', 'error');
      return;
    }

    const verifyBtn = document.getElementById('verify-otp-btn');
    if (verifyBtn) {
      verifyBtn.disabled = true;
      verifyBtn.textContent = 'Verifying...';
    }

    // Simulate verification delay
    setTimeout(() => {
      setCustomerSession({
        phone: `+91 ${enteredPhone}`,
        name: 'ShopEasy Customer',
        role: 'customer',
        memberSince: 'Today',
        loggedIn: true
      });

      showToast('Successfully signed in!');
      
      const redirect = new URLSearchParams(window.location.search).get('redirect') || 'profile.html';
      setTimeout(() => {
        window.location.href = redirect;
      }, 700);
    }, 700);
  });
}

// Setup auto-advancing 6-digit OTP boxes
function setupOtpInputs() {
  const digits = document.querySelectorAll('.otp-digit');
  if (digits.length === 0) return;

  digits[0].focus();

  digits.forEach((input, index) => {
    input.addEventListener('input', (e) => {
      const val = e.target.value.replace(/\D/g, '');
      input.value = val ? val[val.length - 1] : '';

      if (input.value && index < digits.length - 1) {
        digits[index + 1].focus();
      }
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !input.value && index > 0) {
        digits[index - 1].focus();
      }
    });

    // Handle paste event
    input.addEventListener('paste', (e) => {
      e.preventDefault();
      const pasteData = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g, '').slice(0, 6);
      if (pasteData) {
        for (let i = 0; i < pasteData.length; i++) {
          if (digits[i]) digits[i].value = pasteData[i];
        }
        const nextIndex = Math.min(pasteData.length, digits.length - 1);
        digits[nextIndex].focus();
      }
    });
  });
}

// Resend OTP simulation
function handleResendOtp() {
  const digits = document.querySelectorAll('.otp-digit');
  digits.forEach(d => d.value = '');
  if (digits[0]) digits[0].focus();
  showToast('A new development OTP code has been sent');
}

