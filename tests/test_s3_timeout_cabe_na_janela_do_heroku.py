"""O envio ao S3 tem que falhar antes do roteador do Heroku desistir.

Existe por causa de um erro em producao: o vacinador preenchia a pagina de
vacinacao, anexava a foto e recebia a pagina "Application error" do Heroku --
que nao diz nada e nao deixa tentar de novo.

O motivo nao era a foto. O cliente do boto3 era criado sem limite de tempo, e
o padrao dele (60s para conectar, 60s para ler, ate 5 tentativas) passa dos
30s em que o roteador do Heroku corta a requisicao. A traducao amigavel que ja
existe em `services/photo_storage.py` ("Tente de novo em instantes.") nunca
chegava a rodar: o roteador derrubava a resposta antes.

Estes testes fixam o contrato: qualquer que seja o ajuste futuro dos limites,
o pior caso tem que caber na janela do roteador.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import s3_utils  # noqa: E402

# Quanto o roteador do Heroku espera antes de devolver "Application error".
JANELA_DO_ROTEADOR_S = 30

# O S3 nao e a requisicao inteira: antes dele ainda entram o recebimento do
# corpo da foto e a conversao HEIC->JPEG. Esta folga existe para o pior caso
# do S3 nao consumir sozinho a janela toda.
FOLGA_PARA_O_RESTO_DA_REQUISICAO_S = 5


def test_cliente_s3_tem_limite_de_tempo_definido():
    config = s3_utils.s3_client_config()

    assert config.connect_timeout is not None, "sem connect_timeout o boto3 usa 60s"
    assert config.read_timeout is not None, "sem read_timeout o boto3 usa 60s"
    assert config.retries and config.retries.get("total_max_attempts"), (
        "sem limite de tentativas o boto3 repete a chamada ate 5 vezes"
    )


def test_pior_caso_cabe_antes_do_roteador_do_heroku_desistir():
    config = s3_utils.s3_client_config()
    # `total_max_attempts` ja conta a primeira chamada. Se alguem trocar por
    # `max_attempts`, o numero passa a ser de retentativas e o pior caso
    # cresce silenciosamente -- por isso o teste le a chave explicita.
    tentativas = config.retries["total_max_attempts"]

    pior_caso = tentativas * (config.connect_timeout + config.read_timeout)
    orcamento = JANELA_DO_ROTEADOR_S - FOLGA_PARA_O_RESTO_DA_REQUISICAO_S

    assert pior_caso <= orcamento, (
        f"pior caso de {pior_caso}s passa do orcamento de {orcamento}s "
        f"({JANELA_DO_ROTEADOR_S}s do roteador menos a folga para receber a foto "
        "e converter HEIC): o usuario voltaria a ver 'Application error' em vez "
        "da mensagem da tela"
    )


def test_cliente_do_modulo_usa_esses_limites():
    # O cliente pronto (usado por upload_to_s3) precisa nascer com a config --
    # nao adianta a funcao existir e ninguem aplicar.
    config = s3_utils.s3.meta.config

    assert config.connect_timeout == s3_utils.S3_CONNECT_TIMEOUT
    assert config.read_timeout == s3_utils.S3_READ_TIMEOUT
    assert config.retries["total_max_attempts"] == s3_utils.S3_MAX_ATTEMPTS


def test_falha_de_rede_vira_mensagem_em_portugues_e_nao_excecao_crua():
    # Com o limite de tempo valendo, a falha chega como ReadTimeoutError --
    # e a tela tem que saber traduzir isso, senao a correcao so troca um erro
    # feio por outro.
    from services.photo_storage import _traduzir

    class ReadTimeoutError(Exception):
        pass

    erro = _traduzir(ReadTimeoutError("read timeout"))

    assert erro.code == "rede"
    assert erro.retryable is True
    assert "tente de novo" in erro.user_message.lower()
