#!/bin/bash
source /opt/kommo-mcp/.env
curl -s "https://${KOMMO_SUBDOMAIN}.amocrm.ru/api/v4/leads?limit=5" \
  -H "Authorization: Bearer ${KOMMO_ACCESS_TOKEN}" | head -c 1000
