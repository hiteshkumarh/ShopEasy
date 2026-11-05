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
    console.error('Error fetching cart from backend:', err);
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
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
          <circle cx="12" cy="7" r="4"></circle>
        </svg>
        <h2 class="empty-state-title">Sign In to View Your Bag</h2>
        <p class="empty-state-desc">Your shopping bag is associated with your customer account. Sign in or register to review items and proceed to checkout.</p>
        <a href="login.html?redirect=cart.html" class="btn btn-primary btn-lg">Sign In / Register</a>
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
        <div class="empty-state">
          <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="9" cy="21" r="1"/>
            <circle cx="20" cy="21" r="1"/>
            <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
          </svg>
          <h2 class="empty-state-title">Your Bag is Empty</h2>
          <p class="empty-state-desc">Explore our verified catalog to discover products and qualify for referral rewards.</p>
          <a href="products.html" class="btn btn-primary btn-lg">Explore Products</a>
        </div>
      `;
      return;
    }

    const subtotal = parseFloat(cart.subtotal) || 0;
    const shipping = subtotal > 1999 ? 0 : 99; // Free shipping above ₹1,999
    const total = subtotal + shipping;

    const itemsHtml = cart.items.map(item => {
      const itemTotal = parseFloat(item.line_total) || (parseFloat(item.unit_price) * item.quantity);
      const displayImg = item.image_url || 'assets/products/placeholder.svg';
      const safeName = (item.product_name || 'Product').replace(/'/g, "\\'");

      return `
        <div class="cart-item" data-item-id="${item.id}">
          <img
            src="${displayImg}"
            alt="${escapeHtml(item.product_name)}"
            class="cart-item-image"
            onerror="if(window.handleImageError){window.handleImageError(this, '${safeName}');}else{this.src='https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=200';}"
          >
          <div class="cart-item-details">
            <span class="cart-item-category">${item.is_power_bank ? 'Power Bank' : 'Product'}</span>
            <a href="product-details.html?id=${item.product_id}" class="cart-item-title">${escapeHtml(item.product_name)}</a>
            <span class="cart-item-price">${formatINR(parseFloat(item.unit_price))} each</span>
            ${item.stock <= 5 ? `<span style="font-size:var(--text-xs);color:var(--color-warning);font-weight:500;">Only ${item.stock} left in stock</span>` : ''}
          </div>
          <div class="cart-item-actions">
            <div class="cart-item-total">${formatINR(itemTotal)}</div>
            <div class="quantity-control">
              <button
                type="button"
                class="quantity-btn"
                onclick="handleCartQtyChange(${item.id}, ${item.quantity - 1})"
                aria-label="Decrease quantity"
              >&minus;</button>
              <input
                type="text"
                class="quantity-input"
                value="${item.quantity}"
                readonly
              >
              <button
                type="button"
                class="quantity-btn"
                onclick="handleCartQtyChange(${item.id}, ${item.quantity + 1})"
                aria-label="Increase quantity"
                ${item.quantity >= item.stock ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : ''}
              >&plus;</button>
            </div>
            <button
              type="button"
              class="cart-item-remove"
              onclick="handleCartRemove(${item.id})"
              aria-label="Remove item"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
              </svg>
              Remove
            </button>
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = `
      <div class="cart-layout">
        <div>
          <div class="cart-items-card">
            ${itemsHtml}
          </div>
          <div style="margin-top:var(--space-4);display:flex;justify-content:space-between;align-items:center;">
            <a href="products.html" class="btn btn-secondary btn-sm">&larr; Continue Shopping</a>
            <button type="button" class="btn btn-subtle btn-sm" onclick="clearCart()" style="color:var(--color-danger);">
              Clear Entire Bag
            </button>
          </div>
        </div>
        <div>
          <div class="summary-card">
            <h2 class="summary-title">Order Summary</h2>
            <div class="summary-row">
              <span>Subtotal (${cart.total_items} items)</span>
              <span>${formatINR(subtotal)}</span>
            </div>
            <div class="summary-row">
              <span>Standard Shipping</span>
              <span>${shipping === 0 ? '<strong style="color:var(--color-success)">FREE</strong>' : formatINR(shipping)}</span>
            </div>
            <div class="summary-row total">
              <span>Total</span>
              <span>${formatINR(total)}</span>
            </div>
            <a href="checkout.html" class="btn btn-primary btn-block btn-lg">Proceed to Checkout</a>
            <div class="summary-badges">
              <div class="summary-badge-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                <span>Safe &amp; Secure Order Processing</span>
              </div>
              <div class="summary-badge-item">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                <span>Complimentary free delivery on orders above ₹1,999</span>
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

// Global click handlers for inline events in cart
function handleCartQtyChange(itemId, newQty) {
  updateCartQuantity(itemId, newQty);
}

function handleCartRemove(itemId) {
  removeFromCart(itemId);
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
window.fetchCart = fetchCart;
