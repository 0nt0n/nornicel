#!/usr/bin/env bash
set -u

(
  for attempt in 1 2 3 4 5; do
    if python scripts/run_pipeline.py --load-only; then
      echo "[serve] граф построен из data/processed/*.json"
      break
    fi
    echo "[serve] попытка $attempt: Neo4j недоступен, повтор через 15с..."
    sleep 15
  done
) &

exec streamlit run src/app/streamlit_app.py \
    --server.port "${PORT:-8501}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false
