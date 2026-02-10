# Petorlandia Test Suite

## Overview

This comprehensive test suite ensures that every feature of the Petorlandia veterinary clinic management system works perfectly and efficiently. The tests cover functionality, security, accessibility, performance, and user workflows.

## Test Categories

### 1. **End-to-End Integration Tests** (E2E)

#### Tutor Workflows (`test_e2e_tutor_workflows.py`)
- User registration with profile photo
- Login and authentication
- Password reset flow
- Animal management (add, edit, view, delete)
- Appointment scheduling and viewing
- Medical records access
- Vaccination history
- Financial operations (estimates, payments)
- Profile management
- Performance benchmarks

#### Veterinarian Workflows (`test_e2e_veterinarian_workflows.py`)
- Clinic setup and configuration
- Service catalog management
- Complete consultation workflow
- Prescription creation and management
- Exam requests
- Estimate/budget creation with discounts
- Schedule and availability management
- Inventory tracking
- On-call payment management
- Multi-veterinarian collaboration
- Financial reporting
- Performance under load

### 2. **Security Tests** (`test_security_authorization.py`)

#### Authentication
- Protected route access control
- Login validation
- Session management and timeout
- Password security (hashing, strength)

#### Authorization
- Role-based access control (RBAC)
- Data ownership verification
- Admin panel access restrictions
- Cross-clinic data isolation

#### Data Isolation (Multi-Tenancy)
- Clinic consultation isolation
- Prescription isolation
- Estimate isolation
- User data privacy

#### Input Validation
- SQL injection prevention
- XSS attack prevention
- File upload validation
- CSRF token protection

#### API Security
- Authentication requirements
- Proper error responses
- Rate limiting

### 3. **Accessibility Tests** (`test_accessibility_ui.py`)

#### WCAG 2.1 Level AA Compliance
- Form accessibility (labels, required fields)
- Image alt text
- Heading hierarchy (h1, h2, h3...)
- Color contrast ratios
- Keyboard navigation
- ARIA attributes
- Semantic HTML5 elements
- Responsive behavior
- Language attributes
- Table accessibility
- SEO best practices

### 4. **Existing Specialized Tests**

The test suite integrates with 70+ existing test files covering:
- Appointment management
- Calendar permissions
- Clinic management
- Financial snapshots
- Prescription workflows
- Exam scheduling
- Vaccination tracking
- Shopping cart operations
- Payment processing
- Data sharing and audit
- Inventory management
- And much more...

## Running Tests

### Run All Tests

```bash
# Using the comprehensive test runner
python tests/run_all_tests.py
```

### Run Specific Test Suites

```bash
# Tutor workflows
pytest tests/test_e2e_tutor_workflows.py -v

# Veterinarian workflows
pytest tests/test_e2e_veterinarian_workflows.py -v

# Security tests
pytest tests/test_security_authorization.py -v

# Accessibility tests
pytest tests/test_accessibility_ui.py -v

# Existing tests
pytest tests/test_routes.py -v

# Route registry smoke tests
pytest tests/test_route_registry.py -v
```

### Run with Coverage

```bash
# Generate coverage report
pytest tests/ --cov=. --cov-report=html --cov-report=term-missing

# View HTML coverage report
# Open htmlcov/index.html in your browser
```

### Run Specific Test Classes

```bash
# Run only authentication tests
pytest tests/test_security_authorization.py::TestAuthentication -v

# Run only form accessibility tests
pytest tests/test_accessibility_ui.py::TestFormAccessibility -v
```

### Run with Markers (if implemented)

```bash
# Run only fast tests
pytest tests/ -m fast

# Run only slow/integration tests
pytest tests/ -m slow
```

## Test Coverage Goals

- **Overall Code Coverage**: 90%+
- **Critical Paths**: 100%
- **Security Features**: 100%
- **API Endpoints**: 95%+
- **UI Templates**: 85%+

