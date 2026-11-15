#!/usr/bin/env bash
# Start the internal APIs in the background, then the public dashboard.
set -e
PORT="${PORT:-7860}"

python -m uvicorn mock_systems.rest_api.app:app --host 127.0.0.1 --port 8001 &
python -m uvicorn fhir_api.app:app --host 127.0.0.1 --port 8002 &

# wait (max ~20s) until the portal API answers, so pipeline steps that read it work
for i in $(seq 1 40); do
  python - <<'PY' && break
import urllib.request, sys
try:
    urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=1); sys.exit(0)
except Exception:
    sys.exit(1)
PY
  sleep 0.5
done

exec python -m streamlit run dashboard/app.py \
  --server.port "$PORT" --server.address 0.0.0.0 \
  --server.headless true --browser.gatherUsageStats false
