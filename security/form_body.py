"""Corpo de formulário ilegível vira erro 400, nunca formulário vazio.

Quando o celular desiste de um envio no meio (tempo esgotado, sinal que cai
durante o upload da foto), o servidor recebe só um pedaço do corpo
``multipart``. O Werkzeug descarta esse corpo **em silêncio**: com o gunicorn
(``wsgi.input_terminated``) o stream não é limitado pelo ``Content-Length`` e a
leitura apenas termina antes da hora; o parser levanta ``ValueError`` e o
``FormDataParser`` padrão (``silent=True``) devolve ``request.form`` e
``request.files`` vazios. Como o token CSRF chega pelo cabeçalho
(``csrf_fetch.js``), a rota rodava com o formulário vazio e gravava os campos
em branco: foi assim que animais passaram a aparecer com o nome "None".

Aqui o parser deixa de ser silencioso. A primeira leitura de ``request.form``
(normalmente a do CSRF, antes da rota) levanta :class:`IncompleteFormBody`,
e o handler registrado em ``request_hooks`` responde 400 com uma mensagem
clara, sem executar a rota. Corpos válidos seguem exatamente como antes.
"""
from __future__ import annotations

from flask import Request
from werkzeug.exceptions import BadRequest

MENSAGEM_ENVIO_INCOMPLETO = (
    'O envio chegou incompleto (a conexão caiu no meio). Nada foi alterado. '
    'Confira a internet e tente de novo.'
)


class IncompleteFormBody(BadRequest):
    """O corpo do formulário chegou cortado ou ilegível."""

    description = MENSAGEM_ENVIO_INCOMPLETO


class FormBodyAwareRequest(Request):
    """``Request`` que não transforma corpo ilegível em formulário vazio."""

    def make_form_data_parser(self):
        parser = super().make_form_data_parser()
        # O padrão engole o ValueError do parser e devolve dicionários vazios.
        parser.silent = False
        return parser

    def _load_form_data(self) -> None:
        try:
            super()._load_form_data()
        except ValueError as exc:
            # Leituras seguintes (handlers de erro, logs) não devem tentar
            # analisar de novo um stream já consumido.
            storage = self.parameter_storage_class
            self.__dict__['form'] = storage()
            self.__dict__['files'] = storage()
            raise IncompleteFormBody() from exc
