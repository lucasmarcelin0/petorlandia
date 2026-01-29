# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PetOrlândia is a Flask-based veterinary clinic management system for managing pets, appointments, veterinarians, clinics, payments (Mercado Pago integration), and electronic invoices (NFS-e). The application is in Portuguese (Brazil).

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application locally
flask run
# or
python app.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_routes.py

# Run a specific test
pytest tests/test_routes.py::test_login_page -v

# Run with coverage
pytest --cov=.

# Database migrations
flask db migrate -m "description"
flask db upgrade

# Accounting backfill (manual)
flask classify-transactions-history
```

## Architecture

### Core Files

- **app.py** (~735KB) - Main Flask application with all routes. This is a monolithic file containing the entire application logic.
- **models.py** (~90KB) - SQLAlchemy models (User, Animal, Veterinario, Clinica, Consulta, Orcamento, Payment, etc.)
- **extensions.py** - Flask extensions initialization (db, migrate, mail, login, session, babel)
- **config.py** - Configuration class with environment variables
- **forms.py** - WTForms form definitions
- **helpers.py** - Utility functions (geocoding, date helpers, decorators)

### Services Layer (`services/`)

- **finance.py** - Financial operations and transaction classification
- **nfse_service.py** / **nfse_queue.py** - Electronic invoice (NFS-e) generation and queue processing
- **health_plan.py** - Health plan subscription logic
- **calendar_access.py** - Calendar permissions and access control
- **animal_search.py** - Animal search functionality
- **data_share.py** - Data sharing between clinics

### Timezone Handling

The application uses Brazil timezone (America/Sao_Paulo) consistently. Use utilities from `time_utils.py`:

```python
from time_utils import BR_TZ, coerce_to_brazil_tz, normalize_to_utc, utcnow, now_in_brazil

# Current time in Brazil
now_in_brazil()

# Current UTC time (timezone-aware)
utcnow()

# Convert to UTC for database storage
normalize_to_utc(datetime_value)

# Convert to Brazil TZ for display
coerce_to_brazil_tz(datetime_value)
```

### Database

- PostgreSQL in production (Heroku)
- SQLite in-memory for tests
- Uses Flask-Migrate/Alembic for migrations
- Models use `db` from `extensions.py`

### Tests

Tests are in `tests/` directory. They use pytest with an in-memory SQLite database:

```python
@pytest.fixture
def app():
    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
    )
    yield flask_app
```

Helper function for simulating login in tests:
```python
def login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True
```

### Deployment

- Heroku deployment via `Procfile`
- Web server: gunicorn with eventlet worker
- Scheduler: separate process for periodic accounting backfills
- SocketIO for real-time features (calendar updates, notifications)

### Key Integrations

- **Mercado Pago**: Payment processing (env vars: `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_PUBLIC_KEY`, `MERCADOPAGO_WEBHOOK_SECRET`)
- **Twilio**: WhatsApp/SMS notifications
- **AWS S3**: File uploads (photos, documents)
- **Flask-Mail**: Email via Gmail SMTP

### Multi-Clinic Support

The system supports multiple clinics with staff permissions. Key models:
- `Clinica` - Clinic entity
- `Veterinario` - Veterinarian linked to User
- Staff access is managed through relationships and decorators

### Offline Support

Forms with `data-sync="true"` queue submissions when offline. See `static/offline.js` and the service worker.
