"""Read GitHub and BuildBuddy timings without publishing raw logs or options."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
import urllib.parse


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
            redirected.remove_header("X-buildbuddy-api-key")
        return redirected


def request(url: str, token: str, body: dict | None = None) -> bytes:
    headers = {"Accept": "application/json"}
    if "api.github.com" in url:
        headers["Authorization"] = "Bearer " + token
    else:
        headers["x-buildbuddy-api-key"] = token
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urllib.request.build_opener(SafeRedirect()).open(req, timeout=90) as response:
        return response.read()


def seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()


def audit(repo: str, run_id: str, github_token: str, buildbuddy_key: str) -> dict:
    base = "https://api.github.com/repos/" + repo
    run = json.loads(request(base + "/actions/runs/" + run_id, github_token))
    jobs = []
    page = 1
    while True:
        batch = json.loads(request(base + "/actions/runs/" + run_id + "/jobs?per_page=100&page=" + str(page), github_token))["jobs"]
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    completed = [j for j in jobs if j["status"] == "completed"]
    result = {
        "schema_version": "hovel.ci-audit/v1", "run_url": run["html_url"],
        "status": run["status"], "conclusion": run["conclusion"],
        "workflow_elapsed_seconds": seconds(run["created_at"], max(j["completed_at"] for j in completed)) if len(completed) == len(jobs) and jobs else None,
        "summed_job_seconds": sum(seconds(j["started_at"], j["completed_at"]) for j in completed),
        "jobs": [{"name": j["name"], "seconds": seconds(j["started_at"], j["completed_at"]), "conclusion": j["conclusion"]} for j in completed],
        "invocations": [], "unavailable": [],
    }
    ids = set()
    for job in completed:
        try:
            log = request(base + "/actions/jobs/" + str(job["id"]) + "/logs", github_token).decode(errors="replace")
            ids.update(re.findall(r"https://vibepwners\.buildbuddy\.io/invocation/([a-f0-9-]{36})", log))
        except (OSError, ValueError):
            result["unavailable"].append("job logs: " + job["name"])
    def invocation(uuid: str) -> dict:
        url = "https://vibepwners.buildbuddy.io/"
        public = json.loads(request(url + "api/v1/GetInvocation", buildbuddy_key, {"selector": {"invocation_id": uuid}, "include_metadata": True}))["invocation"][0]
        detail = json.loads(request(url + "rpc/BuildBuddyService/GetInvocation", buildbuddy_key, {"lookup": {"invocationId": uuid}}))["invocation"][0]
        executions = json.loads(request(url + "rpc/BuildBuddyService/GetExecution", buildbuddy_key, {"executionLookup": {"invocationId": uuid}})).get("execution", [])
        metadata = {m["key"]: m.get("value", "") for m in public.get("buildMetadata", [])}
        record = {"id": uuid, "commit": public.get("commitSha"), "job": metadata.get("HOVEL_JOB"), "command": public.get("command"), "seconds": int(public.get("durationUsec", 0)) / 1e6, "cache": {}, "execution_records": len(executions), "phases_seconds": {}}
        for key in ["actionCacheHits", "actionCacheMisses", "totalDownloadSizeBytes", "totalDownloadTransferredSizeBytes"]:
            record["cache"][key] = int(detail.get("cacheStats", {}).get(key, 0))
        for phase, start, end in [("queue", "queuedTimestamp", "workerStartTimestamp"), ("fetch", "inputFetchStartTimestamp", "inputFetchCompletedTimestamp"), ("execute", "executionStartTimestamp", "executionCompletedTimestamp"), ("upload", "outputUploadStartTimestamp", "outputUploadCompletedTimestamp")]:
            samples = sorted(seconds(m[start], m[end]) for e in executions if start in (m := e.get("executedActionMetadata", {})) and end in m)
            record["phases_seconds"][phase] = {"sum": sum(samples), "p95": samples[min(len(samples) - 1, int(len(samples) * .95))] if samples else None}
        return record
    if buildbuddy_key:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [(uuid, pool.submit(invocation, uuid)) for uuid in sorted(ids)]
            for uuid, future in futures:
                try:
                    result["invocations"].append(future.result())
                except (OSError, ValueError, KeyError, IndexError):
                    result["unavailable"].append("invocation: " + uuid)
    else:
        result["unavailable"].append("BuildBuddy credential")
    result["units"] = "Seconds and bytes. Summed phases overlap; cache counters count requests and repeated worker/client transfers, not unique actions or billed egress."
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", default="vibepwners/hovel")
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    key = os.environ.get("BUILDBUDDY_API_KEY", "")
    if args.credential_file:
        match = re.search(r"x-buildbuddy-api-key=([^\s]+)", args.credential_file.read_text())
        key = match.group(1) if match else ""
    data = audit(args.repo, args.run_id, token, key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print("CI audit saved; unavailable records:", len(data["unavailable"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
