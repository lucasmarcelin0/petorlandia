#!/usr/bin/env python
"""Run the Flask app in production-like mode (no debug, no reloader).

Usage:
    python run_production.py
    python run_production.py --port 5000
    python run_production.py --host 0.0.0.0 --port 8000
"""
import argparse
import os

# Disable debug mode
os.environ.setdefault("FLASK_DEBUG", "0")
os.environ.setdefault("FLASK_ENV", "production")

# Disable template auto-reload for speed
os.environ.setdefault("TEMPLATES_AUTO_RELOAD", "0")

from app import socketio
from app_factory import create_app

app = create_app()


def main():
    parser = argparse.ArgumentParser(description="Run Flask app in production mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    args = parser.parse_args()

    print(f"Starting server at http://{args.host}:{args.port}")
    print("Running in production mode (no debug, no reloader)")
    print("Press Ctrl+C to stop\n")

    # Use socketio.run for WebSocket support
    socketio.run(
        app,
        host=args.host,
        port=args.port,
        debug=False,
        use_reloader=False,
        log_output=True,
    )


if __name__ == "__main__":
    main()
