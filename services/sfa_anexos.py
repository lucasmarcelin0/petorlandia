"""Anexos do protocolo SFA gerados a partir dos mesmos schemas que o site usa.

Os anexos T0, T7 e T30 reproduzem pergunta, opções, ajuda e ordem exatamente
como aparecem no formulário público; as regras de ``visible_if`` viram frases
que apontam para o número da pergunta. Antes deles vem a ficha SINAN de
dengue/chikungunya, com o uso de cada campo no estudo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

TIPOS_ENTRADA = {
    "text": "Resposta curta",
    "textarea": "Resposta longa",
    "number": "Numero",
    "date": "Data",
}

SINAN_FICHA_PATH = Path(__file__).resolve().parents[1] / "config" / "sfa_sinan_ficha_dengue.json"


def carregar_ficha_sinan_dengue() -> dict:
    """Ficha de Investigação Dengue e Febre de Chikungunya, campo a campo.

    Transcrita da ficha do Sinan Online (SVS 14/03/2016) com os códigos
    impressos. ``plataforma`` lista as chaves que a plataforma já transcreve da
    ficha desde a notificação; o restante vem da extração da base SINAN/GAL.
    """
    return json.loads(SINAN_FICHA_PATH.read_text(encoding="utf-8"))


def _estagios_anteriores(stage: str) -> tuple[str, ...]:
    return {"t7": ("t0",), "t30": ("t0", "t7")}.get(stage, ())


def _citar(valor: object) -> str:
    return f'"{valor}"'


def _lista_citada(valores: list[object], conector: str) -> str:
    citados = [_citar(valor) for valor in valores]
    if len(citados) <= 1:
        return "".join(citados)
    return ", ".join(citados[:-1]) + f" {conector} " + citados[-1]


class _Descritor:
    """Traduz o DSL de ``visible_if`` em regra de salto com número de pergunta.

    ``frase`` devolve o texto e, quando há muitas alternativas ou respostas de
    entrevistas anteriores, a lista de situações que abrem a pergunta.
    """

    MAX_ALTERNATIVAS_EM_LINHA = 2

    def __init__(self, numeros: dict[str, int], anteriores: dict[str, tuple[list[str], str]]):
        self.numeros = numeros
        self.anteriores = anteriores

    def frase(self, regra: dict) -> dict[str, object]:
        if isinstance(regra.get("not"), dict):
            # Pergunta principal que só some em um caso: não é aprofundamento.
            return {"texto": f"Não aparece se {self.clausula(regra['not'])}.", "itens": [], "aprofundamento": False}
        filhos = regra.get("all")
        if isinstance(filhos, list):
            negadas = [f["not"] for f in filhos if isinstance(f, dict) and isinstance(f.get("not"), dict)]
            positivas = [f for f in filhos if not (isinstance(f, dict) and isinstance(f.get("not"), dict))]
            if negadas and positivas:
                positivo = self.clausula({"all": positivas})
                negativo = " ou ".join(self.clausula(f, aninhada=True) for f in negadas)
                return {"texto": f"Aparece se {positivo}; não aparece se {negativo}.", "itens": [], "aprofundamento": True}
        alternativas = regra.get("any")
        if isinstance(alternativas, list) and (
            len(alternativas) > self.MAX_ALTERNATIVAS_EM_LINHA
            or any(self._so_anterior(f) for f in alternativas)
        ):
            itens = [self.clausula(f) for f in alternativas if not self._so_anterior(f)]
            itens += [self.clausula(f) for f in alternativas if self._so_anterior(f)]
            return {"texto": "Aparece se ocorrer pelo menos uma destas situações:", "itens": itens, "aprofundamento": True}
        return {"texto": f"Aparece se {self.clausula(regra)}.", "itens": [], "aprofundamento": True}

    def clausula(self, regra: dict, aninhada: bool = False) -> str:
        if isinstance(regra.get("all"), list):
            partes = [self.clausula(f, aninhada=True) for f in self._fundir_respondida(regra["all"])]
            texto = " e ".join(partes)
            return f"({texto})" if aninhada and len(partes) > 1 else texto
        if isinstance(regra.get("any"), list):
            partes = [self.clausula(f, aninhada=True) for f in regra["any"]]
            texto = " ou ".join(partes)
            return f"({texto})" if aninhada and len(partes) > 1 else texto
        if isinstance(regra.get("not"), dict):
            return f"não ({self.clausula(regra['not'])})"
        return self._atomo(regra)

    def _fundir_respondida(self, filhos: list) -> list:
        """``nonempty`` + ``not_equals`` na mesma pergunta viram uma condição só."""
        diferentes = {
            (self._fonte(f), self._chave(f))
            for f in filhos
            if self._atomica(f) and self._operador(f) in {"not_equals", "neq"}
        }
        return [
            f for f in filhos
            if not (
                self._atomica(f)
                and self._operador(f) in {"nonempty", "present"}
                and (self._fonte(f), self._chave(f)) in diferentes
            )
        ]

    def _so_anterior(self, regra: object) -> bool:
        if self._atomica(regra):
            return self._fonte(regra) != "current"
        if not isinstance(regra, dict):
            return False
        filhos = regra.get("all") or regra.get("any") or ([regra["not"]] if isinstance(regra.get("not"), dict) else [])
        return bool(filhos) and all(self._so_anterior(f) for f in filhos)

    @staticmethod
    def _atomica(regra: object) -> bool:
        return isinstance(regra, dict) and not any(k in regra for k in ("all", "any", "not"))

    @staticmethod
    def _fonte(regra: object) -> str:
        if not isinstance(regra, dict):
            return "current"
        return str(regra.get("source") or "current").strip().lower()

    @staticmethod
    def _chave(regra: dict) -> str:
        return str(regra.get("key") or regra.get("field") or "")

    @staticmethod
    def _operador(regra: dict) -> str:
        return str(regra.get("operator") or regra.get("op") or "equals").strip().lower()

    def _referencia(self, regra: dict) -> str:
        chave = self._chave(regra)
        if self._fonte(regra) == "current":
            return f"pergunta {self.numeros[chave]}" if chave in self.numeros else f'"{chave}"'
        etapas, rotulo = self.anteriores.get(chave, ([], chave))
        onde = " ou ".join(etapa.upper() for etapa in etapas) or "entrevista anterior"
        return f'no {onde}, "{rotulo}"'

    def _atomo(self, regra: dict) -> str:
        ref = self._referencia(regra)
        operador = self._operador(regra)
        valores = regra.get("values") or []
        if operador in {"equals", "eq"}:
            return f"{ref} = {_citar(regra.get('value'))}"
        if operador in {"not_equals", "neq"}:
            return f"{ref} respondida com opção diferente de {_citar(regra.get('value'))}"
        if operador in {"nonempty", "present"}:
            return f"{ref} respondida"
        if operador in {"selected_any", "contains_any", "in"}:
            return f"{ref} com {_lista_citada(valores, 'ou')} marcado"
        if operador == "selected_any_except":
            return f"{ref} com alguma opção além de {_lista_citada(valores, 'e')} marcada"
        return f"{ref} ({operador})"


def montar_formulario_anexo(stage: str, schema: dict, anteriores: Optional[dict[str, dict]] = None) -> dict:
    """Numera as perguntas e anexa a frase de condição de cada uma."""
    from services.sfa_service import iterar_campos_form

    numeros: dict[str, int] = {}
    for posicao, campo in enumerate(iterar_campos_form(schema), start=1):
        numeros[campo["key"]] = posicao

    rotulos_anteriores: dict[str, tuple[list[str], str]] = {}
    for etapa in _estagios_anteriores(stage):
        schema_anterior = (anteriores or {}).get(etapa)
        if not schema_anterior:
            continue
        for campo in iterar_campos_form(schema_anterior):
            etapas, _ = rotulos_anteriores.get(campo["key"], ([], ""))
            # O rótulo mais recente descreve melhor o que foi perguntado por último.
            rotulos_anteriores[campo["key"]] = (etapas + [etapa], campo.get("label") or campo["key"])

    descritor = _Descritor(numeros, rotulos_anteriores)
    secoes = []
    for secao in schema.get("sections", []):
        perguntas = []
        for campo in secao.get("fields", []):
            if not isinstance(campo, dict):
                continue
            regra = campo.get("visible_if")
            perguntas.append({
                **campo,
                "numero": numeros[campo["key"]],
                "condicao": descritor.frase(regra) if isinstance(regra, dict) else None,
                "entrada": TIPOS_ENTRADA.get(str(campo.get("type") or "text"), "Resposta curta"),
            })
        secoes.append({**secao, "perguntas": perguntas})
    return {
        "stage": stage,
        "etapa": stage.upper(),
        "schema": schema,
        "secoes": secoes,
        "total_perguntas": len(numeros),
        "total_condicionais": sum(1 for s in secoes for p in s["perguntas"] if p["condicao"]),
    }


def montar_anexos_protocolo() -> dict:
    from services.sfa_service import carregar_t0_form_schema, carregar_t7_form_schema, carregar_t30_form_schema

    schemas = {
        "t0": carregar_t0_form_schema(),
        "t7": carregar_t7_form_schema(),
        "t30": carregar_t30_form_schema(),
    }
    return {
        "sinan": carregar_ficha_sinan_dengue(),
        "formularios": [
            montar_formulario_anexo(stage, schemas[stage], anteriores=schemas)
            for stage in ("t0", "t7", "t30")
        ],
    }
