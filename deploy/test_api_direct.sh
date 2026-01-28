#!/bin/bash
source /opt/kommo-mcp/.env
echo "Subdomain: $KOMMO_SUBDOMAIN"
echo "Token length: ${#KOMMO_ACCESS_TOKEN}"
curl -s -X GET "https://${KOMMO_SUBDOMAIN}.amocrm.ru/api/v4/account" \
  -H "Authorization: Bearer ${KOMMO_ACCESS_TOKEN}" | head -c 500
