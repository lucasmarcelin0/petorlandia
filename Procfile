web: gunicorn 'app_factory:create_app()' --worker-class eventlet --workers 1 --log-file -
scheduler: python scheduler.py
