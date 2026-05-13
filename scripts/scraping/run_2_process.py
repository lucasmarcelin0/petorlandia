"""
run_2_process.py — Fase 2: Parsear HTMLs e importar ao banco
=============================================================
Lê HTMLs baixados por run_1_harvest.py, extrai dados estruturados e importa
ao PostgreSQL.  Não precisa de browser/Playwright.

Opcionalmente usa Claude Haiku para extração de doses quando o parser regex
produz zero resultados (--usar-llm flag).

USO:
    # Processar todos os HTMLs disponíveis:
    python scripts/scraping/run_2_process.py

    # Dry-run (não grava no banco):
    python scripts/scraping/run_2_process.py --dry-run

    # Com extração LLM para doses difíceis:
    python scripts/scraping/run_2_process.py --usar-llm

    # Só produto específico (debug):
    python scripts/scraping/run_2_process.py --pid 12345

    # Limitar quantidade processada:
    python scripts/scraping/run_2_process.py --limite 100
"""

import os
import sys
import json
import re
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# UTF-8 no console Windows
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Adiciona raiz do projeto ao path para importar o parser existente
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

try:
    from importar_medicamentos_vetsmart import (
        extrair_produto_do_html,
        conectar_banco,
        _encontrar_ou_criar_medicamento_por_pa,
        _inserir_apresentacoes_consolidado,
        _inserir_doses_consolidado,
        _norm,
        CREATED_BY_USER_ID,
    )
except ImportError as e:
    print(f"Erro ao importar parser: {e}")
    print("Execute a partir da raiz do projeto ou verifique o PYTHONPATH.")
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ImportError:
    print("Instale: pip install psycopg2-binary")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
BASE_DIR  = _ROOT
HTML_DIR  = BASE_DIR / "data" / "vetsmart_html"
LOG_FILE  = BASE_DIR / "data" / "process.log"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validação de doses antes da inserção
# ---------------------------------------------------------------------------
_UNIDADES_VALIDAS = {
    "MG_KG", "MCG_KG", "ML_KG", "UI_KG",
    "MG_ANIMAL", "MCG_ANIMAL", "ML_ANIMAL",
    "COMPRIMIDOS_ANIMAL", "COMPRIMIDOS_KG",
    "PIPETA_KG", "PIPETA_ANIMAL",
    "GOTAS_ANIMAL",
}

_ESPECIES_VALIDAS = {"CAES", "GATOS", "AMBOS", "OUTRO"}


def validar_dose(d: Dict[str, Any]) -> Optional[str]:
    """Retorna mensagem de erro ou None se a dose é válida."""
    dose_min = d.get("dose_min")
    dose_max = d.get("dose_max")
    unidade  = (d.get("dose_unidade") or "").upper()
    especie  = (d.get("especie_code") or "").upper()

    if dose_min is None:
        return "dose_min ausente"
    try:
        dose_min = float(dose_min)
    except (TypeError, ValueError):
        return f"dose_min inválido: {dose_min!r}"
    if dose_min < 0:
        return f"dose_min negativo: {dose_min}"
    if dose_min == 0 and unidade not in ("COMPRIMIDOS_ANIMAL", "COMPRIMIDOS_KG"):
        return f"dose_min = 0 (unidade={unidade})"

    if dose_max is not None:
        try:
            dose_max = float(dose_max)
        except (TypeError, ValueError):
            return f"dose_max inválido: {dose_max!r}"
        if dose_max < dose_min:
            return f"dose_max ({dose_max}) < dose_min ({dose_min})"

    if unidade and unidade not in _UNIDADES_VALIDAS:
        return f"unidade desconhecida: {unidade!r}"

    if especie and especie not in _ESPECIES_VALIDAS:
        return f"especie_code desconhecido: {especie!r}"

    intervalo = d.get("intervalo_horas")
    if intervalo is not None:
        try:
            h = int(intervalo)
        except (TypeError, ValueError):
            return f"intervalo_horas inválido: {intervalo!r}"
        if h <= 0 or h > 720:
            return f"intervalo_horas fora do range: {h}"

    return None


def filtrar_doses_validas(doses: List[Dict], nome_prod: str) -> List[Dict]:
    validas = []
    for d in doses:
        erro = validar_dose(d)
        if erro:
            log.debug(f"  Dose descartada ({nome_prod}): {erro} | raw={d.get('dose_raw_text','')!r}")
        else:
            validas.append(d)
    return validas


