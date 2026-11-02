# ShopEasy --- Design System

## 1. Design vision

Create a premium, minimalist e-commerce experience inspired by the
visual principles of Apple.com: confident typography, generous
whitespace, strong product photography, simple navigation, restrained
color, and polished interactions.

This is inspiration, not a reproduction. Do not copy Apple's logo,
proprietary assets, exact page layouts, or branding.

## 2. Brand personality

-   Premium but approachable.
-   Calm, clear, and product-focused.
-   Modern and uncluttered.
-   Trustworthy and easy to navigate.

## 3. Color tokens

  Token               Hex         Usage
  ------------------- ----------- --------------------------------
  `--color-bg`        `#FFFFFF`   Main background
  `--color-surface`   `#F5F5F7`   Secondary sections and cards
  `--color-text`      `#1D1D1F`   Main text
  `--color-muted`     `#6E6E73`   Secondary text
  `--color-primary`   `#0071E3`   Primary actions and links
  `--color-border`    `#D2D2D7`   Borders and separators
  `--color-success`   `#248A3D`   Success feedback
  `--color-danger`    `#D70015`   Errors and destructive actions

Use colors consistently. Avoid unnecessary gradients and bright
decorative colors.

## 4. Typography

-   Prefer a system font stack for fast loading and platform-native
    rendering.
-   Suggested stack:
    `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.
-   Use large, confident headings for hero sections.
-   Keep body text readable and line lengths controlled.
-   Use a clear hierarchy for page title, section title, product name,
    price, and metadata.
-   Avoid excessive font weights and decorative typefaces.

## 5. Layout and spacing

-   Use a centered content container with a consistent maximum width.
-   Use generous whitespace around hero content and product imagery.
-   Keep navigation simple and uncluttered.
-   Use a consistent spacing scale, preferably multiples of 4 or 8
    pixels.
-   Use responsive CSS Grid and Flexbox.
-   Avoid horizontal overflow on mobile.
-   Keep product cards aligned and visually consistent.

## 6. Components

### Navigation

-   Clean header with ShopEasy wordmark.
-   Links to relevant shopping categories.
-   Search, account, and cart access.
-   Responsive mobile navigation.
-   Admin navigation must be visually separate from customer navigation.

### Buttons

-   Primary action: blue background, white text.
-   Secondary action: neutral surface or outlined style.
-   Destructive action: clearly differentiated.
-   Provide hover, focus, active, disabled, and loading states.
-   Use consistent height, padding, and border radius.

### Product cards

-   Large, high-quality product image.
-   Product name and concise supporting text.
-   Clearly visible price.
-   Simple Add to Cart action.
-   Consistent image aspect ratio and card spacing.
-   Show stock availability when relevant.

### Forms

-   Visible labels.
-   Clear input focus state.
-   Helpful validation messages.
-   Accessible error messaging.
-   Do not rely on placeholder text as the only label.

### Feedback

-   Provide loading, empty, success, and error states.
-   Use restrained notifications.
-   Confirm destructive actions.

## 7. Customer pages

1.  Home: hero, categories, featured products, latest products, and
    footer.
2.  Product listing: product grid, search, category filter, and sorting.
3.  Product details: image gallery, description, price, stock, quantity,
    and Add to Cart.
4.  Cart: line items, quantity controls, remove action, and summary.
5.  Checkout: delivery address, order summary, and simulated payment.
6.  Orders: order history and status timeline.
7.  Profile: customer information, addresses, and referral code.
8.  Login: phone number and OTP verification.

## 8. Admin pages

1.  Dashboard: order and product summary.
2.  Products: product table and management actions.
3.  Add/edit product: name, description, category, price, stock, and
    image.
4.  Orders: order list and status updates.
5.  Customers: customer list and relevant account details.

Admin pages must not show referral codes or referral controls.

## 9. Imagery

-   Use clear, consistent product photography.
-   Prefer neutral backgrounds and uncluttered compositions.
-   Use appropriately sized images and lazy loading where useful.
-   Use licensed, public-domain, or project-owned assets.
-   Do not hotlink arbitrary images as a permanent storage strategy.
-   Store production product images in external image storage.

## 10. Responsive behavior

-   Desktop: spacious layouts and multi-column product grids.
-   Tablet: reduce columns and spacing without crowding.
-   Mobile: single-column or compact grids, touch-friendly controls, and
    a usable navigation menu.
-   Test common viewport widths and prevent horizontal scrolling.

## 11. Motion

-   Use subtle transitions for hover and focus.
-   Keep animation short and purposeful.
-   Respect `prefers-reduced-motion`.
-   Do not animate every element or make shopping interactions slower.

## 12. Design acceptance checklist

-   Visual hierarchy is clear.
-   Product imagery is prominent.
-   Whitespace is consistent.
-   Typography is readable.
-   Buttons and inputs have all relevant states.
-   Customer and admin experiences are distinct.
-   Pages work on desktop, tablet, and mobile.
-   No broken images, overflowing content, or inconsistent components.
