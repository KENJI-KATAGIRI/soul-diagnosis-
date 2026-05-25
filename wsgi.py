"""Gunicorn 用エントリ（本番: gunicorn wsgi:application）。"""
from app import create_app

application = create_app()
