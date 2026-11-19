/**
 * ShopEasy --- Shopping Cart Logic
 * Integrates persistent shopping cart with backend FastAPI services:
 * - GET /api/v1/cart (fetch live cart and database-calculated totals)
 * - POST /api/v1/cart (add product or increment quantity)
 * - PUT /api/v1/cart/{item_id} (update item quantity)
 * - DELETE /api/v1/cart/{item_id} (remove item from cart)
 * - DELETE /api/v1/cart (clear customer cart)
 */

let cachedCart = null;

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Fetch live cart from backend
async function fetchCart() {
  if (!window.ShopEasyAPI || !window.ShopEasyAPI.getCustomerToken()) {
    cachedCart = { items: [], total_items: 0, subtotal: 0 };
    syncCartBadge();
    return cachedCart;
  }
  try {
    const res = await window.ShopEasyCart.get();
    cachedCart = res;
    syncCartBadge();
    return cachedCart;
  } catch (err) {
    if (err && (err.status === 401 || err.statusCode === 401)) {
      if (window.ShopEasyAPI && typeof window.ShopEasyAPI.clearCustomerToken === 'function') {
        window.ShopEasyAPI.clearCustomerToken();
      }
    } else {
      console.error('Error fetching cart from backend:', err);
    }
    cachedCart = { items: [], total_items: 0, subtotal: 0 };
    syncCartBadge();
    return cachedCart;
  }
}

// Add item to cart
async function addToCart(productId, quantity = 1) {
  if (!window.ShopEasyAPI || !window.ShopEasyAPI.getCustomerToken()) {
    if (typeof showToast === 'function') {
      showToast('Please sign in to add products to your bag.', 'error');
    }
    const currentPath = window.location.pathname.split('/').pop() || 'products.html';
    const redirectUrl = `login.html?redirect=${encodeURIComponent(currentPath)}`;
    setTimeout(() => {
      window.location.href = redirectUrl;
    }, 800);
    return false;
  }

  const pId = parseInt(productId, 10);
  const qty = parseInt(quantity, 10) || 1;

  try {
    const res = await window.ShopEasyCart.addItem(pId, qty);
    cachedCart = res;
    syncCartBadge();
    const addedItem = (res.items || []).find(i => i.product_id === pId);
    const prodName = addedItem ? addedItem.product_name : 'Product';
    if (typeof showToast === 'function') {
      showToast(`Added "${prodName}" to your shopping bag.`);
    }
    window.dispatchEvent(new CustomEvent('cart-updated', { detail: { cart: res } }));
    return true;
  } catch (err) {
    if (err && (err.status === 401 || err.statusCode === 401)) {
      if (window.ShopEasyAPI && typeof window.ShopEasyAPI.clearCustomerToken === 'function') {
        window.ShopEasyAPI.clearCustomerToken();
      }
      if (typeof showToast === 'function') {
        showToast('Your session has expired. Please sign in again.', 'error');
      }
      const currentPath = window.location.pathname.split('/').pop() || 'products.html';
      setTimeout(() => {
        window.location.href = `login.html?redirect=${encodeURIComponent(currentPath)}`;
      }, 500);
      return false;
    }
    if (typeof showToast === 'function') {
      showToast(err.detail || err.message || 'Failed to add item to bag.', 'error');
    }
    return false;
  }
}

// Update quantity
async function updateCartQuantity(itemId, quantity) {
  const iId = parseInt(itemId, 10);
  const qty = parseInt(quantity, 10);

  if (qty <= 0) {
    await removeFromCart(iId);
    return;
  }

  try {
    const res = await window.ShopEasyCart.updateItem(iId, qty);
    cachedCart = res;
    syncCartBadge();
    await renderCartPage();
    window.dispatchEvent(new CustomEvent('cart-updated', { detail: { cart: res } }));
  } catch (err) {
    if (typeof showToast === 'function') {
      showToast(err.detail || err.message || 'Failed to update quantity.', 'error');
    }
    await renderCartPage();
  }
}

// Remove item from cart
async function removeFromCart(itemId) {
  const iId = parseInt(itemId, 10);
  try {
    const res = await window.ShopEasyCart.removeItem(iId);
    cachedCart = res;
    syncCartBadge();
    if (typeof showToast === 'function') {
      showToast('Item removed from your bag.');
    }
    await renderCartPage();
    window.dispatchEvent(new CustomEvent('cart-updated', { detail: { cart: res } }));
  } catch (err) {
    if (typeof showToast === 'function') {
      showToast(err.detail || err.message || 'Failed to remove item.', 'error');
    }
    await renderCartPage();
  }
}

