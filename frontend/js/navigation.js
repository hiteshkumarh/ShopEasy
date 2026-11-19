/**
 * ShopEasy --- Navigation & Mobile Drawer Behavior
 */

document.addEventListener('DOMContentLoaded', () => {
  initNavigation();
  syncCartBadge();
  hydrateNavigationAuth();
});

function hydrateNavigationAuth() {
  if (typeof window === 'undefined') return;

  const adminToken = window.ShopEasyAPI ? window.ShopEasyAPI.getAdminToken() : null;
  const adminUser = window.ShopEasyAPI ? window.ShopEasyAPI.getAdminUser() : null;
  const customerToken = window.ShopEasyAPI ? window.ShopEasyAPI.getCustomerToken() : null;
  const customerUser = window.ShopEasyAPI ? window.ShopEasyAPI.getCustomerUser() : null;

  // 1. Admin Session Hydration across Storefront
  if (adminToken) {
    // Update header account icons
    const accountBtns = document.querySelectorAll(
      'a[title="Customer Account"], a[aria-label="Customer Account"], a[href="login.html"], #nav-account-btn'
    );
    accountBtns.forEach(btn => {
      btn.setAttribute('href', 'admin/dashboard.html');
      btn.setAttribute('title', `Admin Console: ${adminUser?.full_name || 'Admin'}`);
      btn.setAttribute('aria-label', `Admin Console: ${adminUser?.full_name || 'Admin'}`);
    });

    // Update mobile drawer sign-in button
    const drawerLoginBtns = document.querySelectorAll('.mobile-nav-drawer a[href="login.html"]');
    drawerLoginBtns.forEach(btn => {
      btn.setAttribute('href', 'admin/dashboard.html');
      btn.textContent = `Admin Console (${adminUser?.full_name || 'Admin'})`;
    });

    // Render persistent storefront Admin Banner if on a storefront page
    if (!document.getElementById('admin-session-indicator') && !window.location.pathname.includes('/admin/')) {
      const banner = document.createElement('div');
      banner.id = 'admin-session-indicator';
      banner.style.cssText = 'background:#0F172A;color:#F8FAFC;padding:7px 20px;font-size:12px;display:flex;justify-content:space-between;align-items:center;z-index:99999;border-bottom:1px solid #334155;font-family:system-ui,-apple-system,sans-serif;';
      banner.innerHTML = `
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10B981;"></span>
          <span>Logged in as Administrator: <strong>${(adminUser && adminUser.full_name) ? adminUser.full_name : 'Admin'}</strong></span>
        </div>
        <a href="admin/dashboard.html" style="color:#60A5FA;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;gap:4px;">
          <span>&larr; Return to Admin Dashboard</span>
        </a>
      `;
      document.body.insertBefore(banner, document.body.firstChild);
    }
  } else {
    // Ensure any leftover admin banner is purged if no active admin session exists
    const existingBanner = document.getElementById('admin-session-indicator');
    if (existingBanner) {
      existingBanner.remove();
    }

    if (customerToken) {
      // 2. Customer Session Hydration
      const accountBtns = document.querySelectorAll(
        'a[title="Customer Account"], a[aria-label="Customer Account"], a[href="login.html"]'
      );
      accountBtns.forEach(btn => {
        btn.setAttribute('href', 'profile.html');
        btn.setAttribute('title', `Profile (${customerUser?.full_name || 'Customer'})`);
        btn.setAttribute('aria-label', `Profile (${customerUser?.full_name || 'Customer'})`);
      });

      const drawerLoginBtns = document.querySelectorAll('.mobile-nav-drawer a[href="login.html"]');
      drawerLoginBtns.forEach(btn => {
        btn.setAttribute('href', 'profile.html');
        btn.textContent = `My Profile (${customerUser?.full_name || 'Customer'})`;
      });
    }
  }
}

function initNavigation() {
  const toggleBtn = document.querySelector('.mobile-nav-toggle');
  const drawer = document.querySelector('.mobile-nav-drawer');

  if (toggleBtn && drawer) {
    toggleBtn.addEventListener('click', () => {
      const isOpen = drawer.classList.contains('open');
      if (isOpen) {
        drawer.classList.remove('open');
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="3" y1="12" x2="21" y2="12"></line>
            <line x1="3" y1="6" x2="21" y2="6"></line>
            <line x1="3" y1="18" x2="21" y2="18"></line>
          </svg>
        `;
      } else {
        drawer.classList.add('open');
        toggleBtn.setAttribute('aria-expanded', 'true');
        toggleBtn.innerHTML = `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        `;
      }
    });

    // Close drawer when clicking a link
    const drawerLinks = drawer.querySelectorAll('a');
    drawerLinks.forEach(link => {
      link.addEventListener('click', () => {
        drawer.classList.remove('open');
        toggleBtn.setAttribute('aria-expanded', 'false');
      });
    });
  }

  // Highlight active link based on current path
  highlightActiveLink();
}

function highlightActiveLink() {
  const currentPath = window.location.pathname.split('/').pop() || 'index.html';
  const navLinks = document.querySelectorAll('.nav-link, .mobile-nav-link');

  navLinks.forEach(link => {
    const href = link.getAttribute('href');
    if (!href) return;
    const linkPath = href.split('/').pop().split('?')[0];

    if (linkPath === currentPath || (currentPath === '' && linkPath === 'index.html')) {
      link.classList.add('active');
    } else {
      link.classList.remove('active');
    }
  });
}

