"""Vercel serverless entrypoint: exposes the FastAPI app.

Deploy notes (Vercel dashboard):
- Set env vars SERPAPI_API_KEY + GEMINI_API_KEY (optional; without them the
  app runs its labeled fixture demo). Set SNAP_PATH=/tmp/snapshots.sqlite and
  CACHE_PATH=/tmp/cache.sqlite (serverless filesystem is ephemeral).
- Hobby functions cap at ~60s: typical live runs take ~25s; the progress page
  streams milestones the whole way.
"""
import os

os.environ.setdefault("SNAP_PATH", "/tmp/snapshots.sqlite")
os.environ.setdefault("CACHE_PATH", "/tmp/cache.sqlite")

from app.main import app  # noqa: E402  (env must be set before app import reads config)

app = app
