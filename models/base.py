"""Fachada de compatibilidade: os modelos vivem em módulos por domínio.

Dividido na modularização (2026-07-10). Novos modelos devem ser criados no
módulo do seu domínio (models/usuarios.py, models/clinica.py, ...). Este
arquivo apenas reexporta tudo para manter `from models.base import X`
funcionando.
"""
from .usuarios import *  # noqa: F401,F403
from .clinica import *  # noqa: F401,F403
from .pacientes import *  # noqa: F401,F403
from .comunicacao import *  # noqa: F401,F403
from .consulta import *  # noqa: F401,F403
from .bulario import *  # noqa: F401,F403
from .agenda import *  # noqa: F401,F403
from .financeiro import *  # noqa: F401,F403
from .loja import *  # noqa: F401,F403
from .racao import *  # noqa: F401,F403
from .saude import *  # noqa: F401,F403
from .pmo import *  # noqa: F401,F403
from .site import *  # noqa: F401,F403

# Nomes internos ainda importados por app/testes:
from .usuarios import _NAME_PARTICLES  # noqa: F401
from .clinica import _clinica_columns  # noqa: F401
from .usuarios import _create_veterinarian_membership  # noqa: F401
from .clinica import _decrypt_nfse_value  # noqa: F401
from .clinica import _encrypt_nfse_value  # noqa: F401
from .pacientes import _format_age_label  # noqa: F401
from .pacientes import _normalize_age_unit  # noqa: F401
from .pacientes import _normalize_animal_name_before_insert  # noqa: F401
from .pacientes import _normalize_animal_name_before_update  # noqa: F401
from .usuarios import _normalize_model_name  # noqa: F401
from .usuarios import _normalize_person_name  # noqa: F401
from .usuarios import _normalize_user_name_before_insert  # noqa: F401
from .usuarios import _normalize_user_name_before_update  # noqa: F401
from .pacientes import _parse_age_value  # noqa: F401
from .loja import _seed_product_categories  # noqa: F401
from .financeiro import _sync_snapshot_totals  # noqa: F401
