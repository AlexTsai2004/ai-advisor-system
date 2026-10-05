#!/bin/bash
# Pull all 3 models into the running worker containers
# Run this after docker-compose up if models weren't auto-pulled

set -e

echo "Pulling models (CPU-only, small variants)..."

docker exec worker1 ollama pull qwen2.5:1.5b
docker exec worker2 ollama pull llama3.2:3b
docker exec worker3 ollama pull gemma2:2b

echo "All models pulled."