# ---------------------------------------------------------------------------
# Extração LLM (Claude Haiku) — opcional
# ---------------------------------------------------------------------------
_LLM_PROMPT_DOSES = """\
Você é um farmacologista veterinário especialista.
Analise o texto abaixo retirado da seção "Administração e doses" de um medicamento veterinário.
Extraia TODAS as doses mencionadas em formato JSON.

Texto:
{texto}

Retorne APENAS um array JSON válido. Cada objeto deve ter exatamente estas chaves (todas opcionais exceto dose_min):
- especie_code: "CAES", "GATOS" ou "AMBOS"
- dose_min: número (obrigatório)
- dose_max: número (igual a dose_min se dose única)
- dose_unidade: "MG_KG", "MCG_KG", "ML_KG", "MG_ANIMAL", "ML_ANIMAL", "COMPRIMIDOS_ANIMAL", "COMPRIMIDOS_KG", "PIPETA_KG", "GOTAS_ANIMAL"
- via: texto (ex: "Oral", "IM", "SC", "IV", "Tópica")
- intervalo_horas: número inteiro (ex: 24 para SID, 12 para BID, 8 para TID)
- duracao_min_dias: número inteiro
- duracao_max_dias: número inteiro
- indicacao: texto curto (ex: "Anti-inflamatório", "Alergia", "Imunossupressão")
- dose_raw_text: linha original do texto que gerou este registro

Não invente dados. Se um campo não está no texto, omita-o.
Retorne [] se não encontrar nenhuma dose.
"""


def extrair_doses_com_llm(texto_admin: str, nome_produto: str) -> List[Dict]:
    """Chama Claude Haiku para extrair doses estruturadas do texto."""
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic não instalado. Instale com: pip install anthropic")
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY não definida — LLM desabilitado.")
        return []

    cliente = anthropic.Anthropic(api_key=api_key)
    prompt = _LLM_PROMPT_DOSES.format(texto=texto_admin[:3000])

    try:
        msg = cliente.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        resposta = msg.content[0].text.strip()
        # Extrai bloco JSON da resposta
        m = re.search(r"\[.*\]", resposta, re.DOTALL)
        if not m:
            return []
        doses_raw = json.loads(m.group(0))
        if not isinstance(doses_raw, list):
            return []

        # Normaliza e adiciona campos obrigatórios para a DB
        doses = []
        for d in doses_raw:
            if not isinstance(d, dict) or d.get("dose_min") is None:
                continue
            d.setdefault("especie_code", "AMBOS")
            d.setdefault("especie", {"CAES": "Cães", "GATOS": "Gatos"}.get(
                d["especie_code"], "Cães e Gatos"
            ))
            d.setdefault("fonte", "LLM_HAIKU")
            d.setdefault("confianca", "MEDIA")
            doses.append(d)

        log.info(f"  LLM extraiu {len(doses)} doses para {nome_produto!r}")
        return doses

    except json.JSONDecodeError as e:
        log.warning(f"  LLM retornou JSON inválido para {nome_produto!r}: {e}")
        return []
    except Exception as e:
        log.warning(f"  Erro LLM para {nome_produto!r}: {e}")
        return []


# ---------------------------------------------------------------------------
# Processamento de um produto
# ---------------------------------------------------------------------------
def processar_html(pid: int, html: str, usar_llm: bool) -> Optional[Any]:
    """Parseia o HTML e retorna ProdutoVetsmart ou None se não extraiu dados."""
    try:
        prod = extrair_produto_do_html(html, pid, f"Produto #{pid}")
    except Exception as e:
        log.warning(f"  Erro ao parsear pid={pid}: {e}")
        return None

    if not prod.nome or prod.nome.startswith("Produto #"):
        log.warning(f"  pid={pid}: nome não extraído, produto ignorado.")
        return None

    # Validação e filtragem de doses
    prod.doses = filtrar_doses_validas(prod.doses or [], prod.nome)

    # Se o parser regex não encontrou nenhuma dose E temos texto de doses,
    # tenta LLM como fallback
    if usar_llm and not prod.doses:
        texto_admin = ""
        ce = prod.conteudo_estruturado or {}
        raw_secs = ce.get("raw_sections") or {}
        texto_admin = raw_secs.get("Administração e doses") or prod.dosagem_recomendada or ""
        if texto_admin:
            doses_llm = extrair_doses_com_llm(texto_admin, prod.nome)
            prod.doses = filtrar_doses_validas(doses_llm, prod.nome)

    return prod


