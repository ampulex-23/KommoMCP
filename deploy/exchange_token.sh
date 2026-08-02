#!/bin/bash
# Exchange authorization code for access token

CLIENT_ID="${KOMMO_CLIENT_ID:?set KOMMO_CLIENT_ID}"
CLIENT_SECRET="${KOMMO_CLIENT_SECRET:?set KOMMO_CLIENT_SECRET}"
AUTH_CODE="${KOMMO_AUTH_CODE:?set KOMMO_AUTH_CODE}"
REDIRECT_URI="${KOMMO_REDIRECT_URI:?set KOMMO_REDIRECT_URI}"

echo "Exchanging authorization code for access token..."

curl -s -X POST "${KOMMO_BASE_URL:?set KOMMO_BASE_URL}/oauth2/access_token" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_id\": \"${CLIENT_ID}\",
    \"client_secret\": \"${CLIENT_SECRET}\",
    \"grant_type\": \"authorization_code\",
    \"code\": \"${AUTH_CODE}\",
    \"redirect_uri\": \"${REDIRECT_URI}\"
  }"
