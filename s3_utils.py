import logging
import os

import boto3
from botocore.config import Config
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# O roteador do Heroku corta a requisicao em 30s e devolve a pagina
# "Application error" -- que nao diz nada a quem esta em campo. O boto3, por
# padrao, espera 60s para conectar, 60s para ler e ainda repete a chamada ate
# 5 vezes: um S3 lento sozinho passa dos 30s e a tela que sabia explicar a
# falha ("Tente de novo em instantes.", em services/photo_storage.py) nunca
# chega a aparecer.
#
# O S3 nao pode gastar a janela inteira: antes dele a requisicao ainda recebe
# o corpo da foto e converte HEIC para JPEG. Por isso o pior caso aqui e
# 2 x (3s + 8s) = 22s (mais ~1s de espera entre as tentativas), deixando
# folga para o resto da requisicao caber nos 30s. Assim a falha vira mensagem
# em portugues dentro da propria pagina, em vez de erro do Heroku.
#
# 8s e folgado para o que sobe de verdade: a foto ja chega reduzida a 1600px
# de lado (services/photo_intake), tipicamente algumas centenas de KB.
#
# `read_timeout` conta cada leitura do socket, nao o upload inteiro: envio
# lento que continua progredindo (internet ruim no meio da rua) nao e cortado.
S3_CONNECT_TIMEOUT = int(os.getenv("S3_CONNECT_TIMEOUT", "3"))
S3_READ_TIMEOUT = int(os.getenv("S3_READ_TIMEOUT", "8"))
# Tentativas no total, ja contando a primeira. Usamos `total_max_attempts`
# porque `max_attempts` no boto3 quer dizer "retentativas": passar 2 ali
# viraria 3 chamadas e o pior caso estouraria os 30s do roteador.
S3_MAX_ATTEMPTS = int(os.getenv("S3_MAX_ATTEMPTS", "2"))


def s3_client_config() -> Config:
    """Limites de tempo do S3 que cabem na janela de 30s do Heroku."""
    return Config(
        connect_timeout=S3_CONNECT_TIMEOUT,
        read_timeout=S3_READ_TIMEOUT,
        retries={"total_max_attempts": S3_MAX_ATTEMPTS, "mode": "standard"},
        tcp_keepalive=True,
    )


s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    config=s3_client_config(),
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

def upload_to_s3(file, filename, folder="uploads", **kwargs):
    filepath = f"{folder}/{secure_filename(filename)}"
    if not BUCKET_NAME:
        logger.warning("S3 bucket is not configured; skipping upload for %s", filepath)
        return None

    stream = getattr(file, "stream", file)
    content_type = getattr(file, "content_type", None) or getattr(stream, "content_type", None) or "application/octet-stream"

    s3.upload_fileobj(
        stream,
        BUCKET_NAME,
        filepath,
        ExtraArgs={
            "ContentType": content_type
        }
    )
    return f"https://{BUCKET_NAME}.s3.amazonaws.com/{filepath}"
