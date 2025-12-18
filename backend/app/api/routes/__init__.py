"""API routes package.

This package contains all API route handlers for the application.
"""
from . import analyze
from . import generate
from . import gboost
from . import assess

__all__ = [
    "analyze",
    "generate",
    "gboost",
    "assess",
]
