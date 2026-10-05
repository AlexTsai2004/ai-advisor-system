#!/bin/bash
set -e

# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait until Ollama is ready
echo "[start] Waiting for Ollama..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "[start] Ollama ready."

# Pull model if not already present
echo "[start] Pulling model: $MODEL"
ollama pull "$MODEL" || echo "[start] WARNING: could not pull $MODEL"

# Start worker Flask API
echo "[start] Starting worker API on port $PORT (model=$MODEL, persona=$PERSONA)"
exec python3 app.py
