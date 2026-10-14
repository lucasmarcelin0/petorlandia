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

## 2026-09-12 - Dynamic Copy Button Feedback for Screen Readers
**Learning:** Copy-to-clipboard buttons that change visual inner text on copy (e.g. from "Copiar" to "Copiado") leave screen reader users unaware of the copy operation status unless the element has `aria-live="polite"` and dynamically updates its `aria-label` during the success feedback state.
**Action:** Always add `aria-live="polite"` and update `aria-label` dynamically during copy feedback state on copy-to-clipboard elements, restoring the original label after timeout.

## 2026-09-16 - Password Visibility Toggles on Onboarding Setup Forms
**Learning:** Onboarding forms where users establish new credentials (such as first-access setup) require accessible `auth-password-toggle` controls with `aria-controls`, `aria-pressed`, and `aria-label` attributes to prevent user friction from silent typos on mobile touchscreens and ensure parity across all credential entry views.
**Action:** Ensure all password setup templates (including onboarding and first-access password creation) wrap password fields in `auth-password-group` containers with accessible visibility toggle controls.

## 2026-09-16 - Dynamic Cart Quantity ARIA Label Synchronization
**Learning:** Updating an element's `textContent` via JavaScript without updating its static `aria-label` attribute leaves screen reader users hearing outdated information, as screen readers prioritize `aria-label` over text content.
**Action:** Always complement dynamic `textContent` updates in JS with `setAttribute('aria-label', ...)` and `aria-live="polite"` on quantity counter elements.

## 2026-09-21 - ARIA labels and hidden icons for icon-only action buttons and cropper toolbar
**Learning:** Icon-only action buttons (e.g. edit, delete, photo cropper controls) rely solely on the `title` attribute for accessibility. However, `title` attributes are not reliably announced by all screen readers and do not provide robust accessible names. Additionally, nested icon elements can create redundant or confusing announcements if not hidden.
**Action:** Always provide an explicit `aria-label` attribute on icon-only interactive elements (like buttons and links), wrap toolbar action groups with `role="group"` and `aria-label`, and always add `aria-hidden="true"` to decorative child icon elements to ensure clear and reliable announcements for screen reader users.

## 2026-09-24 - Dynamic ARIA Expanded State Synchronization on Collapsible Drawers
**Learning:** Collapsible sections and drawer toggles without explicit `aria-expanded` and `aria-controls` bindings prevent assistive technology users from perceiving when content is expanded or collapsed.
**Action:** Always bind toggle buttons to collapsible containers via `aria-controls` and `aria-expanded`, and update `aria-expanded` dynamically in JS event handlers whenever visibility is toggled.

## 2026-09-28 - Store Search Form Accessibility and Inline Quick Clear
**Learning:** In search forms with multi-dimensional filtering (category, seller, sorting), input controls require explicit `aria-label` attributes (`aria-label="Buscar produtos no catálogo"`) and a dedicated inline search clear button (`js-clear-search-btn`) with `aria-label="Limpar busca"`. This enables screen reader and keyboard users to clear specifically the search term without resetting active seller or category filter parameters.
**Action:** Always pair multi-filter search inputs with explicit `aria-label` attributes and an inline clear button that resets the query parameter while preserving active contextual filters.

## 2026-09-30 - Accessible Clinical Panel Controls and Form Label Associations
**Learning:** Interactive controls in clinical suggestions panels (such as dismissal and search clear buttons) require explicit `aria-label`s and `aria-hidden="true"` on nested icons to avoid silent or confusing screen reader navigation. Furthermore, all form inputs in tutor/patient details must have matching `<label for="id">` and `<input id="id">` attributes to maintain full WCAG 1.3.1 compliance.
**Action:** Ensure every icon button in clinical and modal workflows has an explicit `aria-label`, hide decorative icon elements, and bind all form labels with matching input IDs.

## 2026-10-09 - Maintainer triage: one-template ARIA PRs are closed; fix whole classes with a guard
**Learning:** The maintainer closed 53 of the 57 open Palette PRs on 2026-10-09. Icon-only buttons already have `aria-label` in 97 of 99 cases, and most PRs repeated work already on `main` (six of them for `clinical_suggestions_panel.html`). Two patterns were rejected as regressions: `aria-label` on a control whose visible label is text or is filled in by JavaScript, and a second click handler for a copy button that already had one.
**Action:** Read `.jules/protocol.md` sections 4 to 6 before every session. Do accessibility work one class at a time, across all templates in a single PR, with a static guard test in `tests/`. Start with section 6.3 (`aria-hidden` on decorative icons: 1,410 of 1,921 lack it). If nothing there applies, end the session without a PR.
