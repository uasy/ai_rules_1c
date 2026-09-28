#!/usr/bin/env python3
"""Remove a managed publication after -DryRun and explicit -Force."""
from web_common import main

if __name__ == "__main__":
    raise SystemExit(main("unpublish"))
