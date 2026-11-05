/**
 * ShopEasy --- Products Catalog & Product Details Logic
 * Integrates live customer product catalog with backend FastAPI services:
 * - GET /api/v1/products (paginated active catalog list)
 * - GET /api/v1/products/{id} (individual active product details)
 */

// Generate HTML markup for a single product card
function createProductCardMarkup(product) {
  const imgUrl = product.image_url || product.image || (typeof getPlaceholderImage === 'function' ? getPlaceholderImage(product.name) : '');
  const priceNum = typeof product.price === 'number' ? product.price : (parseFloat(product.price) || 0);
  const formattedPrice = typeof formatINR === 'function' ? formatINR(priceNum) : ('₹' + priceNum.toLocaleString('en-IN'));
  const categoryName = product.categoryName || (product.is_power_bank ? 'Electronics' : 'Collection');
  const stockCount = product.stock !== undefined ? product.stock : (product.stockCount !== undefined ? product.stockCount : 1);
  const isOutOfStock = stockCount <= 0;
  const safeName = (product.name || 'Product').replace(/'/g, "\\'");

  return `
    <article class="product-card" data-product-id="${product.id}">
      <div class="product-card-image-wrap">
        <a href="product-details.html?id=${product.id}">
          <img
            src="${imgUrl}"
            alt="${product.name || 'Product'}"
            class="product-card-image"
            loading="lazy"
            onerror="handleImageError(this, '${safeName}')"
          >
        </a>
        ${product.is_power_bank ? `<span class="product-card-badge">Power Bank</span>` : ''}
        ${product.isLatest ? `<span class="product-card-badge">New</span>` : ''}
        ${!product.isLatest && product.isFeatured ? `<span class="product-card-badge">Popular</span>` : ''}
        ${isOutOfStock ? `<span class="product-card-badge" style="background:var(--color-danger);top:auto;bottom:10px;">Out of Stock</span>` : ''}
      </div>
      <div class="product-card-body">
        <span class="product-card-category">${categoryName}</span>
        <h3 class="product-card-title">
          <a href="product-details.html?id=${product.id}">${product.name || 'Product'}</a>
        </h3>
        <p class="product-card-desc">${product.description || ''}</p>
        <div class="product-card-footer">
          <div class="product-card-price">${formattedPrice}</div>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            onclick="handleQuickAddToCart('${product.id}')"
            aria-label="Add ${product.name || 'Product'} to cart"
            ${isOutOfStock ? 'disabled style="opacity:0.6;cursor:not-allowed;"' : ''}
          >
            ${isOutOfStock ? 'Sold Out' : 'Add to Cart'}
          </button>
        </div>
      </div>
    </article>
  `;
}

// Quick Add To Cart from Card
function handleQuickAddToCart(productId) {
  if (typeof addToCart === 'function') {
    addToCart(productId, 1);
  }
}

// ---------------------------------------------------------------------------
// 1. Home Page Renderers (`index.html`)
// ---------------------------------------------------------------------------
async function initHomePageProducts() {
  const featuredContainer = document.getElementById('featured-products-container');
  const latestContainer = document.getElementById('latest-products-container');
  const browseCta = document.getElementById('browse-catalog-cta');
  const latestSection = document.querySelector('.latest-section');
  if (!featuredContainer && !latestContainer) return;

  // Determine authentication state (Customer or Admin session)
  const isCustomerAuth = Boolean(window.ShopEasyAPI && typeof window.ShopEasyAPI.getCustomerToken === 'function' && window.ShopEasyAPI.getCustomerToken());
  const isAdminAuth = Boolean(window.ShopEasyAPI && typeof window.ShopEasyAPI.getAdminToken === 'function' && window.ShopEasyAPI.getAdminToken());
  let hasLocalToken = false;
  try {
    const cust = localStorage.getItem('shopeasy_customer_token');
    const adm = localStorage.getItem('shopeasy_admin_token') || sessionStorage.getItem('shopeasy_admin_token');
    hasLocalToken = Boolean(cust || adm);
  } catch (e) {
    hasLocalToken = false;
  }
  const isAuthenticated = isCustomerAuth || isAdminAuth || hasLocalToken;

  // If user is not logged in, remove product cards and show member sign-in call-to-action
  if (!isAuthenticated) {
    if (browseCta) {
      browseCta.style.display = 'none';
    }
    if (latestSection) {
      latestSection.style.display = 'none';
    }

    if (featuredContainer) {
      featuredContainer.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-10) var(--space-4); text-align: center; max-width: 480px; margin: 0 auto;">
          <div style="width: 52px; height: 52px; border-radius: 50%; background: var(--color-surface-hover, #f1f5f9); display: inline-flex; align-items: center; justify-content: center; margin: 0 auto var(--space-4); color: var(--color-primary);">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 26px; height: 26px;">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
          </div>
          <h3 class="empty-state-title" style="font-size: var(--text-lg); font-weight: 600; margin-bottom: var(--space-2);">Sign In to View Products</h3>
          <p class="empty-state-desc" style="font-size: var(--text-sm); color: var(--color-muted); margin-bottom: var(--space-6); line-height: 1.5;">
            Our featured essentials and member pricing are exclusively visible to authenticated members. Please sign in or register to explore.
          </p>
          <div style="display: flex; gap: var(--space-3); justify-content: center; flex-wrap: wrap;">
            <a href="login.html" class="btn btn-primary btn-sm">Sign In</a>
            <a href="login.html?tab=register" class="btn btn-secondary btn-sm">Create Account</a>
          </div>
        </div>
      `;
    }
    if (latestContainer) {
      latestContainer.innerHTML = '';
    }
    return;
  }

  // User is authenticated: restore sections
  if (browseCta) {
    browseCta.style.display = 'block';
  }
  if (latestSection) {
    latestSection.style.display = 'block';
  }

  const showLoading = (container) => {
    if (container) {
      container.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-8);">
          <div class="spinner" style="width:32px;height:32px;border:3px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto var(--space-3);"></div>
          <p style="color:var(--color-muted);font-size:var(--text-sm);">Loading products from catalog...</p>
        </div>
      `;
    }
  };

  showLoading(featuredContainer);
  showLoading(latestContainer);

  let products = [];
  try {
    if (window.ShopEasyProducts) {
      const res = await window.ShopEasyProducts.list({ page: 1, page_size: 12 });
      products = (res && Array.isArray(res.items)) ? res.items : [];
    } else {
      products = typeof getProducts === 'function' ? getProducts() : [];
    }
  } catch (err) {
    console.error('Failed to load homepage products from API:', err);
    const renderError = (container) => {
      if (container) {
        container.innerHTML = `
          <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-8);">
            <h3 class="empty-state-title" style="font-size:var(--text-base);color:var(--color-error);">Unable to load products</h3>
            <p class="empty-state-desc" style="font-size:var(--text-xs);margin-bottom:var(--space-4);">${err.detail || 'Please check your connection and try again.'}</p>
            <button type="button" class="btn btn-secondary btn-sm" onclick="initHomePageProducts()">Retry</button>
          </div>
        `;
      }
    };
    renderError(featuredContainer);
    renderError(latestContainer);
    return;
  }

  if (products.length === 0) {
    const renderEmpty = (container, label) => {
      if (container) {
        container.innerHTML = `
          <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-8);">
            <p style="color:var(--color-muted);font-size:var(--text-sm);">No ${label} available yet.</p>
          </div>
        `;
      }
    };
    renderEmpty(featuredContainer, 'featured products');
    renderEmpty(latestContainer, 'latest products');
    return;
  }

  if (featuredContainer) {
    const featured = products.slice(0, 4);
    featuredContainer.innerHTML = featured.map(createProductCardMarkup).join('');
  }

  if (latestContainer) {
    const latest = products.length > 4 ? products.slice(4, 8) : products.slice(0, 4);
    latestContainer.innerHTML = latest.map(createProductCardMarkup).join('');
  }
}

