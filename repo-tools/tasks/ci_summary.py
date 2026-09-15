"""Render only allowlisted provenance from local BES events into a job summary."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def invocations(directory: Path) -> list[dict[str, str]]:
    results = []
    for path in sorted(directory.glob("*.json")):
        record = {"id": "", "command": "", "status": "incomplete"}
        with path.open(encoding="utf-8") as events:
            for line in events:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # An interrupted build can leave a partial final event.
                if "started" in event:
                    record["id"] = event["started"].get("uuid", "")
                    record["command"] = event["started"].get("command", "")
                if "finished" in event:
                    record["status"] = event["finished"].get("exitCode", {}).get("name", "unknown")
        if re.fullmatch(r"[0-9a-fA-F-]{36}", record["id"]):
            results.append(record)
    return results


def cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def render(env: dict[str, str]) -> str:
    lines = [
        "### BuildBuddy invocations",
        "",
        "Job: **" + cell(env.get("JOB_STATUS", "unknown")) + "**. Backend: " + cell(env.get("HOVEL_BUILDBUDDY_MODE", "not configured")) + ".",
        "",
    ]
    directory = env.get("HOVEL_BEP_DIR")
    timing_dir = env.get("HOVEL_TIMING_DIR")
    if timing_dir:
        lines.extend(["Task times include post-build host execution; nested tasks overlap.", "", "| Task | Seconds | Exit |", "| --- | ---: | ---: |"])
        for path in sorted(Path(timing_dir).glob("*.json")):
            try:
                task = json.loads(path.read_text())
                lines.append("| " + cell(task["task"]) + " | " + str(round(float(task["duration_seconds"]), 2)) + " | " + str(int(task["exit_code"])) + " |")
            except (OSError, ValueError, KeyError, TypeError):
                lines.append("| Timing unavailable | — | — |")
        lines.append("")
    records = invocations(Path(directory)) if directory else []
    if not records:
        return "\n".join(lines + ["No Bazel invocation events were recorded.", ""])
    remote = env.get("HOVEL_BUILDBUDDY_MODE") == "remote-execution"
    lines.extend(["| Invocation | Command | Result |", "| --- | --- | --- |"])
    for record in records:
        label = record["id"][:8]
        if remote:
            label = "[" + label + "](https://vibepwners.buildbuddy.io/invocation/" + record["id"] + ")"
        lines.append("| " + label + " | " + cell(record["command"]) + " | " + cell(record["status"]) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    summary = render(dict(os.environ))
    output = os.environ.get("GITHUB_STEP_SUMMARY")
    if output:
        with Path(output).open("a", encoding="utf-8") as destination:
            destination.write(summary)
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
