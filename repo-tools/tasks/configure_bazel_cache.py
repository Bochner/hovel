#!/usr/bin/env python3
"""Configure the GitHub runner boundary before any Bazel invocation."""
from __future__ import annotations

import os
import re
import shlex
import sys
import tempfile
from pathlib import Path


def rc_path(env: dict[str, str]) -> Path:
    return Path(env.get("RUNNER_TEMP", tempfile.gettempdir())) / "hovel-buildbuddy.bazelrc"


def configure(env: dict[str, str]) -> dict[str, str]:
    user_home = Path(env["HOME"])
    path = rc_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = env.get("BUILDBUDDY_API_KEY", "")
    if key and not re.fullmatch(r"[A-Za-z0-9_+/=-]+", key):
        raise ValueError("BuildBuddy API key contains unsupported characters")
    configs = ["--config=github-actions", "--config=ci"]
    lines = [
        "common --noannounce_rc",
        "build:github-actions --repository_cache=" + shlex.quote(str(user_home / ".cache/bazel-repository")),
    ]
    if key:
        lines.append("build:buildbuddy --remote_header=x-buildbuddy-api-key=" + key)
        configs.append("--config=buildbuddy")
    # Open with restrictive permissions before writing, including on reruns.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as rc:
        os.fchmod(rc.fileno(), 0o600)
        rc.write("\n".join(lines) + "\n")
    bep_dir = path.parent / "hovel-bep"
    bep_dir.mkdir(mode=0o700, exist_ok=True)
    return {
        "HOVEL_BAZEL_STARTUP_ARGS": "--bazelrc=" + str(path),
        "HOVEL_BAZEL_ARGS": " ".join(configs),
        "HOVEL_BEP_DIR": str(bep_dir),
        "HOVEL_TIMING_DIR": str(path.parent / "hovel-timing"),
        "HOVEL_BUILDBUDDY_MODE": "remote-execution" if key else "local (no credential)",
        "HOVEL_BUILDBUDDY_URL": "https://vibepwners.buildbuddy.io",
    }


def main() -> int:
    env = dict(os.environ)
    if sys.argv[1:] == ["--cleanup"]:
        rc_path(env).unlink(missing_ok=True)
        return 0
    if sys.argv[1:]:
        raise SystemExit("usage: configure_bazel_cache.py [--cleanup]")
    values = configure(env)
    # GitHub masks secrets already; also register this key for nonstandard callers.
    key = env.get("BUILDBUDDY_API_KEY", "")
    if key and env.get("GITHUB_ACTIONS"):
        print("::add-mask::" + key)
    destination = env.get("GITHUB_ENV")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as output:
            for name, value in values.items():
                if "\n" in value or "\r" in value:
                    raise ValueError("invalid GitHub environment value")
                output.write(name + "=" + value + "\n")
    print("BuildBuddy mode: " + values["HOVEL_BUILDBUDDY_MODE"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
