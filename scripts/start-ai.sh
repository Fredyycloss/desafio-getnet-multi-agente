#!/bin/sh
set -eu

docker compose -f docker-compose.yml -f docker-compose.ai.yml --profile ai up --build "$@"
