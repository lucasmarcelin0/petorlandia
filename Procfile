release: flask db upgrade
web: gunicorn 'app_factory:create_app()' --workers 1 --worker-class gthread --threads 4 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --log-file -
scheduler: python scheduler.py
