#!/bin/sh
# One-command demo: replay the golden set for both environments (no API key needed), then serve the dashboard.
set -e
if [ "${ARBITER_DEMO_RUN:-1}" = "1" ]; then
  for env in store productivity; do
    arbiter run --env "$env" --config configs/gate.yaml --set golden --mode replay --no-judge \
      --label "docker demo replay" --out /tmp/demo-runs
  done
  arbiter import --results-dir /tmp/demo-runs
fi
exec arbiter dashboard --host 0.0.0.0 --port 8000
