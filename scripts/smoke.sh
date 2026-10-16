#!/usr/bin/env bash
# Usage: scripts/smoke.sh <gateway-api-key> [base-url]
# Lists tools and calls clock__get_time through the gateway as the key's owner.
KEY=${1:?api key}; URL=${2:-http://admin.localtest.me:8080}/mcp
H=(-H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")
echo "== tools/list"; curl -s "${H[@]}" "$URL" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | (jq -r '.result.tools[].name' 2>/dev/null || cat)
echo "== tools/call clock__get_time"; curl -s "${H[@]}" "$URL" -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"clock__get_time","arguments":{"timezone_name":"Asia/Kolkata"}}}'; echo
