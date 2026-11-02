/**
 * ShopEasy --- Products Catalog & Product Details Logic
 */

// Generate HTML markup for a single product card
function createProductCardMarkup(product) {
  return `
    <article class="product-card" data-product-id="${product.id}">
      <div class="product-card-image-wrap">
        <a href="product-details.html?id=${product.id}">
          <img 
            src="${product.image}" 
            alt="${product.name}" 
            class="product-card-image" 
            loading="lazy"
            onerror="handleImageError(this, '${product.name}')"
          >
        </a>
        ${product.isLatest ? `<span class="product-card-badge">New</span>` : ''}
        ${!product.isLatest && product.isFeatured ? `<span class="product-card-badge">Popular</span>` : ''}
      </div>
      <div class="product-card-body">
        <span class="product-card-category">${product.categoryName}</span>
        <h3 class="product-card-title">
          <a href="product-details.html?id=${product.id}">${product.name}</a>
        </h3>
        <p class="product-card-desc">${product.description}</p>
        <div class="product-card-footer">
          <div class="product-card-price">${formatINR(product.price)}</div>
          <button 
            type="button" 
            class="btn btn-primary btn-sm" 
            onclick="handleQuickAddToCart('${product.id}')"
            aria-label="Add ${product.name} to cart"
          >
            Add to Cart
          </button>
        </div>
      </div>
    </article>
  `;
}

// Quick Add To Cart from Card
function handleQuickAddToCart(productId) {
  addToCart(productId, 1);
}

// ---------------------------------------------------------------------------
// Home Page Renderers
// ---------------------------------------------------------------------------
function initHomePageProducts() {
  const featuredContainer = document.getElementById('featured-products-container');
  if (featuredContainer) {
    const featured = getFeaturedProducts().slice(0, 4);
    featuredContainer.innerHTML = featured.map(createProductCardMarkup).join('');
  }

  const latestContainer = document.getElementById('latest-products-container');
  if (latestContainer) {
    const latest = getLatestProducts().slice(0, 4);
    latestContainer.innerHTML = latest.map(createProductCardMarkup).join('');
  }
}

// ---------------------------------------------------------------------------
// Products Catalog Page (`products.html`)
// ---------------------------------------------------------------------------
let catalogState = {
  searchQuery: '',
  selectedCategory: 'all',
  sortBy: 'featured'
};

