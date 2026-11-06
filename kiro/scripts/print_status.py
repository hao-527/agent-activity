#!/usr/bin/env python3
"""Print a one-glance summary of the pet's published status file."""
import json
import os
import sys


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
    lines = [
        " ".join(
            str(part)
            for part in (
                "[state]",
                data.get("overall"),
                "active=", data.get("active_count"),
                "sessions=", data.get("total_sessions"),
                "logs=", data.get("log_count"),
                "kiro=", "on" if data.get("kiro_running") else "off",
            )
        ),
        f"[message] {data.get('headline')} / {data.get('subline')}",
    ]
    try:
        for line in lines:
            print(line)
        sys.stdout.flush()
    except BrokenPipeError:
        # Piping into head/less is normal; exit quietly instead of tracing back.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
