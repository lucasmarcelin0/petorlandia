"""Guarda a foto no S3 e traduz a falha para quem esta em campo.

Existe porque a rota de foto do Vacina PMO devolvia `str(exc)` da excecao do
boto3 quando o envio quebrava. Na tela isso virava algo como "An error
occurred (InvalidAccessKeyId) when calling the PutObject operation" -- exato
para quem le log, inutil para o vacinador no meio da rua, e igual para
problemas com causas completamente diferentes (bucket errado, credencial
vencida, internet do dyno).

Aqui cada falha vira tres coisas: um `code` curto e estavel (bom para
telemetria e para pedir ajuda), uma frase em portugues que diz o que fazer, e
a informacao de se vale a pena tentar de novo.
"""

from __future__ import annotations

MENSAGEM_GENERICA = (
    'Não foi possível guardar a foto agora. Ela continua salva no seu aparelho '
    'e você pode tentar de novo.'
)

# Codigos do S3 que significam "a credencial ou a permissao esta errada".
# Tentar de novo com a mesma chave da sempre no mesmo lugar: quem resolve e o
# administrador, entao a tela para de insistir e mostra o motivo.
_CREDENCIAL_RECUSADA = {
    'AccessDenied',
    'AllAccessDisabled',
    'ExpiredToken',
    'InvalidAccessKeyId',
    'InvalidToken',
    'SignatureDoesNotMatch',
    'TokenRefreshRequired',
    'UnrecognizedClientException',
}

_BUCKET_AUSENTE = {'NoSuchBucket', 'PermanentRedirect'}


class PhotoStorageError(RuntimeError):
    """Falha ao guardar a foto, ja traduzida."""

    def __init__(self, code: str, user_message: str, retryable: bool = True, detail: str = ''):
        super().__init__(f'{code}: {detail or user_message}')
        self.code = code
        self.user_message = user_message
        self.retryable = retryable
        self.detail = detail


def _codigo_do_client_error(exc) -> str:
    resposta = getattr(exc, 'response', None) or {}
    erro = resposta.get('Error') or {}
    return str(erro.get('Code') or '').strip()


def _traduzir(exc) -> PhotoStorageError:
    """Converte a excecao do boto3 no erro que a tela sabe mostrar."""
    nome = type(exc).__name__

    if nome in {'NoCredentialsError', 'PartialCredentialsError'}:
        return PhotoStorageError(
            code='sem-credencial',
            user_message=(
                'O servidor está sem a credencial do armazenamento de fotos. '
                'Avise um administrador: a foto está guardada no seu aparelho e '
                'não se perdeu.'
            ),
            retryable=False,
            detail=str(exc),
        )

    if nome in {'EndpointConnectionError', 'ConnectTimeoutError', 'ReadTimeoutError', 'ConnectionError'}:
        return PhotoStorageError(
            code='rede',
            user_message=(
                'O servidor não conseguiu falar com o armazenamento de fotos. '
                'Tente de novo em instantes.'
            ),
            retryable=True,
            detail=str(exc),
        )

    codigo = _codigo_do_client_error(exc)
    if codigo in _CREDENCIAL_RECUSADA:
        return PhotoStorageError(
            code='credencial-recusada',
            user_message=(
                f'O armazenamento de fotos recusou o envio ({codigo}). '
                'Isso é configuração do servidor, não da sua foto — avise um '
                'administrador. A foto continua guardada no seu aparelho.'
            ),
            retryable=False,
            detail=str(exc),
        )
    if codigo in _BUCKET_AUSENTE:
        return PhotoStorageError(
            code='bucket-inexistente',
            user_message=(
                f'O local onde as fotos são guardadas não respondeu ({codigo}). '
                'Avise um administrador.'
            ),
            retryable=False,
            detail=str(exc),
        )
    if codigo:
        return PhotoStorageError(
            code='s3-erro',
            user_message=f'O armazenamento de fotos respondeu com erro ({codigo}). {MENSAGEM_GENERICA}',
            retryable=True,
            detail=str(exc),
        )

    return PhotoStorageError(
        code='desconhecido',
        user_message=MENSAGEM_GENERICA,
        retryable=True,
        detail=f'{nome}: {exc}',
    )


def store_photo(stream, filename: str, folder: str = 'animals', uploader=None) -> str:
    """Envia a foto e devolve a URL publica.

    Levanta `PhotoStorageError` -- nunca a excecao crua do boto3 -- para que a
    rota nao precise saber nada sobre S3 para responder direito.

    `uploader` existe para a rota poder passar o seu proprio atalho de envio
    (o do blueprint resolve `app.upload_to_s3` na hora da chamada, que e o que
    os testes trocam). Sem isso, importar `s3_utils` aqui furaria esse ponto
    de troca e a suite passaria a falar com a AWS de verdade.
    """
    if uploader is None:
        from s3_utils import upload_to_s3 as uploader

    try:
        try:
            url = uploader(stream, filename, folder=folder, reraise=True)
        except TypeError:
            url = uploader(stream, filename, folder=folder)
    except Exception as exc:  # noqa: BLE001 - a traducao decide o que fazer
        raise _traduzir(exc) from exc

    if not url:
        raise PhotoStorageError(
            code='sem-bucket',
            user_message=(
                'O armazenamento de fotos não está configurado no servidor. '
                'Avise um administrador: a foto está guardada no seu aparelho.'
            ),
            retryable=False,
            detail='upload_to_s3 devolveu None (S3_BUCKET_NAME ausente).',
        )

    # Fallback local e efemero no Heroku: o proximo restart apagaria a foto.
    # Melhor recusar do que fingir que guardou.
    if not str(url).startswith('http'):
        raise PhotoStorageError(
            code='sem-durabilidade',
            user_message=(
                'A foto não pôde ser guardada em local permanente. '
                'Avise um administrador antes de tentar de novo.'
            ),
            retryable=False,
            detail=f'URL sem esquema http: {url!r}',
        )

    return url


def diagnose_photo_storage() -> dict:
    """Checa a configuracao do armazenamento sem enviar foto de verdade.

    Serve para responder em segundos a pergunta que antes exigia abrir o log do
    Heroku: "o problema e a foto ou e o servidor?". Nao expoe segredo nenhum --
    so diz se cada peca esta presente e o que o S3 respondeu.
    """
    import os

    relatorio = {
        'bucket_configurado': bool(os.getenv('S3_BUCKET_NAME')),
        'chave_configurada': bool(os.getenv('AWS_ACCESS_KEY_ID')),
        'segredo_configurado': bool(os.getenv('AWS_SECRET_ACCESS_KEY')),
        'escrita_ok': False,
        'code': '',
        'detalhe': '',
    }
    if not relatorio['bucket_configurado']:
        relatorio['code'] = 'sem-bucket'
        relatorio['detalhe'] = 'S3_BUCKET_NAME não está definido no servidor.'
        return relatorio

    from io import BytesIO

    from s3_utils import BUCKET_NAME, s3

    # Um objeto minusculo e descartavel: confirma credencial, permissao de
    # escrita e nome do bucket de uma vez so, sem custo relevante.
    chave = 'diagnostico/escrita-teste.txt'
    try:
        s3.upload_fileobj(BytesIO(b'ok'), BUCKET_NAME, chave, ExtraArgs={'ContentType': 'text/plain'})
        relatorio['escrita_ok'] = True
    except Exception as exc:  # noqa: BLE001
        traduzido = _traduzir(exc)
        relatorio['code'] = traduzido.code
        relatorio['detalhe'] = traduzido.detail or traduzido.user_message
    return relatorio
