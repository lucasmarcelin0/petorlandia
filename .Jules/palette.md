## 2026-08-29 - Modal Dialog Accessibility Attributes
**Learning:** Reusable custom modal components require explicit `role="dialog"`, `aria-modal="true"`, `aria-labelledby`, and `aria-label="Fechar"` on close buttons to ensure screen readers properly announce dialog context and close controls.
**Action:** Always include ARIA dialog roles, accessible title IDs, and close button labels when building or modifying custom modal templates.
