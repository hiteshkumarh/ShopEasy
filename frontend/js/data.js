/**
 * ShopEasy --- Sample Product Data & Helpers
 * Realistic product catalog with INR pricing
 * Structured for easy replacement with backend API responses in later phases.
 */

const SHOP_CATEGORIES = [
  { id: 'electronics', name: 'Electronics', count: 4, icon: 'headphones' },
  { id: 'fashion', name: 'Fashion', count: 2, icon: 'shoe' },
  { id: 'accessories', name: 'Accessories', count: 3, icon: 'watch' },
  { id: 'home', name: 'Home & Living', count: 2, icon: 'home' },
  { id: 'beauty', name: 'Beauty', count: 1, icon: 'sparkle' }
];

const SHOP_PRODUCTS = [
  {
    id: 'prod-001',
    name: 'Wireless Noise-Cancelling Headphones',
    category: 'electronics',
    categoryName: 'Electronics',
    price: 2499,
    originalPrice: 3499,
    rating: 4.8,
    reviewsCount: 142,
    inStock: true,
    stockCount: 28,
    isFeatured: true,
    isLatest: false,
    image: 'https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1546435770-a3e426bf472b?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1484704849700-f032a568e944?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Immerse yourself in pure studio sound with active noise cancellation, custom acoustic drivers, and up to 40 hours of battery life on a single charge.',
    features: [
      'Active Noise Cancellation with Transparency mode',
      'Custom 40mm dynamic acoustic drivers',
      'Up to 40 hours battery life with fast charging',
      'Bluetooth 5.3 with multi-device pairing',
      'Ergonomic memory foam ear cushions'
    ]
  },
  {
    id: 'prod-002',
    name: 'Smart Watch Series X',
    category: 'accessories',
    categoryName: 'Accessories',
    price: 3999,
    originalPrice: 4999,
    rating: 4.9,
    reviewsCount: 215,
    inStock: true,
    stockCount: 15,
    isFeatured: true,
    isLatest: true,
    image: 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1579586337278-3befd40fd17a?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'An advanced fitness and wellness companion featuring an always-on Retina AMOLED display, optical heart sensor, SpO2 tracking, and 7-day battery.',
    features: [
      '1.78-inch Always-on Ultra AMOLED display',
      'Real-time heart rate and blood oxygen monitoring',
      'Over 100 dedicated workout and fitness modes',
      '5 ATM water resistance up to 50 meters',
      'Fast magnetic wireless charging'
    ]
  },
  {
    id: 'prod-003',
    name: 'Premium Minimalist Backpack',
    category: 'accessories',
    categoryName: 'Accessories',
    price: 1799,
    originalPrice: 2299,
    rating: 4.7,
    reviewsCount: 88,
    inStock: true,
    stockCount: 34,
    isFeatured: true,
    isLatest: false,
    image: 'https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1546938576-6e6a64f317cc?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Engineered for modern commuters and creatives with weather-resistant recycled canvas, dedicated 16-inch laptop compartment, and concealed anti-theft pockets.',
    features: [
      'Dedicated padded sleeve fits up to 16-inch laptops',
      'Water-repellent durable matte canvas exterior',
      'Ergonomic breathable mesh shoulder straps',
      'Luggage pass-through strap for effortless travel',
      '22-liter capacity with organized dividers'
    ]
  },
  {
    id: 'prod-004',
    name: 'Pro Performance Running Shoes',
    category: 'fashion',
    categoryName: 'Fashion',
    price: 2999,
    originalPrice: 3899,
    rating: 4.6,
    reviewsCount: 110,
    inStock: true,
    stockCount: 19,
    isFeatured: false,
    isLatest: true,
    image: 'https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1584735935682-2f2b69dff9d2?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Built for high energy return and responsive cushioning. Breathable engineered mesh upper keeps your feet cool across long running sessions.',
    features: [
      'Dual-density high-rebound cushioning midsole',
      'Breathable engineered micro-mesh upper',
      'High-abrasion durable rubber traction outsole',
      'Ultra-lightweight construction (under 240g)'
    ]
  },
  {
    id: 'prod-005',
    name: 'Portable Bluetooth Speaker',
    category: 'electronics',
    categoryName: 'Electronics',
    price: 1499,
    originalPrice: 1999,
    rating: 4.8,
    reviewsCount: 94,
    inStock: true,
    stockCount: 42,
    isFeatured: true,
    isLatest: false,
    image: 'https://images.unsplash.com/photo-1545454675-3531b543be5d?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1545454675-3531b543be5d?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Compact 360-degree acoustic performance with deep bass and IPX7 waterproof casing. Grab-and-go lanyard design ready for any adventure.',
    features: [
      '360-degree room-filling acoustic soundstage',
      'IPX7 certified waterproof and dustproof',
      'Up to 16 hours continuous playtime',
      'Dual speaker stereo pairing support'
    ]
  },
  {
    id: 'prod-006',
    name: 'Tactile Mechanical Keyboard',
    category: 'electronics',
    categoryName: 'Electronics',
    price: 3499,
    originalPrice: 4299,
    rating: 4.9,
    reviewsCount: 167,
    inStock: true,
    stockCount: 12,
    isFeatured: false,
    isLatest: true,
    image: 'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=800&auto=format&fit=crop&q=80',
      'https://images.unsplash.com/photo-1618384887929-16ec33fab9ef?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Compact 75% layout keyboard with factory-lubed tactile mechanical switches, premium PBT keycaps, and Mac/Windows dual compatibility.',
    features: [
      'Hot-swappable tactile mechanical switches',
      'Double-shot PBT keycaps with crisp legends',
      'Multi-mode: Bluetooth 5.1, 2.4GHz & USB-C wired',
      'Solid CNC-machined aluminum top frame'
    ]
  },
  {
    id: 'prod-007',
    name: 'Minimalist Top-Grain Leather Wallet',
    category: 'accessories',
    categoryName: 'Accessories',
    price: 999,
    originalPrice: 1499,
    rating: 4.7,
    reviewsCount: 76,
    inStock: true,
    stockCount: 50,
    isFeatured: false,
    isLatest: false,
    image: 'https://images.unsplash.com/photo-1627123424574-724758594e93?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1627123424574-724758594e93?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Slim bifold wallet handcrafted from vegetable-tanned top-grain leather with built-in RFID blocking shield and quick-access card pull tab.',
    features: [
      'Full RFID protection against digital theft',
      'Holds 8-10 cards and flat currency notes',
      'Slim 8mm profile prevents pocket bulge'
    ]
  },
  {
    id: 'prod-008',
    name: 'Ultrasonic Ceramic Aroma Diffuser',
    category: 'home',
    categoryName: 'Home & Living',
    price: 1899,
    originalPrice: 2499,
    rating: 4.8,
    reviewsCount: 52,
    inStock: true,
    stockCount: 22,
    isFeatured: false,
    isLatest: true,
    image: 'https://images.unsplash.com/photo-1608571423902-eed4a5ad8108?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1608571423902-eed4a5ad8108?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Elegantly styled matte ceramic essential oil diffuser with whisper-quiet ultrasonic atomization and warm ambient LED glow.',
    features: [
      'Handcrafted matte ceramic cover',
      'Quiet ultrasonic misting up to 8 hours',
      'Auto shut-off when water reservoir is empty'
    ]
  },
  {
    id: 'prod-009',
    name: 'Natural Botanical Facial Serum',
    category: 'beauty',
    categoryName: 'Beauty',
    price: 1299,
    originalPrice: 1699,
    rating: 4.9,
    reviewsCount: 64,
    inStock: true,
    stockCount: 30,
    isFeatured: false,
    isLatest: true,
    image: 'https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Restorative antioxidant serum formulated with cold-pressed rosehip, squalane, and vitamin C to enhance radiance and deeply hydrate skin.',
    features: [
      '100% vegan and cruelty-free formulation',
      'Free of synthetic fragrances and parabens',
      'Suitable for all skin types, including sensitive'
    ]
  },
  {
    id: 'prod-010',
    name: 'Insulated Stainless Steel Bottle',
    category: 'home',
    categoryName: 'Home & Living',
    price: 799,
    originalPrice: 1199,
    rating: 4.7,
    reviewsCount: 130,
    inStock: true,
    stockCount: 65,
    isFeatured: false,
    isLatest: false,
    image: 'https://images.unsplash.com/photo-1602143407151-7111542de6e8?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1602143407151-7111542de6e8?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Double-wall vacuum insulated canteen keeps drinks ice-cold for 24 hours or piping hot for 12 hours. Premium powder coat grip.',
    features: [
      '18/8 food-grade stainless steel',
      'Zero condensation sweat-free exterior',
      '100% leakproof spout lid'
    ]
  },
  {
    id: 'prod-011',
    name: 'Studio True Wireless Earbuds',
    category: 'electronics',
    categoryName: 'Electronics',
    price: 4499,
    originalPrice: 5999,
    rating: 4.9,
    reviewsCount: 92,
    inStock: true,
    stockCount: 18,
    isFeatured: true,
    isLatest: true,
    image: 'https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'True wireless spatial audio earbuds with active noise cancellation, low-latency gaming mode, and seamless Qi wireless charging case.',
    features: [
      'Adaptive Hybrid Noise Cancellation',
      'Spatial 3D audio head tracking',
      'Up to 32 hours total playback with charging case'
    ]
  },
  {
    id: 'prod-012',
    name: 'Classic Polarized Sunglasses',
    category: 'fashion',
    categoryName: 'Fashion',
    price: 1599,
    originalPrice: 2199,
    rating: 4.6,
    reviewsCount: 45,
    inStock: true,
    stockCount: 25,
    isFeatured: false,
    isLatest: false,
    image: 'https://images.unsplash.com/photo-1511499767150-a48a237f0083?w=800&auto=format&fit=crop&q=80',
    gallery: [
      'https://images.unsplash.com/photo-1511499767150-a48a237f0083?w=800&auto=format&fit=crop&q=80'
    ],
    description: 'Timeless hand-polished acetate frames paired with UV400 polarized optical lenses for crystal clear contrast and zero eye fatigue.',
    features: [
      '100% UVA/UVB protection (UV400)',
      'Durable 5-barrel stainless steel hinges',
      'Includes microfiber protective case and cloth'
    ]
  }
];

