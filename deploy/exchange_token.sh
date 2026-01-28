#!/bin/bash
# Exchange authorization code for access token

CLIENT_ID="deb0b3df-938d-4157-9892-a1d742ed227c"
CLIENT_SECRET="GKInQ3svPkrCtLWEvX8gDZah7F1Q0zP47NCGZwB49Lh4xx5187XVjleN9UtiiTJR"
AUTH_CODE="def502001ffb21914fbf87ecc8472612a9a27494efac5d7c2a2ee3025dab59ed09f0687f343aa5c7c2dac062d5723e1cc7bf44d6a1dd0e14c7936b805278d4a107c3982aa38b07b6e777582aae25bcb6232da1490d49f0e8f4b9666199af0eb09f1d866d140de80ca6c74cd3050b5db7d3b838219a1723aec74aafb8e0cbdf7fdf6aa9f357edc3ec8f51c3e520496d5e5e63019c2d81e39c97a85c37dfe06eb801dea4b7953b32e083135cf5868af4432c3e93727645bddcbae2e189f7a1d527cd07e1aa10f62d09ac651ddb80210c2dd1c29be6408608555812ca616ffa3cd1dcb516684cac2993d54b51037817c85af4da9aade60f1b9bffcbf2bd7d32bbd543a72351abc3ddfbef068a01219db78b44f6d48dd8a26d4db3391ccdbd1d5d6a505fdec1516e7556731b04ece31b6d81a7945d1d87786386fd92f6876f7ca5472237986aa6fb548ed7cb10db6c01c6182341efde7aec056f5b49bac370ecb71b507972f1a8a72951ef423e8c8a83fa13772096b6016c4a35e0ab63d9efcac0fc0fcce72ca1aab322f7445732db1e07e12b480a8b3f215008735268ab635a3e2e66e21dfd3b79b5253fdfc93502b6371dc625911488579d28b4b3bee38bbf05c5a6920dc9bd638059e69799a0e60fc21d7c02468ae845fb05e0fbac1dd864f7efa51006ace2afb878d5dbcfba0a0c420cea836d58a12e62d6"
REDIRECT_URI="https://amomcp.metodoxia25.net/callback"

echo "Exchanging authorization code for access token..."

curl -s -X POST "https://kkkonstantinov.amocrm.ru/oauth2/access_token" \
  -H "Content-Type: application/json" \
  -d "{
    \"client_id\": \"${CLIENT_ID}\",
    \"client_secret\": \"${CLIENT_SECRET}\",
    \"grant_type\": \"authorization_code\",
    \"code\": \"${AUTH_CODE}\",
    \"redirect_uri\": \"${REDIRECT_URI}\"
  }"
