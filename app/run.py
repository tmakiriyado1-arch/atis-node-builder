"""Production runner entrypoint for the NORA pipeline."""
from __future__ import annotations

from app.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
