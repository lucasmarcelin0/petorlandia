"""Campos de formulário que entendem como o brasileiro digita número.

O ``DecimalField`` do WTForms só aceita ponto decimal. Quem preenche "28,00" —
o que o próprio navegador em pt-BR exibe dentro de um ``input type=number`` —
derruba a validação do formulário inteiro. Como a maior parte das telas de
cadastro não renderiza erro de campo, o efeito prático era um Salvar que não
salvava e não avisava.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from wtforms import DecimalField


class BRDecimalField(DecimalField):
    """Decimal tolerante ao separador decimal em vírgula.

    Aceita ``28,00``, ``28.00``, ``1.234,56`` e ``1234.56``. Continua
    recusando texto que não seja número — o objetivo é entender a digitação
    real, não adivinhar intenção.
    """

    def process_formdata(self, valuelist):
        if not valuelist:
            return super().process_formdata(valuelist)

        raw = valuelist[0]
        if isinstance(raw, str):
            normalized = _normalize_br_number(raw)
            if normalized is not None:
                valuelist = [normalized]

        return super().process_formdata(valuelist)


def _normalize_br_number(raw: str) -> str | None:
    """Devolve o texto com ponto decimal, ou ``None`` se não for numérico."""
    text = raw.strip().replace('R$', '').replace('%', '').replace(' ', '')
    if not text:
        return None

    if ',' in text:
        # Vírgula presente: ela é o separador decimal e o ponto, se houver,
        # é separador de milhar ("1.234,56").
        text = text.replace('.', '').replace(',', '.')
    elif text.count('.') > 1:
        # Só pontos e mais de um: todos são separador de milhar ("1.234.567").
        text = text.replace('.', '')

    try:
        Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return text
