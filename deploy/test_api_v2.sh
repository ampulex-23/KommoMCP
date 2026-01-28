#!/bin/bash
source /opt/kommo-mcp/.env

# Try different API endpoints
echo "=== Testing api-b.amocrm.ru ==="
curl -s -X GET "https://api-b.amocrm.ru/api/v4/account" \
  -H "Authorization: Bearer ${KOMMO_ACCESS_TOKEN}" | head -c 300

echo ""
echo "=== Testing kkkonstantinov.amocrm.ru ==="
curl -s -X GET "https://kkkonstantinov.amocrm.ru/api/v4/account" \
  -H "Authorization: Bearer ${KOMMO_ACCESS_TOKEN}" | head -c 300