// Initial mock customer profile data (reset)
const MOCK_PROFILE = null;

// Initial mock orders (reset to empty)
const MOCK_ORDERS = [];

// Utility: Format currency in Indian Rupees (INR)
function formatINR(amount) {
  if (typeof amount !== 'number') return '₹0';
  return '₹' + amount.toLocaleString('en-IN');
}

// Data access helpers
function getProducts() {
  return SHOP_PRODUCTS;
}

function getProductById(id) {
  return SHOP_PRODUCTS.find(p => p.id === id);
}

function getFeaturedProducts() {
  return SHOP_PRODUCTS.filter(p => p.isFeatured);
}

function getLatestProducts() {
  return SHOP_PRODUCTS.filter(p => p.isLatest);
}

function getCategories() {
  return SHOP_CATEGORIES;
}

// Fallback image generator (clean SVG placeholder so broken links never display ugly icons)
function getPlaceholderImage(text) {
  const cleanText = encodeURIComponent(text || 'ShopEasy Product');
  return `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600"><rect width="600" height="600" fill="%23F5F5F7"/><circle cx="300" cy="270" r="80" fill="%23E5E5EA"/><text x="50%" y="420" font-family="-apple-system, sans-serif" font-size="24" font-weight="600" fill="%236E6E73" text-anchor="middle">${cleanText}</text><text x="50%" y="460" font-family="-apple-system, sans-serif" font-size="16" fill="%238E8E93" text-anchor="middle">ShopEasy Premium Collection</text></svg>`;
}

