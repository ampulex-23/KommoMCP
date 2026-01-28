#!/bin/bash
curl -s -X POST https://amomcp.metodoxia25.net/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kommo_pipelines_list","arguments":{}}}'
