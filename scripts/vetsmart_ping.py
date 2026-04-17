"""
vetsmart_ping.py  (v2 — bypass Cloudflare)
============================================
Testa em segundos se a autenticacao e conectividade com o VetSmart estao OK.
Usa headers de navegador real para nao ser bloqueado pelo Cloudflare WAF.

    python scripts/vetsmart_ping.py
"""

import json, sys
import requests

PARSE_URL        = "https://parse.vetsmart.com.br/parse"
PARSE_APP_ID     = "XhI4EJ09WGTwlYIT8kpQDrsVEsCjwatFNHDHQOEi"
PARSE_SESSION    = "r:7046f7c91b7784a7e83f744bfdc7b0b1"
PARSE_INSTALL_ID = "abd97cd5-c0b6-497a-9002-d0c9f22b10bd"
CLIENT_VERSION   = "js6.1.1"

# Headers de navegador real (copiados do network dump do Chrome)
BROWSER_HEADERS = {
    "User-Agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/147.0.0.0 Safari/537.36",
    "sec-ch-ua":          '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Accept-Language":    "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept":             "*/*",
    "Origin":             "https://prontuario.vetsmart.com.br",
    "Referer":            "https://prontuario.vetsmart.com.br/",
    "Sec-Fetch-Dest":     "empty",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Site":     "same-site",
}

print("=" * 60)
print("VetSmart Parse Server — Teste de conectividade")
print("=" * 60)
print(f"URL   : {PARSE_URL}")
print(f"AppId : {PARSE_APP_ID[:20]}...")
print(f"Token : {PARSE_SESSION[:20]}...")
print()

# ── Tentativa 1: POST com _method:GET + content-type:text/plain (jeito do JS SDK) ──
print("[1] POST /users/me com _method:GET (jeito do JS SDK)...")
try:
    payload = {
        "_method":         "GET",
        "_ApplicationId":  PARSE_APP_ID,
        "_ClientVersion":  CLIENT_VERSION,
        "_InstallationId": PARSE_INSTALL_ID,
        "_SessionToken":   PARSE_SESSION,
    }
    r = requests.post(
        f"{PARSE_URL}/users/me",
        headers={**BROWSER_HEADERS, "Content-Type": "text/plain"},
        data=json.dumps(payload),
        timeout=20,
    )
    print(f"    Status: HTTP {r.status_code}")
    if r.status_code == 200:
        user = r.json()
        print(f"    ✅ SUCESSO!")
        print(f"       Usuario : {user.get('fullName') or user.get('name')}")
        print(f"       E-mail  : {user.get('email')}")
        print(f"       ObjectId: {user.get('objectId')}")
        print()
        print("=" * 60)
        print("Proximo passo: python scripts/vetsmart_discover.py")
        print("=" * 60)
        sys.exit(0)
    else:
        body = r.text[:200].replace("\n", " ")
        print(f"    Body: {body}...")
except Exception as e:
    print(f"    Erro: {e}")

# ── Tentativa 2: GET com headers X-Parse-* e browser headers ──
print("\n[2] GET /users/me com headers X-Parse-* + browser headers...")
try:
    r = requests.get(
        f"{PARSE_URL}/users/me",
        headers={
            **BROWSER_HEADERS,
            "X-Parse-Application-Id":  PARSE_APP_ID,
            "X-Parse-Session-Token":   PARSE_SESSION,
            "X-Parse-Installation-Id": PARSE_INSTALL_ID,
        },
        timeout=20,
    )
    print(f"    Status: HTTP {r.status_code}")
    if r.status_code == 200:
        user = r.json()
        print(f"    ✅ SUCESSO!")
        print(f"       Usuario : {user.get('fullName') or user.get('name')}")
        print()
        print("=" * 60)
        print("Proximo passo: python scripts/vetsmart_discover.py")
        print("=" * 60)
        sys.exit(0)
    else:
        body = r.text[:200].replace("\n", " ")
        print(f"    Body: {body}...")
except Exception as e:
    print(f"    Erro: {e}")

# ── Falha ────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("❌ Nao foi possivel autenticar via HTTP direto.")
print()
print("O Cloudflare WAF do VetSmart esta bloqueando as requisicoes Python.")
print()
print("SOLUCAO: usar o navegador via Playwright (funciona 100%):")
print()
print("  1. Instale Playwright:")
print("     pip install playwright")
print("     playwright install chromium")
print()
print("  2. Rode a extracao via browser:")
print("     python scripts/exportar_clientes_vetsmart.py")
print()
print("  Isso abre um Chrome logado que o Cloudflare aceita.")
print("  O JSON gerado pode ser importado com migrate_vetsmart.py.")
print()
print("Se o token expirou:")
print("  - Abra o VetSmart logado, F12 → Application → Local Storage")
print("  - Copie o 'sessionToken' da chave Parse/.../currentUser")
print("  - Atualize PARSE_SESSION nos 3 scripts (.py)")
print("=" * 60)
sys.exit(1)
