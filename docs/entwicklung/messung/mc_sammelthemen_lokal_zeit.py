"""M40, the clean timing: the question N alone to each local model, on the 45 topics, with nothing else on the CPU.

mc_sammelthemen_lokal.py timed the questions while part 1 and other work ran beside them. Here each model answers the
question N (word for word, with the JSON schema of M40, without Qwen3's thinking) for the 25 set-like and the 20
ordinary topics in a row, after one warm-up question; llama-server with THREADS threads, one model at a time.

Usage (in the development container, with mc_sammelthemen.py and eval/artikelwahl/korpus_labels.yaml in <dir>, the
models under /opt/lokal/models and llama.cpp under /opt/lokal/llama-b11206):
python mc_sammelthemen_lokal_zeit.py <dir> <threads> <out.json>
"""

from __future__ import annotations

import ast
import json
import os
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

MODELS = ["LFM2-700M-Q4_K_M.gguf", "LFM2.5-1.2B-Instruct-Q4_K_M.gguf", "Qwen3-0.6B-Q8_0.gguf"]
MODEL_DIR = "/opt/lokal/models"
LLAMA = "/opt/lokal/llama-b11206"
URL = "http://127.0.0.1:8081"
SCHEMA = {
    "type": "object",
    "properties": {
        "uebersicht": {"type": "string"},
        "artikel": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["uebersicht", "artikel"],
}

directory, threads, out = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
m37 = ast.parse((directory / "mc_sammelthemen.py").read_text(encoding="utf-8"))
M37 = {
    n.targets[0].id: ast.literal_eval(n.value)
    for n in m37.body
    if isinstance(n, ast.Assign)
    and isinstance(n.targets[0], ast.Name)
    and n.targets[0].id in ("TOPICS", "NEW_SYSTEM", "NEW_QUESTION", "MAX_NAMED")
}
topics = [*M37["TOPICS"], *yaml.safe_load((directory / "korpus_labels.yaml").read_text(encoding="utf-8"))["labels"]]


def stop_servers() -> None:
    """The container has no pkill: end every llama-server found in /proc, and wait until none answers."""
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"llama-server" in f.read().split(b"\0")[0]:
                    os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    for _ in range(40):
        try:
            httpx.get(f"{URL}/health", timeout=1)
        except httpx.HTTPError:
            return
        time.sleep(0.5)
    raise SystemExit("an old llama-server still answers")


def start_server(model: str) -> subprocess.Popen[bytes]:
    stop_servers()
    server = subprocess.Popen(
        [f"{LLAMA}/llama-server", "-m", f"{MODEL_DIR}/{model}", "-t", str(threads), "-c", "4096", "-np", "1",
         "--host", "127.0.0.1", "--port", "8081", "--jinja"],
        env={"LD_LIBRARY_PATH": f"/opt/lokal/lib:{LLAMA}"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    for _ in range(120):
        try:
            if httpx.get(f"{URL}/health", timeout=2).status_code == 200:
                loaded = httpx.get(f"{URL}/props", timeout=5).json().get("model_path", "")
                if not loaded.endswith(model):
                    server.kill()
                    raise SystemExit(f"the server serves {loaded}, not {model}")
                return server
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    server.kill()
    raise SystemExit(f"llama-server did not come up with {model}")


def ask(topic: str) -> tuple[float, dict[str, Any]]:
    question = M37["NEW_QUESTION"].format(topic=topic, count=M37["MAX_NAMED"])
    body = {
        "messages": [{"role": "system", "content": M37["NEW_SYSTEM"]}, {"role": "user", "content": question}],
        "max_tokens": 400,
        "temperature": 0,
        "response_format": {"type": "json_schema", "json_schema": {"schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    answer = httpx.post(f"{URL}/v1/chat/completions", json=body, timeout=180).json()
    return time.perf_counter() - started, answer


result: dict[str, Any] = {"threads": threads, "modelle": {}}
for model in MODELS:
    server = start_server(model)
    try:
        ask("Wärme")  # warm-up, not counted
        rows = []
        for topic in topics:
            seconds, answer = ask(topic)
            timing = answer.get("timings", {})
            rows.append({"thema": topic, "sekunden": round(seconds, 2),
                         "tokens_aus": answer.get("usage", {}).get("completion_tokens", 0),
                         "prompt_ms": round(timing.get("prompt_ms", 0)),
                         "erzeugung_ms": round(timing.get("predicted_ms", 0))})  # fmt: skip
        secs = [row["sekunden"] for row in rows]
        result["modelle"][model] = {
            "median": statistics.median(secs),
            "max": max(secs),
            "unter_3s": sum(s <= 3 for s in secs),
            "fragen": rows,
        }
        print(f"{model}: Median {statistics.median(secs):.2f} s, max {max(secs):.2f} s, "
              f"bis 3 s: {sum(s <= 3 for s in secs)} von {len(secs)}", flush=True)  # fmt: skip
    finally:
        server.terminate()
        server.wait(timeout=30)
out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
