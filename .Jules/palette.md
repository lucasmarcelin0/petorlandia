## 2026-08-29 - Modal Dialog Accessibility Attributes
**Learning:** Reusable custom modal components require explicit `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, and `aria-label="Fechar"` on close buttons to ensure screen readers properly announce dialog context and close controls.
**Action:** Always include ARIA dialog roles, accessible title IDs, and close button labels when building or modifying custom modal templates.

## 2026-09-02 - Hover-Only Action Overlays and Keyboard Focus
**Learning:** Hover-only action containers on UI cards (e.g. `opacity: 0` until `:hover`) leave keyboard users unable to discover or interact with edit/delete buttons when navigating with the Tab key.
**Action:** Always complement `:hover` visibility with `:focus-within` on card containers (e.g., `.card:focus-within .card__actions { opacity: 1; }`) and ensure `:focus-visible` outline styles are provided on action buttons.

## 2026-08-30 - Dynamic Icon-Only Action Buttons in Store Cards
**Learning:** State-toggling icon buttons (like product visibility or active status toggles) need conditional `aria-label`s matching the action (e.g., "Desativar produto" vs "Ativar produto") rather than static icon labels, with child icons set to `aria-hidden="true"`.
**Action:** Always ensure stateful icon-only action buttons use dynamic Jinja conditional `aria-label` attributes to announce the correct action to assistive technologies.

## 2026-08-28 - Skip-to-content links for main layout accessibility
**Learning:** In applications with extensive top navigation menus, keyboard and screen reader users must tab through every single navigation item on every page load to reach page content. Adding a visually-hidden skip link immediately inside `<body>` targeting the main content container (`<main id="main-content" tabindex="-1">`) satisfies WCAG 2.4.1 (Bypass Blocks).
**Action:** Whenever creating or updating base HTML layout templates with top navigation headers, always ensure a skip-to-content link is present at the top of `<body>` pointing to the main element with `tabindex="-1"`.

## 2026-09-06 - Accessible Password Visibility Toggles & Search Controls
**Learning:** Password inputs require accessible visibility toggles with `aria-label`, `aria-pressed`, and dynamic text announcement so screen reader and keyboard users can verify password entry safely. Search inputs and filtering drawers require explicit `aria-label`, `aria-expanded`, and `aria-controls` bindings to maintain accessible state transitions.
**Action:** Always provide accessible toggle buttons for password inputs and link collapsible filter drawers to their toggles via `aria-expanded` and `aria-controls`.

## 2026-09-07 - Emoji Action Buttons & Dynamic Item Aria Labels
**Learning:** Raw emoji action buttons (such as 🗑️) render inconsistently across platforms and fail to convey context to screen readers. Replacing them with standard icon elements (`aria-hidden="true"`) paired with item-specific `aria-label`s (e.g. `aria-label="Remover item {{ item.descricao }}"`) provides clear contextual announcements to screen readers.
**Action:** Replace raw emoji action buttons with standard Font Awesome icons and always provide descriptive, item-specific `aria-label`s in both static HTML templates and dynamic JS string templates.

## 2026-09-08 - Accessible Form Macros with Field Validation & Required Indicators
**Learning:** Reusable WTForms macros require automatic `aria-required="true"` and visual asterisk indicators (`*`) for required fields, plus `aria-invalid="true"` and `aria-describedby="{{ field.id }}-error"` linking invalid inputs to error messages so screen readers announce form errors immediately upon focus.
**Action:** Always complement Jinja form rendering macros with automatic `aria-required`, `aria-invalid`, and `aria-describedby` error associations alongside visual required indicators.
