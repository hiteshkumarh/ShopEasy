/**
 * ShopEasy --- Shopping Cart Logic
 * Manages cart state in localStorage, calculates totals, and renders cart view.
 */

const CART_STORAGE_KEY = 'shopeasy_cart';

// Retrieve cart items from localStorage
function getCart() {
  try {
    const raw = localStorage.getItem(CART_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error('Error reading cart from localStorage', e);
    return [];
  }
}

// Save cart items to localStorage
function saveCart(cart) {
  try {
    localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cart));
    syncCartBadge();
    window.dispatchEvent(new CustomEvent('cart-updated', { detail: { cart } }));
  } catch (e) {
    console.error('Error saving cart to localStorage', e);
  }
}

// Add item to cart
function addToCart(productId, quantity = 1) {
  const product = getProductById(productId);
  if (!product) {
    showToast('Product not found', 'error');
    return false;
  }

  const cart = getCart();
  const existingItemIndex = cart.findIndex(item => item.productId === productId);

  if (existingItemIndex > -1) {
    cart[existingItemIndex].quantity += quantity;
  } else {
    cart.push({
      productId: product.id,
      quantity: quantity,
      product: {
        id: product.id,
        name: product.name,
        price: product.price,
        image: product.image,
        categoryName: product.categoryName
      }
    });
  }

  saveCart(cart);
  showToast(`Added "${product.name}" to your cart`);
  return true;
}

// Update quantity
function updateCartQuantity(productId, quantity) {
  let cart = getCart();
  const itemIndex = cart.findIndex(item => item.productId === productId);

  if (itemIndex > -1) {
    if (quantity <= 0) {
      removeFromCart(productId);
      return;
    }
    cart[itemIndex].quantity = quantity;
    saveCart(cart);
  }
}

// Remove item from cart
function removeFromCart(productId) {
  let cart = getCart();
  const itemToRemove = cart.find(item => item.productId === productId);
  cart = cart.filter(item => item.productId !== productId);
  saveCart(cart);

  if (itemToRemove && itemToRemove.product) {
    showToast(`Removed "${itemToRemove.product.name}" from cart`);
  }
}

// Total count of units in cart
function getCartCount() {
  const cart = getCart();
  return cart.reduce((total, item) => total + (item.quantity || 0), 0);
}

// Subtotal amount in INR
function getCartSubtotal() {
  const cart = getCart();
  return cart.reduce((sum, item) => {
    const price = (item.product && item.product.price) || 0;
    return sum + (price * item.quantity);
  }, 0);
}

// Empty the cart
function clearCart() {
  localStorage.removeItem(CART_STORAGE_KEY);
  syncCartBadge();
  window.dispatchEvent(new CustomEvent('cart-updated', { detail: { cart: [] } }));
}

// Synchronize badge on header
function syncCartBadge() {
  const count = getCartCount();
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
function renderCartPage() {
  const container = document.getElementById('cart-content-container');
  if (!container) return;

  const cart = getCart();

  if (cart.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg class="empty-state-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <circle cx="9" cy="21" r="1"/>
          <circle cx="20" cy="21" r="1"/>
          <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
        </svg>
        <h2 class="empty-state-title">Your Bag is Empty</h2>
        <p class="empty-state-desc">Explore our premium selection and find something designed for your everyday lifestyle.</p>
        <a href="products.html" class="btn btn-primary btn-lg">Explore Products</a>
      </div>
    `;
    return;
  }

  const subtotal = getCartSubtotal();
  const shipping = subtotal > 1999 ? 0 : 99; // Free shipping above ₹1,999
  const total = subtotal + shipping;

  const itemsHtml = cart.map(item => {
    const itemTotal = item.product.price * item.quantity;
    return `
      <div class="cart-item" data-product-id="${item.productId}">
        <img 
          src="${item.product.image}" 
          alt="${item.product.name}" 
          class="cart-item-image"
          onerror="handleImageError(this, '${item.product.name}')"
        >
        <div class="cart-item-details">
          <span class="cart-item-category">${item.product.categoryName || 'Product'}</span>
          <a href="product-details.html?id=${item.productId}" class="cart-item-title">${item.product.name}</a>
          <span class="cart-item-price">${formatINR(item.product.price)} each</span>
        </div>
        <div class="cart-item-actions">
          <div class="cart-item-total">${formatINR(itemTotal)}</div>
          <div class="quantity-control">
            <button 
              type="button" 
              class="quantity-btn" 
              onclick="handleCartQtyChange('${item.productId}', ${item.quantity - 1})"
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
              onclick="handleCartQtyChange('${item.productId}', ${item.quantity + 1})"
              aria-label="Increase quantity"
            >&plus;</button>
          </div>
          <button 
            type="button" 
            class="cart-item-remove" 
            onclick="handleCartRemove('${item.productId}')"
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
      </div>
      <div>
        <div class="summary-card">
          <h2 class="summary-title">Order Summary</h2>
          <div class="summary-row">
            <span>Subtotal (${getCartCount()} items)</span>
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
              <span>Safe & Secure Checkout</span>
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
}

// Global click handlers for inline events in cart
function handleCartQtyChange(productId, newQty) {
  updateCartQuantity(productId, newQty);
  renderCartPage();
}

function handleCartRemove(productId) {
  removeFromCart(productId);
  renderCartPage();
}

// Listen to cart update event
window.addEventListener('cart-updated', syncCartBadge);

