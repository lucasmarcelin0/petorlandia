## 2026-08-29 - Modal Dialog Accessibility Attributes
**Learning:** Reusable custom modal components require explicit `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, and `aria-label="Fechar"` on close buttons to ensure screen readers properly announce dialog context and close controls.
**Action:** Always include ARIA dialog roles, accessible title IDs, and close button labels when building or modifying custom modal templates.

## 2026-09-02 - Hover-Only Action Overlays and Keyboard Focus
**Learning:** Hover-only action containers on UI cards (e.g. `opacity: 0` until `:hover`) leave keyboard users unable to discover or interact with edit/delete buttons when navigating with the Tab key.
**Action:** Always complement `:hover` visibility with `:focus-within` on card containers (e.g., `.card:focus-within .card__actions { opacity: 1; }`) and ensure `:focus-visible` outline styles are provided on action buttons.

## 2026-08-30 - Dynamic Icon-Only Action Buttons in Store Cards
**Learning:** State-toggling icon buttons (like product visibility or active status toggles) need conditional `aria-label`s matching the action (e.g., "Desativar produto" vs "Ativar produto") rather than static icon labels, with child icons set to `aria-hidden="true"`.
**Action:** Always ensure stateful icon-only action buttons use dynamic Jinja conditional `aria-label` attributes to announce the correct action to assistive technologies.