# ---------------------------------------------------------------------------
# Importação para o banco
# ---------------------------------------------------------------------------
def importar_produto(conn, prod, dry_run: bool) -> Dict[str, int]:
    stats = {"apres": 0, "doses": 0, "med_novo": 0, "med_atualizado": 0}

    if dry_run:
        log.info(
            f"  [dry-run] {prod.nome!r} PA={prod.principio_ativo!r} "
            f"apres={len(prod.apresentacoes)} doses={len(prod.doses)}"
        )
        return stats

    try:
        with conn.cursor() as cur:
            pa_norm = _norm(prod.principio_ativo or "")
            existia = False
            if pa_norm:
                cur.execute("""
                    SELECT 1 FROM medicamento
                    WHERE LOWER(REGEXP_REPLACE(
                            TRANSLATE(principio_ativo,
                                      'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                                      'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'),
                            '\\s+', ' ', 'g')) = %s
                    LIMIT 1
                """, (pa_norm,))
                existia = cur.fetchone() is not None

            med_id = _encontrar_ou_criar_medicamento_por_pa(cur, prod)
            n_apres = _inserir_apresentacoes_consolidado(cur, med_id, prod)
            n_doses = _inserir_doses_consolidado(cur, med_id, prod.doses or [])

            stats["apres"]  = n_apres
            stats["doses"]  = n_doses
            stats["med_novo"]        = 0 if existia else 1
            stats["med_atualizado"]  = 1 if existia else 0

        conn.commit()

    except Exception as e:
        log.error(f"  ✗ ERRO DB para {prod.nome!r}: {e}")
        conn.rollback()

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Fase 2 — Parsear HTMLs salvos e importar ao banco."
    )
    parser.add_argument("--dry-run",   action="store_true",
                        help="Simula sem gravar no banco.")
    parser.add_argument("--usar-llm",  action="store_true",
                        help="Usa Claude Haiku para extrair doses quando regex falha.")
    parser.add_argument("--pid",       type=int, default=None,
                        help="Processa apenas o produto com este vetsmart_id.")
    parser.add_argument("--limite",    type=int, default=0,
                        help="Processa no máximo N produtos (0 = todos).")
    parser.add_argument("--html-dir",  type=str, default=str(HTML_DIR),
                        help="Diretório com os HTMLs (padrão: data/vetsmart_html/).")
    args = parser.parse_args()

    html_dir = Path(args.html_dir)
    if not html_dir.exists():
        log.error(f"Diretório {html_dir} não existe. Execute run_1_harvest.py primeiro.")
        sys.exit(1)

    # Lista de PIDs a processar
    if args.pid:
        html_files = [html_dir / f"{args.pid}.html"]
    else:
        html_files = sorted(html_dir.glob("*.html"), key=lambda p: int(p.stem))

    if args.limite > 0:
        html_files = html_files[:args.limite]

    total = len(html_files)
    log.info(f"Produtos a processar: {total} | dry_run={args.dry_run} | usar_llm={args.usar_llm}")

    conn = conectar_banco()

    acum = {
        "processados": 0, "ignorados": 0, "erros": 0,
        "apres": 0, "doses": 0, "med_novos": 0, "med_atualizados": 0,
    }

    for i, html_path in enumerate(html_files, 1):
        pid = int(html_path.stem)
        log.info(f"[{i}/{total}] pid={pid}")

        try:
            html = html_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning(f"  Erro ao ler {html_path}: {e}")
            acum["erros"] += 1
            continue

        prod = processar_html(pid, html, usar_llm=args.usar_llm)
        if prod is None:
            acum["ignorados"] += 1
            continue

        log.info(
            f"  ✓ {prod.nome!r} PA={prod.principio_ativo!r} "
            f"apres={len(prod.apresentacoes)} doses={len(prod.doses)}"
        )

        stats = importar_produto(conn, prod, dry_run=args.dry_run)
        acum["processados"] += 1
        acum["apres"]           += stats["apres"]
        acum["doses"]           += stats["doses"]
        acum["med_novos"]       += stats["med_novo"]
        acum["med_atualizados"] += stats["med_atualizado"]

    conn.close()

    print(f"""
{'='*65}
  RESULTADO — Fase 2 (process)
{'='*65}
  HTMLs lidos:           {total}
  Processados:           {acum['processados']}
  Ignorados:             {acum['ignorados']}
  Erros leitura:         {acum['erros']}
  Medicamentos novos:    {acum['med_novos']}
  Medicamentos updtd:    {acum['med_atualizados']}
  Apresentações inser.:  {acum['apres']}
  Doses inseridas:       {acum['doses']}
  Dry-run:               {'SIM' if args.dry_run else 'NÃO'}
  LLM:                   {'SIM' if args.usar_llm else 'NÃO'}
{'='*65}
""")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido.")
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
