"""
Script para configurar SFA_GOOGLE_CREDENTIALS_JSON no Heroku via API REST.
Execute na raiz do projeto com: python set_heroku_credentials.py
"""
import json
import subprocess
import sys
import os

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

CREDENTIALS_FILE = "sfao-490521-bc2dc5933745.json"
APP_NAME = "petorlandia"


def get_heroku_token():
    """Obtém o token de autenticação do Heroku CLI."""
    try:
        result = subprocess.run(
            "heroku auth:token",
            capture_output=True, text=True, shell=True, check=True
        )
        token = result.stdout.strip()
        if token:
            return token
    except Exception:
        pass

    # Fallback: lê do arquivo de configuração do Heroku
    netrc_path = os.path.expanduser("~/.netrc")
    if os.path.exists(netrc_path):
        with open(netrc_path) as f:
            content = f.read()
        lines = content.split()
        for i, word in enumerate(lines):
            if word == "password" and i + 1 < len(lines):
                return lines[i + 1]

    return None


def set_config_via_api(app_name, token, key, value):
    """Define uma config var no Heroku via API REST."""
    url = f"https://api.heroku.com/apps/{app_name}/config-vars"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.heroku+json; version=3",
    }
    payload = json.dumps({key: value}).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers=headers, method="PATCH")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def main():
    # Verifica se o arquivo existe
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"ERRO: Arquivo '{CREDENTIALS_FILE}' não encontrado.")
        print("Execute este script na raiz do projeto.")
        sys.exit(1)

    # Lê e valida o JSON
    print(f"Lendo '{CREDENTIALS_FILE}'...")
    with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    try:
        parsed = json.loads(raw)
        print(f"JSON válido. Tipo: {parsed.get('type')}, Projeto: {parsed.get('project_id')}")
    except json.JSONDecodeError as e:
        print(f"ERRO: JSON inválido no arquivo: {e}")
        sys.exit(1)

    # Serializa em uma única linha
    single_line = json.dumps(parsed)

    # Obtém o token do Heroku
    print("Obtendo token de autenticação do Heroku...")
    token = get_heroku_token()
    if not token:
        print("ERRO: Não foi possível obter o token do Heroku.")
        print("Certifique-se de estar logado com: heroku login")
        sys.exit(1)
    print(f"Token obtido com sucesso (termina em ...{token[-6:]})")

    # Envia via API REST (sem problemas de quoting no Windows)
    print(f"\nConfigurando SFA_GOOGLE_CREDENTIALS_JSON no app '{APP_NAME}' via API...")
    status, body = set_config_via_api(APP_NAME, token, "SFA_GOOGLE_CREDENTIALS_JSON", single_line)

    if status == 200:
        print("Sucesso! Variável configurada corretamente no Heroku.")
        # Verifica se foi salvo corretamente
        result_vars = json.loads(body)
        saved = result_vars.get("SFA_GOOGLE_CREDENTIALS_JSON", "")
        if saved == single_line:
            print("Verificação OK: o valor salvo confere com o arquivo local.")
        else:
            print("AVISO: o valor salvo parece diferente do esperado. Verifique manualmente.")
    else:
        print(f"ERRO na API Heroku (status {status}):")
        print(body)
        sys.exit(1)


if __name__ == "__main__":
    main()
