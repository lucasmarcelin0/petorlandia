import requests
import hmac
import hashlib
import json

# Corpo da notificação simulada (como o Mercado Pago envia)
body = {
    "type": "payment",
    "data": {
        "id": "118894082315"  # troque por um ID real se quiser ativar a lógica do banco
    },
    "live_mode": True
}

# Segredo HMAC (o mesmo que está no Heroku e no painel do Mercado Pago)
secret = b"f2378fa55dfb250b5b138a96e3fe72cc8378de846dc6dc518ca8bbff8baa18d3"

# Serializa e gera assinatura
json_body = json.dumps(body).encode("utf-8")
signature = hmac.new(secret, json_body, hashlib.sha256).hexdigest()

# Envia a requisição simulada
headers = {
    "Content-Type": "application/json",
    "X-MP-Signature": signature
}

response = requests.post("https://www.petorlandia.com.br/notificacoes", data=json_body, headers=headers)

# Resultado
print("Status:", response.status_code)
print("Resposta:", response.text)
