"""Cliente da API do Google Sheets sem o texto de ajuda gerado a cada uso.

A biblioteca ``googleapiclient`` monta, a cada ``service.spreadsheets()``, o
``__doc__`` de todos os métodos do recurso imprimindo o esquema completo da
planilha (só o do ``batchUpdate`` passa de 4 MB de texto). Isso custava ~68 MB
por chamada e era o que levava o scheduler (sincronização do PMO, 59 abas a
cada 10 min) e o painel do PMO acima da cota de memória do dyno.

O texto só aparece em ``help()``: nenhuma requisição usa. Aqui ele vira uma
linha curta; URLs, parâmetros, validação e respostas continuam idênticos.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_ready = False


def _sem_texto_de_ajuda() -> None:
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        from googleapiclient import discovery, schema

        base = schema.Schemas

        class _SchemasSemAjuda(base):
            def prettyPrintByName(self, name):
                return "# Objeto do esquema %s" % name

            def prettyPrintSchema(self, schema):
                return "# Objeto"

        # ``build`` cria o ``Schemas`` pelo nome importado em ``discovery``; se uma
        # versão futura mudar isso, o cliente segue funcionando como antes.
        if getattr(discovery, "Schemas", None) is base:
            discovery.Schemas = _SchemasSemAjuda
        _ready = True


def build_sheets(credentials):
    from googleapiclient.discovery import build

    _sem_texto_de_ajuda()
    return build("sheets", "v4", credentials=credentials)
