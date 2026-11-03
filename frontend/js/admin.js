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
// Mock Admin Session & Navigation
// ---------------------------------------------------------------------------
function getAdminSession() {
  try {
    const raw = sessionStorage.getItem(ADMIN_SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function ensureMockAdminSession() {
  let session = getAdminSession();
  if (!session) {
    // Prototype convenience: provide default mock admin session for viewing admin UI
    session = {
      role: 'admin',
      phone: '+91 98000 00000',
      name: 'System Admin',
      authenticated: true,
      referral_code: null, // Invariant: Admin never has referral code
      referred_by: null
    };
    try {
      sessionStorage.setItem(ADMIN_SESSION_KEY, JSON.stringify(session));
    } catch (e) {}
  }
  return session;
}

function adminLogout() {
  try {
    sessionStorage.removeItem(ADMIN_SESSION_KEY);
  } catch (e) {}
  window.location.href = 'login.html';
}

function initAdminShell() {
  ensureMockAdminSession();

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
}

// ---------------------------------------------------------------------------
// Admin Products Storage (localStorage)
// ---------------------------------------------------------------------------
function getCategoryFallbackImage(category, name) {
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
  return 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800&auto=format&fit=crop&q=80';
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

function getAdminProducts() {
  try {
    const raw = localStorage.getItem(ADMIN_PRODUCTS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch (e) {
    console.error('Error reading admin products from localStorage', e);
  }

  // Fallback to SHOP_PRODUCTS from data.js
  const initial = (typeof SHOP_PRODUCTS !== 'undefined') ? JSON.parse(JSON.stringify(SHOP_PRODUCTS)) : [];
  saveAdminProducts(initial);
  return initial;
}

function saveAdminProducts(products) {
  if (!Array.isArray(products)) {
    console.error('saveAdminProducts: products must be an array');
    return false;
  }

  try {
    localStorage.setItem(ADMIN_PRODUCTS_KEY, JSON.stringify(products));
    return true;
  } catch (e) {
    console.warn('Direct saveAdminProducts exceeded quota or failed; attempting fallback sanitization...', e);

    // Emergency sanitization: replace oversized base64 strings with lightweight fallbacks
    try {
      const sanitized = products.map(p => {
        const copy = Object.assign({}, p);
        if (typeof copy.image === 'string' && copy.image.startsWith('data:image/') && copy.image.length > 40000) {
          copy.image = getCategoryFallbackImage(copy.category, copy.name);
        }
        if (Array.isArray(copy.gallery)) {
          copy.gallery = copy.gallery.map(g => {
            if (typeof g === 'string' && g.startsWith('data:image/') && g.length > 20000) {
              return copy.image;
            }
            return g;
          });
        }
        return copy;
      });

      localStorage.setItem(ADMIN_PRODUCTS_KEY, JSON.stringify(sanitized));
      console.log('Saved admin products successfully after sanitizing oversized images.');
      return true;
    } catch (fallbackErr) {
      console.error('Critical failure: Could not save admin products to localStorage', fallbackErr);
      return false;
    }
  }
}

function getAdminProductById(id) {
  const products = getAdminProducts();
  return products.find(p => p.id === id);
}

function deleteAdminProduct(id) {
  let products = getAdminProducts();
  const prod = products.find(p => p.id === id);
  const name = prod ? prod.name : 'Product';

  if (!confirm(`Are you sure you want to delete "${name}"? This action cannot be undone.`)) {
    return;
  }

  products = products.filter(p => p.id !== id);
  saveAdminProducts(products);

  // Re-render table without re-binding input listeners
  renderAdminProductsTable();
}

// ---------------------------------------------------------------------------
// 1. Admin Login Page
// ---------------------------------------------------------------------------
function initAdminLogin() {
  const phoneForm = document.getElementById('admin-phone-form');
  const otpForm = document.getElementById('admin-otp-form');
  const phoneStep = document.getElementById('admin-phone-step');
  const otpStep = document.getElementById('admin-otp-step');
  const phoneInput = document.getElementById('admin-phone-input');
  const displayPhone = document.getElementById('admin-display-phone');

  if (!phoneForm || !otpForm) return;

  let currentPhone = '';

  phoneForm.addEventListener('submit', (e) => {
    e.preventDefault();
    clearAdminMessage();

    const rawPhone = phoneInput.value.trim().replace(/\D/g, '');
    if (rawPhone.length !== 10) {
      showAdminMessage('Please enter a valid 10-digit mobile number.', 'error');
      phoneInput.focus();
      return;
    }

    currentPhone = rawPhone;
    if (displayPhone) {
      displayPhone.textContent = `+91 ${rawPhone.slice(0, 5)} ${rawPhone.slice(5)}`;
    }

    const sendBtn = document.getElementById('admin-send-otp-btn');
    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.textContent = 'Requesting OTP...';
    }

    setTimeout(() => {
      phoneStep.style.display = 'none';
      otpStep.classList.add('active');
      setupAdminOtpBoxes();
      showAdminMessage(`Development OTP code generated for +91 ${currentPhone}.`, 'success');
      if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send OTP';
      }
    }, 600);
  });

  otpForm.addEventListener('submit', (e) => {
    e.preventDefault();
    clearAdminMessage();

    const boxes = document.querySelectorAll('.admin-otp-box');
    let code = '';
    boxes.forEach(box => code += box.value.trim());

    if (code.length < 6) {
      showAdminMessage('Please enter the complete 6-digit OTP code.', 'error');
      return;
    }

    const verifyBtn = document.getElementById('admin-verify-btn');
    if (verifyBtn) {
      verifyBtn.disabled = true;
      verifyBtn.textContent = 'Verifying Credentials...';
    }

    setTimeout(() => {
      // Invariant: Admin role has strictly NO referral code
      const adminSession = {
        role: 'admin',
        phone: `+91 ${currentPhone}`,
        name: 'System Admin',
        authenticated: true,
        authenticatedAt: new Date().toISOString(),
        referral_code: null,
        referred_by: null
      };

      try {
        sessionStorage.setItem(ADMIN_SESSION_KEY, JSON.stringify(adminSession));
      } catch (err) {}

      showAdminMessage('Verification successful. Administrator access authorized.', 'success');

      if (verifyBtn) {
        verifyBtn.textContent = 'Access Authorized ✓';
        verifyBtn.classList.remove('btn-primary');
        verifyBtn.classList.add('btn-secondary');
      }

      setTimeout(() => {
        window.location.href = 'dashboard.html';
      }, 700);
    }, 700);
  });
}

function setupAdminOtpBoxes() {
  const boxes = document.querySelectorAll('.admin-otp-box');
  if (boxes.length === 0) return;
  boxes[0].focus();

  boxes.forEach((box, index) => {
    box.addEventListener('input', (e) => {
      const val = e.target.value.replace(/\D/g, '');
      box.value = val ? val[val.length - 1] : '';
      if (box.value && index < boxes.length - 1) {
        boxes[index + 1].focus();
      }
    });

    box.addEventListener('keydown', (e) => {
      if (e.key === 'Backspace' && !box.value && index > 0) {
        boxes[index - 1].focus();
      }
    });

    box.addEventListener('paste', (e) => {
      e.preventDefault();
      const pasteText = (e.clipboardData || window.clipboardData).getData('text').replace(/\D/g, '').slice(0, 6);
      if (pasteText) {
        for (let i = 0; i < pasteText.length; i++) {
          if (boxes[i]) boxes[i].value = pasteText[i];
        }
        const nextIdx = Math.min(pasteText.length, boxes.length - 1);
        boxes[nextIdx].focus();
      }
    });
  });
}

function handleAdminResendOtp() {
  clearAdminMessage();
  const boxes = document.querySelectorAll('.admin-otp-box');
  boxes.forEach(b => b.value = '');
  if (boxes[0]) boxes[0].focus();
  showAdminMessage('A new development OTP code has been generated.', 'success');
}

function showAdminMessage(msg, type = 'error') {
  const banner = document.getElementById('admin-message-banner');
  if (!banner) return;
  banner.textContent = msg;
  banner.className = `admin-message-banner ${type}`;
}

function clearAdminMessage() {
  const banner = document.getElementById('admin-message-banner');
  if (!banner) return;
  banner.textContent = '';
  banner.className = 'admin-message-banner';
}

// ---------------------------------------------------------------------------
// 2. Admin Dashboard Overview
// ---------------------------------------------------------------------------
function initAdminDashboard() {
  initAdminShell();

  const products = getAdminProducts();

  // Orders source
  let orders = [];
  try {
    const raw = localStorage.getItem('shopeasy_orders');
    orders = raw ? JSON.parse(raw) : ((typeof MOCK_ORDERS !== 'undefined') ? MOCK_ORDERS : []);
  } catch (e) {
    orders = (typeof MOCK_ORDERS !== 'undefined') ? MOCK_ORDERS : [];
  }

  // Calculate Metrics
  const totalProducts = products.length;
  const totalOrders = orders.length;
  const totalCustomers = 18; // Realistic prototype sample
  const totalRevenue = orders.reduce((sum, o) => sum + (o.total || 0), 0);

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
    if (orders.length === 0) {
      ordersTableBody.innerHTML = `
        <tr>
          <td colspan="5" style="text-align:center;padding:var(--space-6);color:var(--color-muted);">
            No orders recorded yet.
          </td>
        </tr>
      `;
    } else {
      ordersTableBody.innerHTML = orders.slice(0, 5).map(o => {
        const itemNames = (o.items || []).map(i => `${i.name} (x${i.quantity})`).join(', ') || 'Custom Items';
        return `
          <tr>
            <td><strong style="font-family:var(--font-mono);">${o.id}</strong></td>
            <td>Aarav Mehta</td>
            <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${itemNames}">${itemNames}</td>
            <td><strong>${formatCurrency(o.total)}</strong></td>
            <td><span class="badge ${o.statusClass || 'badge-primary'}">${o.status}</span></td>
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

function initAdminProductsPage() {
  initAdminShell();

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

  renderAdminProductsTable();
}

function renderAdminProductsTable() {
  const tbody = document.getElementById('admin-products-table-body');
  const countEl = document.getElementById('admin-products-count');
  if (!tbody) return;

  let products = getAdminProducts();

  // Search filter
  if (adminCatalogState.search) {
    const query = adminCatalogState.search;
    products = products.filter(p => 
      (p.name && p.name.toLowerCase().includes(query)) ||
      (p.id && p.id.toLowerCase().includes(query)) ||
      (p.categoryName && p.categoryName.toLowerCase().includes(query)) ||
      (p.category && p.category.toLowerCase().includes(query)) ||
      (p.description && p.description.toLowerCase().includes(query))
    );
  }

  // Category filter
  if (adminCatalogState.category && adminCatalogState.category !== 'all') {
    products = products.filter(p => p.category === adminCatalogState.category);
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
    const stockBadge = p.stockCount > 10 
      ? `<span class="badge badge-success">${p.stockCount} in stock</span>`
      : p.stockCount > 0 
        ? `<span class="badge badge-warning">${p.stockCount} low stock</span>`
        : `<span class="badge badge-danger">Out of stock</span>`;

    const displayImg = p.image || getCategoryFallbackImage(p.category, p.name);

    return `
      <tr>
        <td>
          <div class="table-product-cell">
            <img 
              src="${displayImg}" 
              alt="${p.name || 'Product'}" 
              class="table-product-thumb"
              onerror="this.src='https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=200';"
            >
            <div class="table-product-info">
              <span class="table-product-name">${p.name || 'Untitled Product'}</span>
              <span class="table-product-id">${p.id || ''}</span>
            </div>
          </div>
        </td>
        <td><span class="badge badge-muted">${p.categoryName || p.category || 'General'}</span></td>
        <td><strong>${formatCurrency(p.price || 0)}</strong></td>
        <td>${stockBadge}</td>
        <td>
          <span class="badge ${p.inStock !== false ? 'badge-primary' : 'badge-muted'}">
            ${p.inStock !== false ? 'Active' : 'Inactive'}
          </span>
        </td>
        <td>
          <div class="table-actions">
            <a href="product-form.html?id=${p.id}" class="table-action-btn" title="Edit product">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
              Edit
            </a>
            <button type="button" class="table-action-btn delete" onclick="deleteAdminProduct('${p.id}')" title="Delete product">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px;"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
              Delete
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
function initProductForm() {
  initAdminShell();

  const urlParams = new URLSearchParams(window.location.search);
  const editId = urlParams.get('id');

  const pageTitle = document.getElementById('form-page-title');
  const form = document.getElementById('admin-product-form');
  const previewImg = document.getElementById('product-image-preview');
  const previewPlaceholder = document.getElementById('image-preview-placeholder');
  const imageFileInput = document.getElementById('product-image-file');
  const imageUrlInput = document.getElementById('product-image-url');
  const hintEl = document.getElementById('image-upload-hint');

  let editingProduct = null;
  let isOptimizingImage = false;
  let optimizedImageData = '';

  if (editId) {
    editingProduct = getAdminProductById(editId);
    if (editingProduct) {
      if (pageTitle) pageTitle.textContent = `Edit Product — ${editingProduct.name}`;
      document.title = `Edit Product — ShopEasy Admin`;

      document.getElementById('product-name').value = editingProduct.name;
      document.getElementById('product-category').value = editingProduct.category;
      document.getElementById('product-price').value = editingProduct.price;
      document.getElementById('product-stock').value = editingProduct.stockCount;
      document.getElementById('product-status').value = editingProduct.inStock !== false ? 'active' : 'inactive';
      document.getElementById('product-description').value = editingProduct.description || '';
      
      if (editingProduct.image) {
        if (imageUrlInput && !editingProduct.image.startsWith('data:image/')) {
          imageUrlInput.value = editingProduct.image;
        }
        setPreviewImage(editingProduct.image);
      }
    }
  }

  // Handle Image File selection -> Downscale & compress for fast storage
  if (imageFileInput) {
    imageFileInput.addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      const submitBtn = form ? form.querySelector('button[type="submit"]') : null;

      try {
        isOptimizingImage = true;
        if (hintEl) {
          hintEl.textContent = 'Optimizing image for catalog storage...';
          hintEl.style.color = 'var(--color-primary)';
        }
        if (submitBtn) {
          submitBtn.disabled = true;
        }

        const compressed = await compressImageFile(file, 600, 600, 0.8);
        if (compressed) {
          optimizedImageData = compressed;
          setPreviewImage(compressed);
          if (hintEl) {
            hintEl.textContent = 'Image optimized and ready for catalog save.';
            hintEl.style.color = 'var(--color-success)';
          }
        }
      } catch (err) {
        console.error('Image compression error', err);
      } finally {
        isOptimizingImage = false;
        if (submitBtn) {
          submitBtn.disabled = false;
        }
      }
    });
  }

  // Handle Image URL input -> Live preview
  if (imageUrlInput) {
    imageUrlInput.addEventListener('input', (e) => {
      const url = e.target.value.trim();
      if (url) {
        optimizedImageData = ''; // Reset file data if user enters URL
        setPreviewImage(url);
      }
    });
  }

  function setPreviewImage(src) {
    if (previewImg && previewPlaceholder) {
      previewImg.src = src;
      previewImg.style.display = 'block';
      previewPlaceholder.style.display = 'none';
    }
  }

  // Form Submit (Save Product)
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      clearAdminMessage();

      if (isOptimizingImage) {
        showAdminMessage('Please wait while your selected image finishes optimizing...', 'error');
        return;
      }

      const nameInput = document.getElementById('product-name');
      const categoryInput = document.getElementById('product-category');
      const priceInput = document.getElementById('product-price');
      const stockInput = document.getElementById('product-stock');
      const statusInput = document.getElementById('product-status');
      const descInput = document.getElementById('product-description');

      const name = nameInput ? nameInput.value.trim() : '';
      const category = categoryInput ? categoryInput.value : 'electronics';
      const priceVal = priceInput ? priceInput.value.trim() : '';
      const stockVal = stockInput ? stockInput.value.trim() : '';
      const status = statusInput ? statusInput.value : 'active';
      const description = descInput ? descInput.value.trim() : '';

      // Validation
      if (!name) {
        showAdminMessage('Please enter a product name.', 'error');
        if (nameInput) nameInput.focus();
        return;
      }
      const price = parseFloat(priceVal);
      if (isNaN(price) || price < 0) {
        showAdminMessage('Please enter a valid price in INR.', 'error');
        if (priceInput) priceInput.focus();
        return;
      }
      const stock = parseInt(stockVal, 10);
      if (isNaN(stock) || stock < 0) {
        showAdminMessage('Please enter a valid stock quantity.', 'error');
        if (stockInput) stockInput.focus();
        return;
      }

      let image = optimizedImageData ||
        (imageUrlInput ? imageUrlInput.value.trim() : '') ||
        (previewImg && previewImg.src && previewImg.style.display !== 'none' ? previewImg.src : '');

      if (!image) {
        image = getCategoryFallbackImage(category, name);
      }

      const categoryNames = {
        'electronics': 'Electronics',
        'fashion': 'Fashion',
        'accessories': 'Accessories',
        'home': 'Home & Living',
        'beauty': 'Beauty'
      };

      const products = getAdminProducts();

      if (editingProduct) {
        // Update existing product without creating duplicates
        const idx = products.findIndex(p => p.id === editingProduct.id);
        if (idx > -1) {
          products[idx] = Object.assign({}, products[idx], {
            name: name,
            category: category,
            categoryName: categoryNames[category] || category,
            price: price,
            stockCount: stock,
            inStock: status === 'active',
            description: description,
            image: image,
            gallery: [image]
          });
        }
      } else {
        // Generate clean sequential ID avoiding collisions
        let maxNum = 12;
        products.forEach(p => {
          if (p.id) {
            const m = String(p.id).match(/^prod-(\d+)$/);
            if (m) {
              const num = parseInt(m[1], 10);
              if (num > maxNum) maxNum = num;
            }
          }
        });
        const newId = `prod-${String(maxNum + 1).padStart(3, '0')}`;

        const newProd = {
          id: newId,
          name: name,
          category: category,
          categoryName: categoryNames[category] || category,
          price: price,
          originalPrice: Math.round(price * 1.25),
          rating: 5.0,
          reviewsCount: 1,
          inStock: status === 'active',
          stockCount: stock,
          isFeatured: false,
          isLatest: true,
          image: image,
          gallery: [image],
          description: description,
          features: ['Carefully designed with premium materials']
        };

        products.unshift(newProd);
      }

      const saved = saveAdminProducts(products);
      if (!saved) {
        showAdminMessage('Could not save product to local storage. Storage quota exceeded.', 'error');
        return;
      }

      showAdminMessage('Product saved successfully. Redirecting to catalog...', 'success');
      if (typeof alert === 'function') {
        try {
          alert('Product saved successfully.');
        } catch (alertErr) {}
      }
      window.location.href = 'products.html';
    });
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatCurrency(amount) {
  if (typeof amount !== 'number') return '₹0';
  return '₹' + amount.toLocaleString('en-IN');
}
