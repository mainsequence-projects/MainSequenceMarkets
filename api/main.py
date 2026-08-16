"""Expose the apps/v1 FastAPI application through the platform discovery path."""

from apps.v1.main import app

__all__ = ["app"]
