"""Time an Aspect child at the runner boundary, including its host executable."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def label(arguments: list[str]) -> str:
    # Record task/target identity, never arbitrary flags, runtime args or secrets.
    before = arguments[:arguments.index("--")] if "--" in arguments else arguments
    return " ".join([before[0]] + [a for a in before[1:] if a.startswith(("//", "@"))]) if before else "aspect"


def main() -> int:
    arguments = sys.argv[1:]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    result = subprocess.run(["aspect", *arguments], check=False)
    record = {
        "schema_version": "hovel.ci-task/v1",
        "task": label(arguments),
        "started_at": started,
        "duration_seconds": round(time.monotonic() - clock, 6),
        "exit_code": result.returncode,
    }
    try:
        directory = Path(os.environ["HOVEL_TIMING_DIR"])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        (directory / (str(uuid.uuid4()) + ".json")).write_text(json.dumps(record) + "\n")
    except (OSError, KeyError):
        print("Task timing unavailable", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
