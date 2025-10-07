## Findings
1. The schedule modal’s “Cadastrar novo tutor” collapse includes only the lightweight `calendar_quick_tutor_form.html` partial, so it lacks the tutor search box, added-tutor list, and address widgets that the dedicated `/tutores` screen provides, forcing duplicate UI work and leaving the calendar flow with fewer capabilities.

:::task-stub{title="Reuse the Tutores layout inside the agenda"}
1. In `app.py`, extract the `fetch_tutores` pagination helper inside `tutores()` into a shared function (e.g., `_get_recent_tutores(scope, page, clinic_id, user_id)`) and call it from both `tutores()` and the veterinarian agenda view so both contexts receive `tutores_adicionados`, `pagination`, and the chosen `scope`.
2. Move the wrapper markup around the form, search panel, and tutor list from `templates/animais/tutores.html` into a reusable partial such as `templates/partials/novo_tutor_panel.html`, parameterized with the context values above.
3. Replace the body of `animais/tutores.html` with an `{% include 'partials/novo_tutor_panel.html' %}` call to render the shared layout for the standalone page.
4. Swap the current `{% include 'partials/calendar_quick_tutor_form.html' %}` call inside the agenda’s “Novo Tutor” collapse for the new partial so the agenda displays the full page layout (adjusting containers so the grid fits inside the collapse).
5. Update the JSON response in `tutores()` (when `Accept: application/json`) to return the fragment of the new partial that should refresh the `#tutores-adicionados` container, mirroring the existing behavior.
:::
