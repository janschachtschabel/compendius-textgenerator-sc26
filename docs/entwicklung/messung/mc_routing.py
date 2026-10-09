"""M83 (09.10.2026): the service through the b-api's routing (D97) or a provider, in process in the one-off container.

The settings come from the environment, so one script runs every variant: B_API_PROVIDER=router with B_API_ROUTE, or
B_API_PROVIDER=openai for the same requests without the router. Writes /health's LLM block and per compendium (parts
1 and 2) the time, the tokens, the frontmatter's llm block (provider, route, the model that answered) and the audit's
note to <out.json>; the service's log goes to stderr: the start line, the model check, the line that names the model
answering behind the route, and the line of each compendium. The b-api is asked for real, with the key in B_API_KEY;
its cache stays out of the way, since every call carries a safety_identifier of its own (D70).

Usage, with the working tree mounted over the code of the image (Git Bash):

  cat mc_routing.py | MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -v <repo>/app:/src/app:ro \\
      -v <ordner>:/out -e PYTHONPATH=/src -e LLM_ENABLED=true -e B_API_KEY \\
      -e B_API_BASE_URL=https://b-api.staging.openeduhub.net -e B_API_PROVIDER=router -e B_API_ROUTE=<route> \\
      api python - /out/<lauf>.json <label> balanced,best-quality-generated Optik Photosynthese 2> <lauf>.log
"""

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

import app.llm.client as client_module
from app.main import create_app

# the mounted working tree, not the code of the image
print("APP", client_module.__file__, hasattr(client_module, "ROUTER"), file=sys.stderr, flush=True)
out_path, label, presets, topics = Path(sys.argv[1]), sys.argv[2], sys.argv[3].split(","), sys.argv[4:]
result: dict = {"label": label, "runs": []}
with TestClient(create_app()) as client:
    health = client.get("/health").json()["components"]["llm"]
    result["health"] = {key: health.get(key) for key in ("enabled", "provider", "model", "route", "available")}
    result["health"]["check"] = (health.get("check") or {}).get("message")
    print("HEALTH", json.dumps(result["health"], ensure_ascii=False), file=sys.stderr, flush=True)
    for topic in topics:
        for preset in presets:
            start = time.monotonic()
            response = client.post(
                "/api/v2/compendium", json={"topic": topic, "preset": preset, "parts": ["world", "curricula"]}
            )
            took = round(time.monotonic() - start, 2)
            body = response.json()
            front = (body.get("frontmatter") or {}).get("llm") or {}
            audit = body.get("audit") or {}
            tokens = audit.get("llm_tokens") or {}
            row = {
                "topic": topic,
                "preset": preset,
                "status": response.status_code,
                "seconds": took,
                "tokens": tokens.get("total"),
                "calls": tokens.get("calls"),
                "provider": front.get("provider"),
                "route": front.get("route"),
                "model": front.get("model"),
                "note": (audit.get("llm") or {}).get("note"),
            }
            result["runs"].append(row)
            print("RUN", json.dumps(row, ensure_ascii=False), file=sys.stderr, flush=True)
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
