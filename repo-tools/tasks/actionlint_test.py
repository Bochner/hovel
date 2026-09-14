"""Validate GitHub workflow syntax and expressions with a declared binary."""
from pathlib import Path
import subprocess
import sys


if __name__ == "__main__":
    # Shellcheck/pyflakes are separate linters, not undeclared host dependencies.
    command = [str(Path(sys.argv[1]).resolve()), "-shellcheck=", "-pyflakes=", *sys.argv[2:]]
    raise SystemExit(subprocess.run(command, check=False).returncode)