// ---------------------------------------------------------------------------
// 2. Products Catalog Page (`products.html`)
// ---------------------------------------------------------------------------
let catalogState = {
  searchQuery: '',
  selectedCategory: 'all',
  sortBy: 'featured',
  page: 1,
  pageSize: 20
};

let liveCatalogProducts = [];
let catalogListenersBound = false;

async function initCatalogPage() {
  const grid = document.getElementById('catalog-products-grid');
  const countEl = document.getElementById('catalog-results-count');
  if (!grid) return;

  // Read URL query parameters
  const urlParams = new URLSearchParams(window.location.search);
  const searchParam = urlParams.get('search');
  const catParam = urlParams.get('category');
  const pageParam = urlParams.get('page');

  if (searchParam) {
    catalogState.searchQuery = searchParam.trim().toLowerCase();
    const searchInput = document.getElementById('catalog-search-input');
    if (searchInput) searchInput.value = searchParam;
  }

  if (catParam) {
    catalogState.selectedCategory = catParam;
  }

  if (pageParam) {
    const p = parseInt(pageParam, 10);
    if (!isNaN(p) && p >= 1) catalogState.page = p;
  }

  // Setup Event Listeners
  setupCatalogListeners();

  // Show loading state
  grid.innerHTML = `
    <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-12);">
      <div class="spinner" style="width:36px;height:36px;border:3px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto var(--space-4);"></div>
      <p style="color:var(--color-muted);">Loading catalog products...</p>
    </div>
  `;
  if (countEl) countEl.textContent = 'Loading products...';

  try {
    if (window.ShopEasyProducts) {
      const res = await window.ShopEasyProducts.list({ page: catalogState.page, page_size: 100 });
      liveCatalogProducts = (res && Array.isArray(res.items)) ? res.items : [];
    } else {
      liveCatalogProducts = typeof getProducts === 'function' ? getProducts() : [];
    }
  } catch (err) {
    console.error('Failed to load catalog from API:', err);
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-12);">
        <h3 class="empty-state-title" style="color:var(--color-error);">Unable to load catalog</h3>
        <p class="empty-state-desc">${err.detail || err.message || 'Unable to communicate with the catalog service.'}</p>
        <button type="button" class="btn btn-secondary" onclick="initCatalogPage()">Retry</button>
      </div>
    `;
    if (countEl) countEl.textContent = 'Failed to load products';
    return;
  }

  updatePillsActiveState();
  renderFilteredCatalog();
}

function setupCatalogListeners() {
  if (catalogListenersBound) return;
  catalogListenersBound = true;

  const searchInput = document.getElementById('catalog-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      catalogState.searchQuery = e.target.value.trim().toLowerCase();
      renderFilteredCatalog();
    });
  }

  const categorySelect = document.getElementById('catalog-category-select');
  if (categorySelect) {
    categorySelect.value = catalogState.selectedCategory;
    categorySelect.addEventListener('change', (e) => {
      catalogState.selectedCategory = e.target.value;
      updatePillsActiveState();
      renderFilteredCatalog();
    });
  }

  const sortSelect = document.getElementById('catalog-sort-select');
  if (sortSelect) {
    sortSelect.addEventListener('change', (e) => {
      catalogState.sortBy = e.target.value;
      renderFilteredCatalog();
    });
  }

  const pills = document.querySelectorAll('.category-pill');
  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.getAttribute('data-category');
      catalogState.selectedCategory = cat;
      if (categorySelect) categorySelect.value = cat;
      updatePillsActiveState();
      renderFilteredCatalog();
    });
  });
}

function updatePillsActiveState() {
  const pills = document.querySelectorAll('.category-pill');
  pills.forEach(pill => {
    const cat = pill.getAttribute('data-category');
    if (cat === catalogState.selectedCategory) {
      pill.classList.add('active');
    } else {
      pill.classList.remove('active');
    }
  });
}

function renderFilteredCatalog() {
  const grid = document.getElementById('catalog-products-grid');
  const countEl = document.getElementById('catalog-results-count');
  if (!grid) return;

  let products = [...liveCatalogProducts];

  // Filter by category
  if (catalogState.selectedCategory && catalogState.selectedCategory !== 'all') {
    products = products.filter(p => {
      const cat = p.category || (p.is_power_bank ? 'electronics' : 'general');
      return cat === catalogState.selectedCategory;
    });
  }

  // Filter by search query
  if (catalogState.searchQuery) {
    const q = catalogState.searchQuery;
    products = products.filter(p => {
      const name = (p.name || '').toLowerCase();
      const desc = (p.description || '').toLowerCase();
      const code = (p.product_code || '').toLowerCase();
      return name.includes(q) || desc.includes(q) || code.includes(q);
    });
  }

  // Sort
  if (catalogState.sortBy === 'price-asc') {
    products.sort((a, b) => (parseFloat(a.price) || 0) - (parseFloat(b.price) || 0));
  } else if (catalogState.sortBy === 'price-desc') {
    products.sort((a, b) => (parseFloat(b.price) || 0) - (parseFloat(a.price) || 0));
  } else if (catalogState.sortBy === 'name') {
    products.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  }

  if (countEl) {
    countEl.textContent = `Showing ${products.length} product${products.length === 1 ? '' : 's'}`;
  }

  if (products.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="11" cy="11" r="8"/>
          <line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <h3 class="empty-state-title">No products found</h3>
        <p class="empty-state-desc">Try adjusting your search criteria or resetting filters to see available products.</p>
        <button type="button" class="btn btn-secondary" onclick="resetCatalogFilters()">Reset All Filters</button>
      </div>
    `;
    return;
  }

  grid.innerHTML = products.map(createProductCardMarkup).join('');
}

