#!/usr/bin/env python3
"""Exit 0 when the pet's status file was refreshed within N seconds."""
import json
import sys
import time

path = sys.argv[1]
limit = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
try:
    with open(path, encoding="utf-8") as handle:
        generated = float(json.load(handle).get("generated_at", 0))
except (OSError, ValueError, TypeError):
    sys.exit(1)
sys.exit(0 if 0 < time.time() - generated <= limit else 1)
