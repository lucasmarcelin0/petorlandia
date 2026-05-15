"""
Reprocessador de conteudo_estruturado (sem re-scraping)
========================================================
Re-aplica o parser v3 ao raw_sections e observacoes já armazenados no banco,
atualizando conteudo_estruturado para todos os medicamentos sem precisar de
Playwright / Chromium.

Estratégia por medicamento:
  1. Tem raw_sections em conteudo_estruturado → re-parseia com BS4 + v3
  2. Tem só observacoes → parseia o texto estruturado de observacoes → v3
  3. Não tem nada útil → pula (não degrada dados existentes)

Uso:
  cd petorlandia/
  python scripts/reprocessar_conteudo_estruturado.py
  python scripts/reprocessar_conteudo_estruturado.py --dry-run
  python scripts/reprocessar_conteudo_estruturado.py --limite 100
"""

import os, sys, json, argparse, logging, importlib.util
from typing import Dict, Any, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Instale: pip install beautifulsoup4")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Importar funções do scraper principal
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def _importar_scraper():
    path = os.path.join(_SCRIPT_DIR, "importar_medicamentos_vetsmart.py")
    spec = importlib.util.spec_from_file_location("scraper", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

log.info("Carregando funções do scraper...")
scraper = _importar_scraper()

_extrair_secao_indicacoes_contraindicacoes = scraper._extrair_secao_indicacoes_contraindicacoes
_extrair_secao_interacoes                 = scraper._extrair_secao_interacoes
_montar_conteudo_estruturado_v2           = scraper._montar_conteudo_estruturado_v2
_texto_multilinha_limpo                   = scraper._texto_multilinha_limpo
_montar_secao_padrao                      = scraper._montar_secao_padrao
_split_lista_textual                      = scraper._split_lista_textual
_parsear_linhas_com_rotulo                = scraper._parsear_linhas_com_rotulo
_redistribuir_itens_clinicos              = scraper._redistribuir_itens_clinicos

log.info("Funções carregadas.")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    os.environ.get(
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://u82pgjdcmkbq7v:p0204cb9289674b66bfcbb9248eaf9d6a71e2dece2722fe22d6bd976c77b411e6"
        "@c2hbg00ac72j9d.cluster-czrs8kj4isg7.us-east-1.rds.amazonaws.com:5432/d2nnmcuqa8ljli",
    ),
)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bs4_de_texto(texto: Optional[str]) -> Optional[object]:
    """Cria elemento BS4 a partir de texto puro, para uso nos parsers do scraper."""
    if not texto:
        return None
    # Preserva quebras de linha como <br> para ajudar _coletar_blocos_por_subtitulo
    html = texto.replace('\n\n', '</p><p>').replace('\n', '<br/>')
    return BeautifulSoup(f"<div>{html}</div>", "html.parser").find("div")


def _reprocessar_de_raw_sections(raw_sections: Dict[str, str]) -> Dict[str, Any]:
    """Gera conteudo_estruturado v3 a partir de raw_sections (texto por seção)."""
    indic_texto = raw_sections.get("Indicações e contraindicações") or ""
    inter_texto  = raw_sections.get("Interações medicamentosas") or ""
    advert_texto = raw_sections.get("Sobre") or ""  # advertências gerais ficam aqui às vezes

    indic_div  = _bs4_de_texto(indic_texto)
    inter_div  = _bs4_de_texto(inter_texto)

    indicacoes_struct  = _extrair_secao_indicacoes_contraindicacoes(indic_div)
    interacoes_struct  = _extrair_secao_interacoes(inter_div)

    # Advertências extras: texto "Sobre" (breve resumo, warnings gerais)
    advertencias_extras = _texto_multilinha_limpo(advert_texto) if advert_texto else None

    return _montar_conteudo_estruturado_v2(
        indicacoes_struct,
        interacoes_struct,
        advertencias_extras=advertencias_extras,
        raw_sections=raw_sections,
    )


def _reprocessar_de_observacoes(observacoes: str) -> Optional[Dict[str, Any]]:
    """Gera conteudo_estruturado v3 a partir de observacoes (texto rotulado)."""
    obs = _texto_multilinha_limpo(observacoes)
    if not obs:
        return None

    # Parsear linhas rotuladas direto do texto de observacoes
    partes = _parsear_linhas_com_rotulo(obs)
    secoes: Dict[str, list] = {
        'indicacoes': [],
        'contraindicacoes': [],
        'advertencias': [],
        'efeitos_adversos': [],
    }
    for chave, textos in partes.items():
        if chave not in secoes:
            continue
        for t in textos:
            secoes[chave].extend(_split_lista_textual(t))
    secoes = _redistribuir_itens_clinicos(secoes)

    # Só vale continuar se tivermos algo útil
    if not any(secoes.values()):
        return None

    indicacoes_struct = {
        'indicacoes':        _montar_secao_padrao(secoes['indicacoes']),
        'contraindicacoes':  _montar_secao_padrao(
            secoes['contraindicacoes'],
            resumo=secoes['contraindicacoes'][:3],
        ),
        'advertencias':      _montar_secao_padrao(secoes['advertencias']),
        'efeitos_adversos':  _montar_secao_padrao(secoes['efeitos_adversos']),
        'texto_bruto':       obs,
    }
    interacoes_struct = {'itens': [], 'texto': None, 'texto_bruto': None}

    # Verificar se há bloco de interações em observacoes
    for marcador in ["Interações medicamentosas:", "Interacoes medicamentosas:"]:
        idx = obs.find(marcador)
        if idx != -1:
            inter_txt = obs[idx + len(marcador):].strip()
            inter_div = _bs4_de_texto(inter_txt)
            interacoes_struct = _extrair_secao_interacoes(inter_div)
            break

    return _montar_conteudo_estruturado_v2(
        indicacoes_struct,
        interacoes_struct,
        raw_sections={},
    )


