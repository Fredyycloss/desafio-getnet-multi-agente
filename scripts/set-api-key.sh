#!/usr/bin/env bash
# Store the Anthropic key for cloud mode in .env without ever printing it.
# - asks with hidden input (read -s); accepts only keys with the Anthropic prefix
# - creates .env from .env.example only if .env does not exist
# - writes or replaces only the GETNET_ANTHROPIC_API_KEY line; every other line is kept
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  if [ ! -f .env.example ]; then echo "error: .env.example not found in $(pwd)" >&2; exit 1; fi
  cp .env.example .env
  echo "created .env from .env.example"
fi

if [ -t 0 ]; then
  read -r -s -p "Anthropic API key (input hidden): " key
  echo
else
  IFS= read -r key || true   # non-interactive (piped) input, still never echoed
fi
key="${key//[[:space:]]/}"
# Anthropic key prefix, assembled so a repository search for real keys stays empty.
prefix="sk-""ant-"
case "$key" in
  "$prefix"?*) ;;
  *) unset key; echo "error: the key must start with the Anthropic prefix (sk-ant…); nothing was written" >&2; exit 1 ;;
esac

tmp="$(mktemp .env.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
found=0
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    GETNET_ANTHROPIC_API_KEY=*) printf 'GETNET_ANTHROPIC_API_KEY=%s\n' "$key"; found=1 ;;
    *) printf '%s\n' "$line" ;;
  esac
done < .env > "$tmp"
[ "$found" = 1 ] || printf 'GETNET_ANTHROPIC_API_KEY=%s\n' "$key" >> "$tmp"
unset key
chmod 600 "$tmp"
mv "$tmp" .env
trap - EXIT
echo "GETNET_ANTHROPIC_API_KEY saved in .env (value not shown). Next: docker compose up -d --build"