function resetCatalogFilters() {
  catalogState.searchQuery = '';
  catalogState.selectedCategory = 'all';
  catalogState.sortBy = 'featured';

  const searchInput = document.getElementById('catalog-search-input');
  if (searchInput) searchInput.value = '';

  const categorySelect = document.getElementById('catalog-category-select');
  if (categorySelect) categorySelect.value = 'all';

  const sortSelect = document.getElementById('catalog-sort-select');
  if (sortSelect) sortSelect.value = 'featured';

  updatePillsActiveState();
  renderFilteredCatalog();
}

// ---------------------------------------------------------------------------
// 3. Product Details Page (`product-details.html`)
// ---------------------------------------------------------------------------
async function initProductDetailsPage() {
  const container = document.getElementById('product-details-container');
  if (!container) return;

  const urlParams = new URLSearchParams(window.location.search);
  const rawId = urlParams.get('id');

  if (!rawId) {
    container.innerHTML = `
      <div class="empty-state">
        <h2 class="empty-state-title">No Product Specified</h2>
        <p class="empty-state-desc">Please choose a product from our catalog to view its details.</p>
        <a href="products.html" class="btn btn-primary">Browse All Products</a>
      </div>
    `;
    return;
  }

  // Show loading state
  container.innerHTML = `
    <div class="empty-state" style="padding:var(--space-16);">
      <div class="spinner" style="width:40px;height:40px;border:3px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto var(--space-4);"></div>
      <p style="color:var(--color-muted);">Loading product details...</p>
    </div>
  `;

  let product = null;
  try {
    if (window.ShopEasyProducts) {
      product = await window.ShopEasyProducts.getById(rawId);
    } else {
      product = typeof getProductById === 'function' ? getProductById(rawId) : null;
    }
  } catch (err) {
    console.error('Failed to fetch product details:', err);
    container.innerHTML = `
      <div class="empty-state">
        <h2 class="empty-state-title">Product Not Found</h2>
        <p class="empty-state-desc">${err.status === 404 ? 'The product you are looking for does not exist or has been removed from the catalog.' : (err.detail || 'Unable to load product details.')}</p>
        <a href="products.html" class="btn btn-primary">Browse All Products</a>
      </div>
    `;
    return;
  }

  if (!product) {
    container.innerHTML = `
      <div class="empty-state">
        <h2 class="empty-state-title">Product Not Found</h2>
        <p class="empty-state-desc">The product you are looking for does not exist or has been removed from the catalog.</p>
        <a href="products.html" class="btn btn-primary">Browse All Products</a>
      </div>
    `;
    return;
  }

  // Update Page Title
  document.title = `${product.name} — ShopEasy`;

  const imgUrl = product.image_url || product.image || (typeof getPlaceholderImage === 'function' ? getPlaceholderImage(product.name) : '');
  const priceNum = typeof product.price === 'number' ? product.price : (parseFloat(product.price) || 0);
  const formattedPrice = typeof formatINR === 'function' ? formatINR(priceNum) : ('₹' + priceNum.toLocaleString('en-IN'));
  const categoryName = product.categoryName || (product.is_power_bank ? 'Electronics' : 'Collection');
  const stockCount = product.stock !== undefined ? product.stock : (product.stockCount !== undefined ? product.stockCount : 1);
  const inStock = stockCount > 0;
  const safeName = (product.name || 'Product').replace(/'/g, "\\'");

  const galleryList = (Array.isArray(product.gallery) && product.gallery.length > 0) ? product.gallery : [imgUrl];
  const thumbnailsHtml = galleryList.map((thumbUrl, idx) => `
    <div class="gallery-thumb ${idx === 0 ? 'active' : ''}" onclick="switchDetailImage('${thumbUrl}', this)">
      <img src="${thumbUrl}" alt="${product.name} view ${idx + 1}" onerror="handleImageError(this, '${safeName}')">
    </div>
  `).join('');

  const features = Array.isArray(product.features) ? product.features : [
    product.is_power_bank ? '20,000mAh High Capacity Fast Charging with Dual USB-C' : 'Crafted with premium durable materials',
    product.product_code ? `Catalog SKU: ${product.product_code}` : 'Verified ShopEasy Authenticity Guarantee',
    'Pan-India Fast Dispatch & 100% Genuine Quality'
  ];

  const featuresHtml = features.map(f => `
    <li class="feature-item">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
      <span>${f}</span>
    </li>
  `).join('');

  container.innerHTML = `
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="index.html">Home</a>
      <span>/</span>
      <a href="products.html">Shop</a>
      <span>/</span>
      <span style="color:var(--color-text);font-weight:500;">${product.name}</span>
    </nav>

    <div class="product-detail-layout">
      <!-- Gallery Column -->
      <div class="product-gallery">
        <div class="product-gallery-main">
          <img
            id="detail-main-img"
            src="${imgUrl}"
            alt="${product.name}"
            class="product-gallery-image"
            onerror="handleImageError(this, '${safeName}')"
          >
        </div>
        ${galleryList.length > 1 ? `<div class="product-gallery-thumbnails">${thumbnailsHtml}</div>` : ''}
      </div>

      <!-- Info Column -->
      <div class="product-info">
        <span class="product-detail-category">${categoryName}</span>
        <h1 class="product-detail-title">${product.name}</h1>

        <div class="product-detail-price-wrap">
          <span class="product-detail-price">${formattedPrice}</span>
          <span class="badge ${inStock ? 'badge-success' : 'badge-danger'}" style="margin-left:auto;">
            ${inStock ? `In Stock (${stockCount} available)` : 'Out of Stock'}
          </span>
        </div>

        <p class="product-detail-desc">${product.description || 'No detailed description provided for this catalog item.'}</p>

        <div class="product-detail-meta">
          <div class="meta-row">
            <span class="meta-label">Product SKU</span>
            <span class="meta-value" style="font-family:var(--font-mono);">${product.product_code || `PROD-${product.id}`}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Shipping</span>
            <span class="meta-value">Free delivery on orders over ₹1,999</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">Authenticity</span>
            <span class="meta-value">100% Genuine product guaranteed</span>
          </div>
        </div>

        <!-- Quantity & Add to Cart -->
        <div style="margin-bottom:var(--space-4);">
          <label style="display:block;font-size:var(--text-sm);font-weight:500;margin-bottom:var(--space-2);">Quantity</label>
          <div class="quantity-control">
            <button type="button" class="quantity-btn" onclick="adjustDetailQty(-1)" ${!inStock ? 'disabled' : ''}>&minus;</button>
            <input type="text" id="detail-qty-input" class="quantity-input" value="1" readonly>
            <button type="button" class="quantity-btn" onclick="adjustDetailQty(1)" ${!inStock ? 'disabled' : ''}>&plus;</button>
          </div>
        </div>

        <div class="product-actions">
          <button
            type="button"
            class="btn btn-primary btn-lg"
            id="detail-add-btn"
            onclick="addDetailItemToCart('${product.id}')"
            ${!inStock ? 'disabled style="opacity:0.6;cursor:not-allowed;"' : ''}
          >
            ${inStock ? 'Add to Cart' : 'Currently Unavailable'}
          </button>
          <a href="products.html" class="btn btn-secondary btn-lg">Browse More</a>
        </div>

        <!-- Key Features -->
        <div class="product-features">
          <h2 class="product-features-title">Highlights</h2>
          <ul class="features-list">
            ${featuresHtml}
          </ul>
        </div>
      </div>
    </div>
  `;

  // Render Related Products
  await renderRelatedProducts(product);
}

function switchDetailImage(url, thumbEl) {
  const mainImg = document.getElementById('detail-main-img');
  if (mainImg) mainImg.src = url;

  const thumbs = document.querySelectorAll('.gallery-thumb');
  thumbs.forEach(t => t.classList.remove('active'));
  if (thumbEl) thumbEl.classList.add('active');
}

function adjustDetailQty(delta) {
  const input = document.getElementById('detail-qty-input');
  if (!input) return;
  let val = parseInt(input.value, 10) || 1;
  val = Math.max(1, Math.min(10, val + delta));
  input.value = val;
}

function addDetailItemToCart(productId) {
  const input = document.getElementById('detail-qty-input');
  const qty = input ? parseInt(input.value, 10) || 1 : 1;
  if (typeof addToCart === 'function') {
    addToCart(productId, qty);
  }
}

async function renderRelatedProducts(currentProduct) {
  const container = document.getElementById('related-products-container');
  if (!container) return;

  try {
    let pool = [];
    if (window.ShopEasyProducts) {
      const res = await window.ShopEasyProducts.list({ page: 1, page_size: 8 });
      const items = (res && Array.isArray(res.items)) ? res.items : [];
      pool = items.filter(p => p.id !== currentProduct.id);
    }
    if (pool.length === 0) {
      const section = container.closest('.related-products-section');
      if (section) section.style.display = 'none';
      return;
    }
    container.innerHTML = pool.slice(0, 4).map(createProductCardMarkup).join('');
  } catch (e) {
    const section = container.closest('.related-products-section');
    if (section) section.style.display = 'none';
  }
}

// Global browser exports
window.initHomePageProducts = initHomePageProducts;
window.initCatalogPage = initCatalogPage;
window.initProductDetailsPage = initProductDetailsPage;
window.createProductCardMarkup = createProductCardMarkup;
window.handleQuickAddToCart = handleQuickAddToCart;
window.switchDetailImage = switchDetailImage;
window.adjustDetailQty = adjustDetailQty;
window.addDetailItemToCart = addDetailItemToCart;
window.resetCatalogFilters = resetCatalogFilters;
