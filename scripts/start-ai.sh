#!/bin/sh
# Offline mode: local Qwen3 1.7B (no key, no cost) even when a cloud key exists in .env.
# Single compose file: the offline profile adds the model pull; these variables switch the API.
set -eu
export LLM_PROVIDER=ollama OLLAMA_ENABLED=true OLLAMA_REQUIRED=true
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3:1.7b}" OLLAMA_EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
docker compose --profile offline up --build "$@"
