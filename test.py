import requests
import hmac
import hashlib
import json

url = "https://www.petorlandia.com.br/notificacoes"
secret = b"f2378fa55dfb250b5b138a96e3fe72cc8378de846dc6dc518ca8bbff8baa18d3"
body = {"type": "payment", "data": {"id": "999999999"}}
json_body = json.dumps(body).encode("utf-8")

signature = hmac.new(secret, json_body, hashlib.sha256).hexdigest()

headers = {
    "Content-Type": "application/json",
    "X-MP-Signature": signature
}

r = requests.post(url, data=json_body, headers=headers)
print("Status:", r.status_code)
print("Response:", r.text)
