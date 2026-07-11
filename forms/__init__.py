"""Formulários (WTForms) divididos por domínio.

forms.py virou este pacote na modularização (2026-07-10); todos os nomes
continuam importáveis como `from forms import X`. Novos formulários devem ir
no módulo do seu domínio.
"""
from .auth import *  # noqa: F401,F403
from .pacientes import *  # noqa: F401,F403
from .clinica import *  # noqa: F401,F403
from .veterinario import *  # noqa: F401,F403
from .loja import *  # noqa: F401,F403
from .financeiro import *  # noqa: F401,F403
from .parceiro import *  # noqa: F401,F403
from .planos import *  # noqa: F401,F403
from .agendamento import *  # noqa: F401,F403

# Nomes internos usados fora do pacote:
from .loja import _ProductCategoryChoicesMixin  # noqa: F401
from .veterinario import _UF_CHOICES  # noqa: F401
from .clinica import _strip_filter  # noqa: F401
