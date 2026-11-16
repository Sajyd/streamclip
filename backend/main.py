"""ASGI entrypoint (`main:app`) for Vercel and for `uvicorn main:app`."""

from app.main import create_app

app = create_app()