// Clear entire cart
async function clearCart() {
  try {
    await window.ShopEasyCart.clear();
    cachedCart = { items: [], total_items: 0, subtotal: 0 };
    syncCartBadge();
    if (typeof showToast === 'function') {
      showToast('Shopping bag cleared.');
    }
    await renderCartPage();
    window.dispatchEvent(new CustomEvent('cart-updated', { detail: { cart: cachedCart } }));
  } catch (err) {
    if (typeof showToast === 'function') {
      showToast(err.detail || err.message || 'Failed to clear bag.', 'error');
    }
  }
}

// Synchronize badge on header
function syncCartBadge() {
  const count = cachedCart ? (cachedCart.total_items || 0) : 0;
  const badges = document.querySelectorAll('.cart-badge');
  badges.forEach(badge => {
    badge.textContent = count;
    if (count > 0) {
      badge.style.display = 'flex';
      badge.classList.remove('bump');
      void badge.offsetWidth; // Trigger reflow
      badge.classList.add('bump');
    } else {
      badge.style.display = 'none';
    }
  });
}

// Render the Cart Page (`cart.html`)
async function renderCartPage() {
  const container = document.getElementById('cart-content-container');
  if (!container) return;

  // Show loading state
  container.innerHTML = `
    <div class="empty-state" style="padding:var(--space-12);">
      <div class="spinner" style="width:36px;height:36px;border:3px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin 0.8s linear infinite;margin:0 auto var(--space-4);"></div>
      <p style="color:var(--color-muted);">Loading your shopping bag...</p>
    </div>
  `;

  if (!window.ShopEasyAPI || !window.ShopEasyAPI.getCustomerToken()) {
    container.innerHTML = `
      <div class="empty-state cart-empty-state">
        <div class="cart-empty-icon-wrap">
          <svg class="cart-empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
          </svg>
        </div>
        <h2 class="cart-empty-title">Sign In to View Your Bag</h2>
        <p class="cart-empty-desc">Your shopping bag is associated with your customer account. Sign in or register to review items and proceed to checkout.</p>
        <div class="cart-empty-actions">
          <a href="login.html?redirect=cart.html" class="btn btn-primary btn-lg">Sign In / Register</a>
          <a href="products.html" class="btn btn-secondary btn-lg">Browse Products</a>
        </div>
      </div>
    `;
    return;
  }

  try {
    const cart = await window.ShopEasyCart.get();
    cachedCart = cart;
    syncCartBadge();

    if (!cart.items || cart.items.length === 0) {
      container.innerHTML = `
        <div class="empty-state cart-empty-state">
          <div class="cart-empty-icon-wrap">
            <svg class="cart-empty-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="9" cy="21" r="1"/>
              <circle cx="20" cy="21" r="1"/>
              <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
            </svg>
          </div>
          <h2 class="cart-empty-title">Your Bag is Empty</h2>
          <p class="cart-empty-desc">Explore our verified catalog to discover products and qualify for referral rewards.</p>
          <div class="cart-empty-actions">
            <a href="products.html" class="btn btn-primary btn-lg">Explore Products</a>
            <a href="orders.html" class="btn btn-secondary btn-lg">View Past Orders</a>
          </div>
        </div>
      `;
      return;
    }

    const subtotal = parseFloat(cart.subtotal) || 0;
    const shipping = subtotal > 1999 ? 0 : 99; // Free shipping above ₹1,999
    const total = subtotal + shipping;
    const freeShippingRemaining = Math.max(0, 2000 - subtotal);

    const itemsHtml = cart.items.map(item => {
      const itemTotal = parseFloat(item.line_total) || (parseFloat(item.unit_price) * item.quantity);
      const displayImg = item.image_url || 'assets/products/placeholder.svg';
      const safeName = (item.product_name || 'Product').replace(/'/g, "\\'");

      return `
        <div class="cart-item" data-item-id="${item.id}">
          <div class="cart-item-image-wrap">
            <img
              src="${displayImg}"
              alt="${escapeHtml(item.product_name)}"
              class="cart-item-image"
              onerror="if(window.handleImageError){window.handleImageError(this, '${safeName}');}else{this.src='https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=200';}"
            >
            ${item.is_power_bank ? `<span class="cart-item-tag">Plan A Eligible</span>` : ''}
          </div>
          <div class="cart-item-details">
            <div class="cart-item-header">
              <span class="cart-item-category">${item.is_power_bank ? '⚡ Arya Power Bank' : 'Verified Retail Product'}</span>
              <a href="product-details.html?id=${item.product_id}" class="cart-item-title">${escapeHtml(item.product_name)}</a>
            </div>
            <div class="cart-item-meta">
              <span class="cart-item-unit-price">${formatINR(parseFloat(item.unit_price))} <span class="unit-label">each</span></span>
              ${item.stock <= 5 ? `<span class="cart-stock-warning">Only ${item.stock} left in stock</span>` : `<span class="cart-stock-in">In Stock</span>`}
            </div>
          </div>
          <div class="cart-item-actions">
            <div class="cart-item-total-block">
              <span class="cart-item-total-label">Subtotal</span>
              <span class="cart-item-total">${formatINR(itemTotal)}</span>
            </div>
            <div class="apple-cart-pill-selector quantity-control" role="group" aria-label="Item quantity selector">
              <button
                type="button"
                class="apple-cart-pill-btn apple-cart-pill-minus quantity-btn"
                onclick="handleCartQtyChange(${item.id}, ${item.quantity - 1})"
                aria-label="Decrease quantity"
                ${item.quantity <= 1 ? 'disabled' : ''}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </button>
              <div class="apple-cart-pill-display">
                <input
                  type="text"
                  inputmode="numeric"
                  pattern="[0-9]*"
                  class="apple-cart-pill-value quantity-input"
                  id="cart-qty-input-${item.id}"
                  value="${item.quantity}"
                  data-item-id="${item.id}"
                  data-stock="${item.stock}"
                  data-current-qty="${item.quantity}"
                  aria-label="Quantity for ${escapeHtml(item.product_name)}"
                  autocomplete="off"
                  onfocus="this.select()"
                  onkeydown="handleCartQtyKeydown(event, ${item.id}, ${item.stock}, ${item.quantity})"
                  onblur="handleCartQtyBlur(event, ${item.id}, ${item.stock}, ${item.quantity})"
                />
              </div>
              <button
                type="button"
                class="apple-cart-pill-btn apple-cart-pill-plus quantity-btn"
                onclick="handleCartQtyChange(${item.id}, ${item.quantity + 1})"
                aria-label="Increase quantity"
                ${item.quantity >= item.stock ? 'disabled' : ''}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </button>
            </div>
            <button
              type="button"
              class="cart-item-remove"
              onclick="handleCartRemove(${item.id})"
              aria-label="Remove ${escapeHtml(item.product_name)} from bag"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              </svg>
              <span>Remove</span>
            </button>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = `
      <div class="cart-layout">
        <div class="cart-main-col">
          <div class="cart-items-card">
            ${itemsHtml}
          </div>
          <div class="cart-footer-actions">
            <a href="products.html" class="btn btn-secondary btn-sm cart-continue-btn">&larr; Continue Shopping</a>
            <button type="button" class="btn btn-subtle btn-sm cart-clear-btn" onclick="clearCart()">
              Clear Entire Bag
            </button>
          </div>
        </div>
        <div class="cart-sidebar-col">
          <div class="summary-card">
            <h2 class="summary-title">Order Summary</h2>
            
            <div class="summary-shipping-pill ${shipping === 0 ? 'qualified' : ''}">
              ${shipping === 0 
                ? `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                   <span>You've unlocked <strong>FREE Standard Delivery</strong>!</span>`
                : `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                   <span>Add <strong>${formatINR(freeShippingRemaining)}</strong> more for <strong>FREE Delivery</strong></span>`
              }
            </div>

            <div class="summary-rows-group">
              <div class="summary-row">
                <span>Subtotal (${cart.total_items} ${cart.total_items === 1 ? 'item' : 'items'})</span>
                <span class="summary-val">${formatINR(subtotal)}</span>
              </div>
              <div class="summary-row">
                <span>Standard Shipping</span>
                <span class="summary-val">${shipping === 0 ? '<strong style="color:var(--color-success)">FREE</strong>' : formatINR(shipping)}</span>
              </div>
              <div class="summary-row total">
                <span>Total Amount</span>
                <span class="summary-total-val">${formatINR(total)}</span>
              </div>
            </div>

            <a href="checkout.html" class="btn btn-primary btn-block btn-lg cart-checkout-cta">
              <span>Proceed to Checkout</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="5" y1="12" x2="19" y2="12"></line>
                <polyline points="12 5 19 12 12 19"></polyline>
              </svg>
            </a>

            <div class="summary-badges">
              <div class="summary-badge-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                <span>Bank-grade 256-bit encrypted checkout</span>
              </div>
              <div class="summary-badge-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                <span>100% Genuine Arya Verified Products</span>
              </div>
              <div class="summary-badge-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                <span>Instant referral credit &amp; cycle tracking</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    console.error('Failed to render cart page:', err);
    container.innerHTML = `
      <div class="empty-state" style="padding:var(--space-12);">
        <h3 class="empty-state-title" style="color:var(--color-danger);">Unable to load shopping bag</h3>
        <p class="empty-state-desc">${escapeHtml(err.detail || err.message || 'Please check your connection and try again.')}</p>
        <button type="button" class="btn btn-secondary" onclick="renderCartPage()">Retry</button>
      </div>
    `;
  }
}

// Global click and direct input handlers for inline events in cart
function handleCartQtyChange(itemId, newQty) {
  updateCartQuantity(itemId, newQty);
}

function handleCartRemove(itemId) {
  removeFromCart(itemId);
}

// Validate and apply manual quantity input
function applyDirectQuantity(inputEl, itemId, stock, currentQty) {
  if (!inputEl) return;
  if (inputEl._isUpdating) return;

  const rawVal = inputEl.value.trim();

  // 1. Empty input -> restore previous quantity
  if (rawVal === '') {
    inputEl.value = currentQty;
    if (typeof showToast === 'function') {
      showToast('Quantity cannot be empty. Restored previous quantity.', 'error');
    }
    return;
  }

  // 2. Reject non-numeric, decimals, negative numbers
  if (!/^\d+$/.test(rawVal)) {
    inputEl.value = currentQty;
    if (typeof showToast === 'function') {
      showToast('Please enter a valid positive whole number.', 'error');
    }
    return;
  }

  const parsedQty = parseInt(rawVal, 10);

  // 3. Reject zero or negative
  if (parsedQty <= 0) {
    inputEl.value = currentQty;
    if (typeof showToast === 'function') {
      showToast('Quantity must be at least 1. To remove an item, click Remove.', 'error');
    }
    return;
  }

  // 4. Enforce stock limit
  const maxStock = parseInt(stock, 10) || 999999;
  if (parsedQty > maxStock) {
    inputEl.value = currentQty;
    if (typeof showToast === 'function') {
      showToast(`Only ${maxStock} ${maxStock === 1 ? 'unit is' : 'units are'} currently available in stock.`, 'error');
    }
    return;
  }

  // 5. If quantity has not changed, keep current value
  if (parsedQty === parseInt(currentQty, 10)) {
    inputEl.value = currentQty;
    return;
  }

  // 6. Valid quantity change -> update cart
  inputEl._isUpdating = true;
  updateCartQuantity(itemId, parsedQty);
}

function handleCartQtyKeydown(event, itemId, stock, currentQty) {
  if (event.key === 'Enter') {
    event.preventDefault();
    event.stopPropagation();
    const inputEl = event.target;
    applyDirectQuantity(inputEl, itemId, stock, currentQty);
    inputEl.blur();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    event.target.value = currentQty;
    event.target.blur();
  }
}

function handleCartQtyBlur(event, itemId, stock, currentQty) {
  const inputEl = event.target;
  applyDirectQuantity(inputEl, itemId, stock, currentQty);
}

// Synchronous getters using cached state if needed
function getCart() {
  return cachedCart ? (cachedCart.items || []) : [];
}

function getCartCount() {
  return cachedCart ? (cachedCart.total_items || 0) : 0;
}

function getCartSubtotal() {
  return cachedCart ? (parseFloat(cachedCart.subtotal) || 0) : 0;
}

// Initialize badge on startup
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    fetchCart();
  });
}

// Listen to cart update event
window.addEventListener('cart-updated', syncCartBadge);

// Window Exports
window.getCart = getCart;
window.getCartCount = getCartCount;
window.getCartSubtotal = getCartSubtotal;
window.addToCart = addToCart;
window.updateCartQuantity = updateCartQuantity;
window.removeFromCart = removeFromCart;
window.clearCart = clearCart;
window.syncCartBadge = syncCartBadge;
window.renderCartPage = renderCartPage;
window.handleCartQtyChange = handleCartQtyChange;
window.handleCartRemove = handleCartRemove;
window.handleCartQtyKeydown = handleCartQtyKeydown;
window.handleCartQtyBlur = handleCartQtyBlur;
window.applyDirectQuantity = applyDirectQuantity;
window.fetchCart = fetchCart;