## Performance Benchmarks

Tests include performance assertions to ensure:

- **Index page**: < 1.5 seconds load time
- **Dashboard**: < 2 seconds
- **Search results**: < 1 second
- **Form submissions**: < 500ms
- **API responses**: < 200ms (GET), < 500ms (POST)

## Continuous Integration

The test suite is designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: pytest tests/ --cov=. --cov-report=xml
      - uses: codecov/codecov-action@v2
```

## Test Data Management

### Fixtures

Tests use pytest fixtures for:
- Database setup/teardown
- User creation (tutors, vets, admins)
- Animal creation with species/breeds
- Clinic setup with memberships
- Session management

### Database

Tests use SQLite in-memory database for:
- Fast execution
- Isolation between tests
- No external dependencies

## Writing New Tests

### Test Structure

```python
@pytest.fixture
def setup_data(app):
    """Create test data."""
    with app.app_context():
        # Create models
        user = User(name="Test")
        db.session.add(user)
        db.session.commit()
        return user.id

def test_feature(client, setup_data):
    """Test a specific feature."""
    # Arrange
    login(client, setup_data)
    
    # Act
    response = client.get('/some-route')
    
    # Assert
    assert response.status_code == 200
```

### Best Practices

1. **Descriptive names**: Use clear, descriptive test names
2. **Single responsibility**: Each test should test one thing
3. **Arrange-Act-Assert**: Follow AAA pattern
4. **Independent tests**: Tests should not depend on each other
5. **Clean fixtures**: Use fixtures for setup, clean up automatically
6. **Assert meaningful things**: Test behavior, not implementation

## Debugging Failed Tests

### Verbose Output

```bash
pytest tests/ -vv --tb=long
```

### Stop on First Failure

```bash
pytest tests/ -x
```

### Run Last Failed Tests

```bash
pytest tests/ --lf
```

### Print Debug Info

```python
def test_something(client, app):
    response = client.get('/')
    
    # Print response for debugging
    print(response.data.decode('utf-8'))
    
    assert response.status_code == 200
```

## Test Reports

After running tests, check:

1. **Console output**: Immediate pass/fail results
2. **test_report.json**: Detailed JSON report
3. **htmlcov/index.html**: Visual coverage report
4. **pytest-report.html** (with pytest-html plugin)

## Accessibility Testing Tools

For enhanced accessibility testing, consider integrating:

- **axe-core**: Automated accessibility testing
- **pa11y**: Command-line accessibility testing
- **Lighthouse CI**: Google's accessibility audits

## Security Scanning Tools

For enhanced security testing:

- **bandit**: Python security linter
- **safety**: Dependency vulnerability scanner
- **OWASP ZAP**: Web application security scanner

## Future Enhancements

- [ ] Load testing with Locust
- [ ] Browser automation with Selenium/Playwright
- [ ] Visual regression testing
- [ ] API contract testing
- [ ] Mutation testing
- [ ] Chaos engineering tests

## Troubleshooting

### ImportError: No module named 'app'

```bash
# Ensure you're in the project root
cd c:\Users\lucas\petorlandia\petorlandia

# Run tests with:
pytest tests/
```

### Database Errors

```python
# Tests use in-memory SQLite
# If you see database errors, check:
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
```

### CSRF Token Errors

```python
# Most tests disable CSRF for simplicity:
app.config['WTF_CSRF_ENABLED'] = False

# Security tests enable it explicitly to test protection
```

## Contributing

When adding new features:

1. Write tests first (TDD)
2. Ensure all existing tests pass
3. Add E2E test for complete workflows
4. Add security test if touching auth/access
5. Add accessibility test if changing UI
6. Update this README

## Questions?

See `TESTING_STRATEGY.md` for comprehensive testing strategy documentation.

---

**Last Updated**: January 2026
**Test Count**: 328+ existing tests + comprehensive new suites
**Coverage Target**: 90%+
