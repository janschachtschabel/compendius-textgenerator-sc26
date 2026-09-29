"""Load test of the compendium service: N requests at once, memory and CPU of the API container from its cgroup.

Run on the Docker host next to the service (Python 3.10+, standard library only):

    python lasttest.py --name 5-balanced --preset balanced Photosynthese Vulkan Demokratie Zellteilung Optik

Every topic is one request, all sent at once. --endpoint qa asks for ten QA pairs instead of a compendium, --url and
--container name the service, --api-key sends X-API-Key. Each run writes lasttest-<name>.json into the current
directory and prints one summary line. A topic the service has already answered is faster the second time (the
caches live in the workers), so a fair round uses new topics.

Memory comes from the cgroup of the container, sampled every 0.7 s with docker exec: rss is the memory of the
processes themselves (cgroup v1 total_rss, v2 anon), cache the page cache of the archives, which the kernel hands back
under pressure; usage holds both and is what API_MEMORY caps. CPU is the growth of the cgroup's CPU time.
"""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# One probe for both cgroup versions: v2 (Debian 13) first, v1 (Docker Desktop) otherwise
PROBE = (
    "if [ -f /sys/fs/cgroup/memory.current ]; then echo v2; cat /sys/fs/cgroup/memory.current; "
    "grep -E '^(anon|file) ' /sys/fs/cgroup/memory.stat; grep '^usage_usec ' /sys/fs/cgroup/cpu.stat; "
    "else echo v1; cat /sys/fs/cgroup/memory/memory.usage_in_bytes; "
    "grep -E '^(total_rss|total_cache) ' /sys/fs/cgroup/memory/memory.stat; "
    "cat /sys/fs/cgroup/cpuacct/cpuacct.usage; fi"
)
GIB = 1024**3


def parse_probe(text: str) -> dict[str, int]:
    """Usage, rss and cache in bytes and CPU time in nanoseconds from the output of PROBE."""
    lines = text.split()
    version, usage = lines[0], int(lines[1])
    stat = dict(zip(lines[2:6:2], (int(value) for value in lines[3:7:2]), strict=True))
    if version == "v2":
        return {"usage": usage, "rss": stat["anon"], "cache": stat["file"], "cpu_ns": int(lines[7]) * 1000}
    return {"usage": usage, "rss": stat["total_rss"], "cache": stat["total_cache"], "cpu_ns": int(lines[6])}


def sample(container: str) -> dict[str, float]:
    out = subprocess.run(["docker", "exec", container, "sh", "-c", PROBE], capture_output=True, text=True, check=True)
    return {"t": time.monotonic(), **parse_probe(out.stdout)}


def request(args: argparse.Namespace, topic: str, results: list[dict[str, object]]) -> None:
    body: dict[str, object] = {"topic": topic, "preset": args.preset}
    if args.endpoint == "qa":
        body["count"] = 10
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key
    req = urllib.request.Request(
        f"{args.url}/api/v2/{args.endpoint}", data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    started = time.monotonic()
    status, tokens, size, detail = 0, None, 0, ""
    try:
        with urllib.request.urlopen(req, timeout=400) as answer:
            status = answer.status
            payload = json.loads(answer.read().decode("utf-8"))
            size = len(payload.get("markdown", "")) if args.endpoint == "compendium" else len(payload.get("pairs", []))
            tokens = ((payload.get("audit") or {}).get("llm_tokens") or payload.get("llm_tokens") or {}).get("total")
    except urllib.error.HTTPError as error:
        status, detail = error.code, error.read().decode("utf-8", "replace")[:200]
    except (OSError, ValueError, http.client.HTTPException) as error:  # a measurement records every failure
        detail = repr(error)[:200]
    results.append(
        {
            "topic": topic,
            "status": status,
            "seconds": round(time.monotonic() - started, 1),
            "size": size,
            "tokens": tokens,
            "detail": detail,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("topics", nargs="+", help="one request per topic, all sent at once")
    parser.add_argument("--name", required=True, help="name of the run, part of the file name")
    parser.add_argument("--endpoint", choices=("compendium", "qa"), default="compendium")
    parser.add_argument("--preset", default="balanced")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--container", default="compendious-text-fastapi-api-1")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()
    if not args.url.startswith(("http://", "https://")):
        parser.error("--url braucht http:// oder https://")

    samples = [sample(args.container)]
    done = threading.Event()

    def sampler() -> None:
        while not done.is_set():
            samples.append(sample(args.container))
            time.sleep(0.7)

    watcher = threading.Thread(target=sampler, daemon=True)
    watcher.start()
    results: list[dict[str, object]] = []
    threads = [threading.Thread(target=request, args=(args, topic, results)) for topic in args.topics]
    wall = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    wall = time.monotonic() - wall
    time.sleep(1.5)
    done.set()
    watcher.join()
    samples.append(sample(args.container))
    base = samples[0]
    pairs = itertools.pairwise(samples)
    cores = [(b["cpu_ns"] - a["cpu_ns"]) / 1e9 / (b["t"] - a["t"]) for a, b in pairs if b["t"] > a["t"]]
    summary = {
        "scenario": args.name,
        "endpoint": args.endpoint,
        "preset": args.preset,
        "concurrent": len(args.topics),
        "wall_s": round(wall, 1),
        "idle_rss_gib": round(base["rss"] / GIB, 2),
        "peak_rss_gib": round(max(s["rss"] for s in samples) / GIB, 2),
        "peak_usage_gib": round(max(s["usage"] for s in samples) / GIB, 2),
        "peak_cache_gib": round(max(s["cache"] for s in samples) / GIB, 2),
        "cpu_seconds": round((samples[-1]["cpu_ns"] - base["cpu_ns"]) / 1e9, 1),
        "peak_cores": round(max(cores), 2) if cores else None,
        "mean_cores": round(sum(cores) / len(cores), 2) if cores else None,
        "requests": sorted(results, key=lambda r: str(r["topic"])),
    }
    target = Path.cwd() / f"lasttest-{args.name}.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    times = sorted(float(str(r["seconds"])) for r in results)
    print(
        f"{args.name}: {len(args.topics)} x {args.endpoint}/{args.preset}, {times[0]}-{times[-1]} s je Anfrage, "
        f"Status {[r['status'] for r in results]}, Tokens {[r['tokens'] for r in results]}, "
        f"RSS {summary['idle_rss_gib']} -> {summary['peak_rss_gib']} GiB, "
        f"mit Cache bis {summary['peak_usage_gib']} GiB, "
        f"CPU {summary['cpu_seconds']} s, Kerne bis {summary['peak_cores']}"
    )


if __name__ == "__main__":
    main()
