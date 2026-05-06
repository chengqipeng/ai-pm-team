#!/bin/bash
TOKEN=$(python3 product-specs/metadata-system/sql/gen_token.py)
ID=9762144152239979

echo "=== BEFORE ==="
curl -s "http://127.0.0.1:18010/entity/data/leadHighSea/$ID" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep depart_api_key

echo "=== PUT (change to rd_backend) ==="
curl -s -X PUT "http://127.0.0.1:18010/entity/data/leadHighSea/$ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"大客户线索公海","depart_api_key":"rd_backend","dbc_smallint1":1,"dbc_smallint2":0,"dbc_smallint3":0,"dbc_smallint4":1,"dbc_bigint1":"30","dbc_bigint2":"20","dbc_bigint3":"5","dbc_bigint4":"10","dbc_bigint5":"0","dbc_bigint6":"30"}'
echo ""

echo "=== AFTER ==="
curl -s "http://127.0.0.1:18010/entity/data/leadHighSea/$ID" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | grep depart_api_key
