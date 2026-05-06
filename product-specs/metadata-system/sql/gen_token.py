import jwt, time
secret = "HongYangPlatformPaasDefaultSecretKey2025!@#$%^&*()"
payload = {
    "sub": "100000000000000006",
    "tenantId": 292193,
    "userId": 100000000000000006,
    "iat": int(time.time()),
    "exp": int(time.time()) + 86400
}
token = jwt.encode(payload, secret, algorithm="HS256")
print(token)
