"""Vercel entrypoint for the FastAPI application."""

import sys
from pathlib import Path

# Add the parent directory to the path so we can import from the root
sys.path.insert(0, str(Path(__file__).parent.parent))

from approval_server import app

# Vercel expects the FastAPI app to be exported as 'app'
