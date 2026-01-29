# Route Testing Plan

This plan focuses on keeping **every single route** healthy and regression-free by combining an always-on smoke test, a registry for coverage accountability, and deeper tests for dynamic routes as data fixtures mature.

## Goals

1. Ensure every registered route can be built and referenced without failures.
2. Ensure every static GET route (no URL parameters) responds without server errors.
3. Provide a clear checklist for expanding coverage to dynamic routes and non-GET methods.

## Current Coverage

### 1) Route Map Smoke Checks

`tests/test_route_registry.py` does two baseline checks:

- **URL building** for every route (`url_for`) to catch broken endpoints or missing parameters.
- **Static GET route health** (all GET routes without URL parameters must return < 500).

This guarantees new routes added to Flask are immediately validated for basic health.

### 2) What’s Included Today

- All routes registered with Flask (from `app.py` and blueprints).
- Static (parameterless) GET endpoints.
- Skips static file serving endpoints (`/static`, `static`).

## Next Steps for Full Route Coverage

The following incremental steps are designed to push coverage toward 100% of routes:

### A) Dynamic Routes (URL Parameters)

Add fixtures that create the minimum database records required for:

- `/animal/<int:animal_id>` family routes
- `/consulta/<int:consulta_id>` family routes
- `/tutor/<int:tutor_id>` family routes
- `/veterinario/<int:veterinario_id>` family routes

Then expand the route smoke test to include:

- GET on each dynamic route with a real object ID
- Expected behavior for missing IDs (404/403)

### B) Non-GET Methods (POST/PUT/DELETE)

For each write route:

- Add a minimal valid payload
- Verify the happy path (201/302)
- Verify invalid payload yields 400 rather than 500
- Verify unauthorized access yields 401/403

### C) Role-Based Access Matrix

Use a matrix that tests each route against:

- Anonymous user
- Tutor
- Veterinarian
- Clinic staff
- Admin

For every route, verify:

- Correct role has access
- Wrong role does not

## Maintenance Checklist

When a new route is added:

1. It must build (covered automatically).
2. If it is a static GET, it must respond without server errors (covered automatically).
3. Add it to the dynamic or write route plan as applicable.

---

This plan is intentionally incremental so the system stays stable while coverage expands without blocking development velocity.
