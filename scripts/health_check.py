"""
Health check script for PetOrlândia application.

Verifies:
- Database connectivity
- Flask app initialization
- Required environment variables
- Model imports

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --verbose
"""
import argparse
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_flask_app():
    """Verify Flask app can be initialized."""
    try:
        from app import app
        logger.info("✓ Flask app initialized successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Flask app initialization failed: {e}")
        return False

def check_database():
    """Verify database connectivity."""
    try:
        from app import app, db
        with app.app_context():
            db.session.execute("SELECT 1")
            logger.info("✓ Database connection successful")
            return True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        return False

def check_models():
    """Verify all models can be imported."""
    try:
        from models.agenda import Consulta  # noqa: F401
        from models.loja import Payment  # noqa: F401
        from models.usuarios import User  # noqa: F401
        logger.info("✓ All models imported successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Model import failed: {e}")
        return False

def check_extensions():
    """Verify Flask extensions are initialized."""
    try:
        from extensions import db, login_manager, socketio, cors  # noqa: F401
        logger.info("✓ All extensions initialized successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Extension initialization failed: {e}")
        return False

def check_environment():
    """Verify required environment variables."""
    import os
    required_vars = [
        'FLASK_APP',
        'FLASK_ENV',
        'SQLALCHEMY_DATABASE_URI',
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        logger.warning(f"⚠ Missing environment variables: {', '.join(missing)}")
        return False
    
    logger.info("✓ All required environment variables present")
    return True

def main():
    """Run all health checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed output'
    )
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info(f"PetOrlândia Health Check - {datetime.now()}")
    logger.info("=" * 60)
    
    checks = [
        ("Flask App", check_flask_app),
        ("Environment", check_environment),
        ("Database", check_database),
        ("Models", check_models),
        ("Extensions", check_extensions),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"✗ {name} check crashed: {e}")
            results.append((name, False))
    
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status} - {name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        logger.info("=" * 60)
        logger.info("✓ All checks passed! Application is healthy.")
        logger.info("=" * 60)
        return 0
    else:
        logger.info("=" * 60)
        logger.error("✗ Some checks failed. Please review the errors above.")
        logger.info("=" * 60)
        return 1

if __name__ == '__main__':
    sys.exit(main())