def _tem_conteudo_util(conteudo: Dict[str, Any]) -> bool:
    """Retorna True se o conteudo tiver pelo menos alguns itens clínicos."""
    if not isinstance(conteudo, dict):
        return False
    for chave in ['indicacoes', 'contraindicacoes', 'advertencias', 'efeitos_adversos']:
        sec = conteudo.get(chave) or {}
        if sec.get('itens'):
            return True
    inter = conteudo.get('interacoes') or {}
    if inter.get('itens'):
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _norm_simples(texto: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", texto or "").encode("ASCII", "ignore").decode().lower()
    return s.strip()


def main():
    p = argparse.ArgumentParser(description="Reprocessa conteudo_estruturado v3 a partir de dados já no banco.")
    p.add_argument("--dry-run",      action="store_true", help="Não grava no banco.")
    p.add_argument("--limite",       type=int, default=0, help="Processa só N medicamentos (0 = todos).")
    p.add_argument("--forcar",       action="store_true", help="Reprocessa mesmo que já tenha parser_version='v3'.")
    p.add_argument("--filtro-nome",  type=str, default="", help="Processa só medicamentos cujo nome contenha este texto (ex: 'prednisolona').")
    args = p.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor(cursor_factory=RealDictCursor)

    # Seleciona medicamentos candidatos
    conditions = ["1=1"]
    params: list = []

    if not args.forcar:
        conditions.append("""(
            conteudo_estruturado IS NULL
            OR conteudo_estruturado::jsonb = '{}'::jsonb
            OR COALESCE(conteudo_estruturado->'metadata'->>'parser_version', '') != 'v3'
          )""")

    if args.filtro_nome:
        conditions.append("LOWER(nome) LIKE %s")
        params.append(f"%{_norm_simples(args.filtro_nome)}%")

    where = " AND ".join(conditions)
    limit_sql = f"LIMIT {args.limite}" if args.limite > 0 else ""

    cur.execute(f"""
        SELECT id, nome, observacoes, conteudo_estruturado
          FROM medicamento
         WHERE {where}
         ORDER BY id
         {limit_sql}
    """, params)
    rows = cur.fetchall()
    log.info(f"Medicamentos para reprocessar: {len(rows)}")

    stats = {
        'raw_sections_ok':  0,
        'observacoes_ok':   0,
        'sem_dados':        0,
        'atualizados':      0,
        'sem_melhoria':     0,
        'erros':            0,
    }

    for row in rows:
        med_id   = row['id']
        nome     = row['nome']
        obs      = row['observacoes']
        conteudo = row['conteudo_estruturado'] or {}

        try:
            novo_conteudo: Optional[Dict[str, Any]] = None

            # Estratégia 1: raw_sections no DB
            raw_sections = conteudo.get('raw_sections') if isinstance(conteudo, dict) else None
            if isinstance(raw_sections, dict) and raw_sections:
                novo_conteudo = _reprocessar_de_raw_sections(raw_sections)
                if _tem_conteudo_util(novo_conteudo):
                    stats['raw_sections_ok'] += 1
                else:
                    novo_conteudo = None

            # Estratégia 2: observacoes
            if novo_conteudo is None and obs:
                novo_conteudo = _reprocessar_de_observacoes(obs)
                if novo_conteudo and _tem_conteudo_util(novo_conteudo):
                    stats['observacoes_ok'] += 1
                else:
                    novo_conteudo = None

            if novo_conteudo is None:
                stats['sem_dados'] += 1
                log.debug(f"  [{med_id}] {nome}: sem dados úteis, pulando")
                continue

            if not args.dry_run:
                cur_upd = conn.cursor()
                cur_upd.execute(
                    "UPDATE medicamento SET conteudo_estruturado = %s WHERE id = %s",
                    (Json(novo_conteudo), med_id),
                )
                cur_upd.close()
                stats['atualizados'] += 1
            else:
                stats['atualizados'] += 1

            indic_count = len((novo_conteudo.get('indicacoes') or {}).get('itens') or [])
            contra_count = len((novo_conteudo.get('contraindicacoes') or {}).get('itens') or [])
            inter_count  = len((novo_conteudo.get('interacoes') or {}).get('itens') or [])
            log.info(
                f"  [{med_id}] {nome[:50]}: "
                f"indicações={indic_count}, contraindicações={contra_count}, interações={inter_count}"
                + (" [DRY-RUN]" if args.dry_run else "")
            )

        except Exception as e:
            stats['erros'] += 1
            log.warning(f"  [{med_id}] {nome}: ERRO — {e}")

    if not args.dry_run:
        conn.commit()
        log.info("Commit realizado.")
    else:
        log.info("[DRY-RUN] Nenhuma alteração gravada.")

    conn.close()

    log.info("\n=== RESUMO ===")
    log.info(f"  Via raw_sections:  {stats['raw_sections_ok']}")
    log.info(f"  Via observacoes:   {stats['observacoes_ok']}")
    log.info(f"  Sem dados úteis:   {stats['sem_dados']}")
    log.info(f"  Atualizados:       {stats['atualizados']}")
    log.info(f"  Erros:             {stats['erros']}")


if __name__ == "__main__":
    main()
