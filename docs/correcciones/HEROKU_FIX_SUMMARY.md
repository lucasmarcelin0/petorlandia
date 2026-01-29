# Heroku Production Error Fix - Prescription History

**Issue:** `UndefinedError: 'consulta' is undefined` when saving prescriptions via AJAX

**Root Cause:**  
The `historico_prescricoes.html` template on line 68 tried to access `consulta.id`, but the `_render_prescricao_history()` function only passes `animal` and `clinic_id` (as `clinic_scope_id`), not the full `consulta` object.

**Error Flow:**
1. User saves prescription via AJAX → calls `/consulta/1719/bloco_prescricao` endpoint
2. Endpoint calls `_render_prescricao_history(animal_atualizado, clinic_id)`
3. Template tries to render delete form with `{{ url_for('historico_prescricoes_partial', consulta_id=consulta.id) }}`
4. **ERROR**: `consulta` doesn't exist in template context → 500 Internal Server Error

## Changes Made

### 1. Fixed Template (`templates/partials/historico_prescricoes.html`)

**Before (Line 68):**
```html
data-target-endpoint="{{ url_for('historico_prescricoes_partial', consulta_id=consulta.id) }}"
```

**After (Line 68):**
```html
data-target-endpoint="{{ url_for('recarregar_historico_prescricoes_ajax', animal_id=animal.id, clinic_id=clinic_scope_id) }}"
```

**Reason:** Uses available context variables (`animal.id` and `clinic_scope_id`) instead of non-existent `consulta` object.

### 2. Added New Endpoint (`app.py`, lines ~11685-11697)

Created a new AJAX endpoint for reloading prescription history by animal ID:

```python
@app.route('/animal/<int:animal_id>/historico_prescricoes', methods=['GET'])
@login_required
def recarregar_historico_prescricoes_ajax(animal_id):
    """Load prescription history for an animal by animal_id and clinic_id."""
    animal = get_animal_or_404(animal_id)
    clinic_id = request.args.get('clinic_id', type=int) or getattr(animal, 'clinica_id', None) or current_user_clinic_id()

    if clinic_id:
        ensure_clinic_access(clinic_id)

    historico_html = _render_prescricao_history(animal, clinic_id)
    return jsonify({'success': True, 'html': historico_html})
```

**Why:** This endpoint properly handles the clinic scope and doesn't require a `consulta_id`, making it compatible with the AJAX save flow.

## Technical Details

- **Problem**: Inconsistency between what the endpoint passes (animal + clinic_id) and what the template expected (consulta object with ID)
- **Solution**: Created a dedicated endpoint that matches the data flow
- **Backward Compatibility**: The old `historico_prescricoes_partial` endpoint still exists for other uses
- **Clinic Scope**: Respects clinic access controls per user role

## Testing

To verify the fix:

1. Save a prescription via the web form (AJAX POST to `/consulta/{id}/bloco_prescricao`)
2. Verify the response returns `{success: true, html: "..."}`
3. Verify history updates in the UI without errors
4. Check server logs - no 500 errors should occur

## Deployment

1. Push changes to production
2. Monitor Heroku logs for any `UndefinedError` related to templates
3. Test prescription save functionality across different user roles
4. Verify delete functionality still works (uses the new endpoint)

## Related Files

- `app.py` - Added `recarregar_historico_prescricoes_ajax()` endpoint
- `templates/partials/historico_prescricoes.html` - Updated to use new endpoint
- No database migrations needed
- No dependency changes needed