function initCatalogPage() {
  const grid = document.getElementById('catalog-products-grid');
  if (!grid) return;

  // Read URL query parameters
  const urlParams = new URLSearchParams(window.location.search);
  const searchParam = urlParams.get('search');
  const catParam = urlParams.get('category');

  if (searchParam) {
    catalogState.searchQuery = searchParam.trim().toLowerCase();
    const searchInput = document.getElementById('catalog-search-input');
    if (searchInput) searchInput.value = searchParam;
  }

  if (catParam) {
    catalogState.selectedCategory = catParam;
  }

  // Setup Event Listeners
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

  // Category Pills
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

  updatePillsActiveState();
  renderFilteredCatalog();
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

  let products = [...getProducts()];

  // Filter by category
  if (catalogState.selectedCategory && catalogState.selectedCategory !== 'all') {
    products = products.filter(p => p.category === catalogState.selectedCategory);
  }

  // Filter by search query
  if (catalogState.searchQuery) {
    products = products.filter(p => 
      p.name.toLowerCase().includes(catalogState.searchQuery) ||
      p.description.toLowerCase().includes(catalogState.searchQuery) ||
      p.categoryName.toLowerCase().includes(catalogState.searchQuery)
    );
  }

  // Sort
  if (catalogState.sortBy === 'price-asc') {
    products.sort((a, b) => a.price - b.price);
  } else if (catalogState.sortBy === 'price-desc') {
    products.sort((a, b) => b.price - a.price);
  } else if (catalogState.sortBy === 'rating') {
    products.sort((a, b) => b.rating - a.rating);
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
        <button class="btn btn-secondary" onclick="resetCatalogFilters()">Reset All Filters</button>
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
// Product Details Page (`product-details.html`)
// ---------------------------------------------------------------------------
function initProductDetailsPage() {
  const container = document.getElementById('product-details-container');
  if (!container) return;

  const urlParams = new URLSearchParams(window.location.search);
  const productId = urlParams.get('id') || 'prod-001';
  const product = getProductById(productId);

  if (!product) {
    container.innerHTML = `
      <div class="empty-state">
        <h2 class="empty-state-title">Product Not Found</h2>
        <p class="empty-state-desc">The product you are looking for does not exist or has been removed.</p>
        <a href="products.html" class="btn btn-primary">Browse All Products</a>
      </div>
    `;
    return;
  }

  // Update Page Title
  document.title = `${product.name} — ShopEasy`;

  const thumbnailsHtml = (product.gallery || [product.image]).map((imgUrl, idx) => `
    <div class="gallery-thumb ${idx === 0 ? 'active' : ''}" onclick="switchDetailImage('${imgUrl}', this)">
      <img src="${imgUrl}" alt="${product.name} view ${idx + 1}" onerror="handleImageError(this, '${product.name}')">
    </div>
  `).join('');

  const featuresHtml = (product.features || []).map(f => `
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
      <a href="products.html?category=${product.category}">${product.categoryName}</a>
      <span>/</span>
      <span style="color:var(--color-text);font-weight:500;">${product.name}</span>
    </nav>

    <div class="product-detail-layout">
      <!-- Gallery Column -->
      <div class="product-gallery">
        <div class="product-gallery-main">
          <img 
            id="detail-main-img" 
            src="${product.image}" 
            alt="${product.name}" 
            class="product-gallery-image"
            onerror="handleImageError(this, '${product.name}')"
          >
        </div>
        <div class="product-gallery-thumbnails">
          ${thumbnailsHtml}
        </div>
      </div>

      <!-- Info Column -->
      <div class="product-info">
        <span class="product-detail-category">${product.categoryName}</span>
        <h1 class="product-detail-title">${product.name}</h1>
        
        <div class="product-detail-price-wrap">
          <span class="product-detail-price">${formatINR(product.price)}</span>
          ${product.originalPrice ? `<span style="font-size:var(--text-lg);color:var(--color-muted);text-decoration:line-through;">${formatINR(product.originalPrice)}</span>` : ''}
          <span class="badge badge-success" style="margin-left:auto;">
            ${product.inStock ? `In Stock (${product.stockCount} available)` : 'Out of Stock'}
          </span>
        </div>

        <p class="product-detail-desc">${product.description}</p>

        <div class="product-detail-meta">
          <div class="meta-row">
            <span class="meta-label">Customer Rating</span>
            <span class="meta-value" style="display:flex;align-items:center;gap:4px;">
              ★ ${product.rating} <span style="font-weight:400;color:var(--color-muted);">(${product.reviewsCount} reviews)</span>
            </span>
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
            <button type="button" class="quantity-btn" onclick="adjustDetailQty(-1)">&minus;</button>
            <input type="text" id="detail-qty-input" class="quantity-input" value="1" readonly>
            <button type="button" class="quantity-btn" onclick="adjustDetailQty(1)">&plus;</button>
          </div>
        </div>

        <div class="product-actions">
          <button 
            type="button" 
            class="btn btn-primary btn-lg" 
            id="detail-add-btn" 
            onclick="addDetailItemToCart('${product.id}')"
          >
            Add to Cart
          </button>
          <a href="cart.html" class="btn btn-secondary btn-lg">View Bag</a>
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
  renderRelatedProducts(product);
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
  addToCart(productId, qty);
}

function renderRelatedProducts(currentProduct) {
  const container = document.getElementById('related-products-container');
  if (!container) return;

  const related = getProducts()
    .filter(p => p.id !== currentProduct.id && p.category === currentProduct.category)
    .slice(0, 4);

  // If fewer than 4 in same category, pad with featured
  let pool = [...related];
  if (pool.length < 4) {
    const others = getProducts().filter(p => p.id !== currentProduct.id && !pool.some(r => r.id === p.id)).slice(0, 4 - pool.length);
    pool = pool.concat(others);
  }

  container.innerHTML = pool.map(createProductCardMarkup).join('');
}

