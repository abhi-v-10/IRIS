"""WSGI entry point for a production server (gunicorn on Render, Railway, Fly.io, ...).

Local development still uses `python run.py`; this module only exists so that a WSGI
server can import a ready application object:

    gunicorn --bind 0.0.0.0:10000 wsgi:app
"""
from iris import create_app

app = create_app()
