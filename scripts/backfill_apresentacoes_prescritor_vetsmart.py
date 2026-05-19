"""
Backfill de apresentacoes a partir do export bruto do Prontuario VetSmart.

O scraper de produtos captura o bulario/comercial. O prescritor do VetSmart,
por outro lado, expoe um catalogo de "Apresentacao e concentracao" mais limpo
para prescricao (ex.: "250 mg / 5mL, solucao", "100 mg/mL, gotas"). Esta
rotina usa esse export como fonte complementar para preencher o nosso bulario.

Uso:
  python scripts/backfill_apresentacoes_prescritor_vetsmart.py --dry-run --filtro cefalexina
  python scripts/backfill_apresentacoes_prescritor_vetsmart.py --filtro cefalexina
  python scripts/backfill_apresentacoes_prescritor_vetsmart.py
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from importar_medicamentos_vetsmart import (
    DATABASE_URL,
    _chave_canonica_apresentacao,
    _deduplicar_apresentacoes_canonicas,
    _estruturar_apresentacao_campos,
    _forma_categoria_apresentacao,
    _norm,
    _trunc,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_FILE = ROOT / "scripts" / "vetsmart_raw" / "prescricoes.json"
FONTE_FABRICANTE = "VetSmart Prescritor"
RE_CONCENTRACAO_FARMACOLOGICA = re.compile(
    r"\b\d+(?:[,.]\d+)?\s*(?:mg|mcg|g|ui)\b|\b\d+(?:[,.]\d+)?\s*%",
    re.IGNORECASE,
)


def _iter_drugs(raw: Any) -> Iterable[Dict[str, Any]]:
    for prescricao in raw or []:
        drugs = prescricao.get("drugs") or prescricao.get("medications") or []
        if not drugs and prescricao.get("drug"):
            drugs = [prescricao]
        for drug in drugs:
            if isinstance(drug, dict):
                yield drug


def _normalizar_forma_prescritor(dosage_form: str, dosage_data: Dict[str, Any]) -> str:
    texto = (dosage_form or "").strip()
    partes = [p.strip() for p in texto.split(",") if p.strip()]
    if len(partes) >= 2:
        forma = partes[-1]
    else:
        forma = texto

    tipo = str((dosage_data or {}).get("type") or "").strip().lower()
    if "mililitro" in tipo or tipo == "ml":
        if "suspens" in _norm(texto):
            return "Suspensao oral"
        return "Solucao oral"
    if "gota" in tipo:
        return "Gotas"
    if "comprim" in tipo:
        return "Comprimido"
    if "caps" in tipo or "cáps" in tipo:
        return "Capsula"

    forma_norm = _norm(forma)
    if not forma_norm:
        return "Apresentacao"
    if "suspens" in forma_norm:
        return "Suspensao oral"
    if "solucao" in forma_norm or "liquido" in forma_norm:
        return "Solucao oral"
    if "gota" in forma_norm:
        return "Gotas"
    if "comprim" in forma_norm or "drage" in forma_norm:
        return "Comprimido"
    if "caps" in forma_norm:
        return "Capsula"
    return forma[:50]


def _apresentacao_do_drug(drug: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    dosage_form = str(drug.get("dosageForm") or "").strip()
    if not dosage_form:
        return None
    if not RE_CONCENTRACAO_FARMACOLOGICA.search(dosage_form):
        return None

    dosage_data = drug.get("dosageData") or {}
    forma = _normalizar_forma_prescritor(dosage_form, dosage_data)
    ap = {
        "forma": forma[:50],
        "concentracao": dosage_form[:100],
        "nome_variante": str(drug.get("drug") or "").strip()[:100] or None,
    }
    ap.update(_estruturar_apresentacao_campos(forma, dosage_form, str(drug.get("drug") or "")))
    ap["forma_categoria"] = _forma_categoria_apresentacao(ap["forma"], ap["concentracao"])
    return ap


def _int_texto(valor: Any) -> Optional[int]:
    texto = str(valor or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        numero = float(texto)
    except ValueError:
        return None
    if numero <= 0:
        return None
    return int(round(numero))


def _intervalo_horas_do_drug(drug: Dict[str, Any]) -> Optional[int]:
    data = drug.get("dosageData") or {}
    valor = _int_texto(data.get("interval"))
    if not valor:
        return None
    unidade = _norm(data.get("intervalUnit") or "")
    if unidade.startswith("dia"):
        return valor * 24
    if unidade.startswith("semana"):
        return valor * 24 * 7
    return valor


def _duracao_dias_do_drug(drug: Dict[str, Any]) -> Optional[int]:
    data = drug.get("dosageData") or {}
    valor = _int_texto(data.get("duration"))
    if not valor:
        return None
    unidade = _norm(data.get("durationUnit") or "")
    if unidade.startswith("semana"):
        return valor * 7
    if unidade.startswith("mes"):
        return valor * 30
    if unidade.startswith("hora"):
        return max(1, int(round(valor / 24)))
    return valor


def _texto_freq(intervalos: List[int]) -> Optional[str]:
    if not intervalos:
        return None
    vals = sorted(set(intervalos))
    if len(vals) == 1:
        return f"{vals[0]}/{vals[0]} horas"
    return " ou ".join(f"{v}/{v} horas" for v in vals[:3])


def _duracao_referencia(duracoes: List[int]) -> tuple[Optional[int], Optional[int], Optional[str]]:
    if not duracoes:
        return (None, None, None)
    # Historico de prescricoes pode conter tratamentos prolongados. Para
    # antimicrobianos e outras terapias agudas, uma amostra curta e frequente
    # representa melhor a referencia do painel do prescritor.
    agudas = [d for d in duracoes if 1 <= d <= 14]
    base = agudas if len(agudas) >= 3 else duracoes
    mn = min(base)
    mx = max(base)
    if mn == mx:
        return (mn, mx, f"{mn} dias")
    return (mn, mx, f"{mn} a {mx} dias")


def _resumo_prescritor(drugs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not drugs:
        return None
    duracoes = [d for d in (_duracao_dias_do_drug(drug) for drug in drugs) if d]
    intervalos = [i for i in (_intervalo_horas_do_drug(drug) for drug in drugs) if i]
    vias = Counter(str(drug.get("usage") or "").strip() for drug in drugs if str(drug.get("usage") or "").strip())
    formas = Counter(str(drug.get("dosageForm") or "").strip() for drug in drugs if str(drug.get("dosageForm") or "").strip())
    exemplos = []
    vistos = set()
    for drug in drugs:
        dosage = str(drug.get("dosage") or "").strip()
        if not dosage or dosage in vistos:
            continue
        vistos.add(dosage)
        exemplos.append({
            "apresentacao": str(drug.get("dosageForm") or "").strip(),
            "posologia": dosage[:220],
        })
        if len(exemplos) >= 5:
            break

    dur_min, dur_max, dur_txt = _duracao_referencia(duracoes)
    resumo = {
        "fonte": "VetSmart Prescritor",
        "tipo": "estatistica_prescricoes_exportadas",
        "n_registros": len(drugs),
        "duracoes_observadas_dias": sorted(Counter(duracoes).items()),
        "duracao_min_dias": dur_min,
        "duracao_max_dias": dur_max,
        "duracao_texto": dur_txt,
        "frequencias_observadas_horas": sorted(Counter(intervalos).items()),
        "frequencia_texto": _texto_freq(intervalos),
        "vias_observadas": vias.most_common(5),
        "apresentacoes_observadas": formas.most_common(12),
        "exemplos_posologia": exemplos,
        "nota_clinica": (
            "Dados extraidos do catalogo/historico do prescritor VetSmart; "
            "usar como apoio operacional quando a bula estruturada nao trouxer o campo."
        ),
    }
    if not duracoes and not intervalos and not exemplos:
        return None
    return resumo


def _buscar_medicamento_id(cur, drug: Dict[str, Any]) -> Optional[int]:
    drug_id = str(drug.get("drugId") or "").strip()
    nome = str(drug.get("drug") or "").strip()

    if drug_id.isdigit():
        cur.execute(
            "SELECT id FROM medicamento WHERE vetsmart_produto_id = %s ORDER BY id LIMIT 1",
            (int(drug_id),),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])

    nome_norm = _norm(nome)
    if not nome_norm:
        return None
    cur.execute(
        """
        SELECT id FROM medicamento
         WHERE LOWER(REGEXP_REPLACE(
                 TRANSLATE(COALESCE(principio_ativo, nome),
                           'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                           'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'),
                 '\\s+', ' ', 'g')) = %s
            OR LOWER(REGEXP_REPLACE(
                 TRANSLATE(nome,
                           'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
                           'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'),
                 '\\s+', ' ', 'g')) = %s
         ORDER BY id LIMIT 1
        """,
        (nome_norm, nome_norm),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def _carregar_existentes(cur, medicamento_id: int) -> set:
    cur.execute(
        """
        SELECT forma, concentracao, fabricante, concentracao_valor,
               concentracao_unidade, volume_valor, volume_unidade
          FROM apresentacao_medicamento
         WHERE medicamento_id = %s
        """,
        (medicamento_id,),
    )
    return {
        _chave_canonica_apresentacao(
            {
                "forma": r.get("forma") or "",
                "concentracao": r.get("concentracao") or "",
                "concentracao_valor": r.get("concentracao_valor"),
                "concentracao_unidade": r.get("concentracao_unidade"),
                "volume_valor": r.get("volume_valor"),
                "volume_unidade": r.get("volume_unidade"),
            },
            r.get("fabricante") or "",
        )
        for r in cur.fetchall()
    }


def _inserir_apresentacao(cur, medicamento_id: int, ap: Dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO apresentacao_medicamento
          (medicamento_id, forma, concentracao, nome_variante,
           concentracao_valor, concentracao_unidade, volume_valor, volume_unidade,
           fabricante, vetsmart_produto_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            medicamento_id,
            _trunc(ap.get("forma"), 50),
            _trunc(ap.get("concentracao"), 100),
            _trunc(ap.get("nome_variante"), 100),
            ap.get("concentracao_valor"),
            _trunc(ap.get("concentracao_unidade"), 20),
            ap.get("volume_valor"),
            _trunc(ap.get("volume_unidade"), 20),
            FONTE_FABRICANTE,
            None,
        ),
    )


def _atualizar_resumo_prescritor(cur, medicamento_id: int, resumo: Dict[str, Any]) -> None:
    cur.execute(
        "SELECT conteudo_estruturado FROM medicamento WHERE id = %s",
        (medicamento_id,),
    )
    row = cur.fetchone()
    atual = row.get("conteudo_estruturado") if row else None
    if not isinstance(atual, dict):
        atual = {}
    atual["prescritor_vetsmart"] = resumo
    cur.execute(
        "UPDATE medicamento SET conteudo_estruturado = %s WHERE id = %s",
        (Json(atual), medicamento_id),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=str(RAW_FILE))
    parser.add_argument("--filtro", default=None, help="Filtra pelo nome do medicamento.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    filtro_norm = _norm(args.filtro or "")
    candidatos: Dict[int, List[Dict[str, Any]]] = {}
    drugs_por_med: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    nomes: Dict[int, str] = {}
    vistos_por_med: Dict[int, set] = {}
    contagem = Counter()

    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=15)
    try:
        with conn.cursor() as cur:
            for drug in _iter_drugs(raw):
                nome = str(drug.get("drug") or "").strip()
                if filtro_norm and filtro_norm not in _norm(nome):
                    continue
                ap = _apresentacao_do_drug(drug)
                med_id = _buscar_medicamento_id(cur, drug)
                if not med_id:
                    contagem["sem_medicamento"] += 1
                    continue
                drugs_por_med[med_id].append(drug)
                if not ap:
                    continue
                nomes.setdefault(med_id, nome)
                chave = _chave_canonica_apresentacao(ap, FONTE_FABRICANTE)
                vistos = vistos_por_med.setdefault(med_id, set())
                if chave in vistos:
                    continue
                vistos.add(chave)
                candidatos.setdefault(med_id, []).append(ap)

            for med_id, aps in candidatos.items():
                aps = _deduplicar_apresentacoes_canonicas(aps, FONTE_FABRICANTE)
                existentes = _carregar_existentes(cur, med_id)
                for ap in aps:
                    chave = _chave_canonica_apresentacao(ap, FONTE_FABRICANTE)
                    if chave in existentes:
                        contagem["ja_existia"] += 1
                        continue
                    contagem["inseridas"] += 1
                    print(f"+ med_id={med_id} {nomes.get(med_id, '')}: {ap['concentracao']} [{ap['forma']}]")
                    if not args.dry_run:
                        _inserir_apresentacao(cur, med_id, ap)
                        existentes.add(chave)

            for med_id, drugs in drugs_por_med.items():
                resumo = _resumo_prescritor(drugs)
                if not resumo:
                    continue
                contagem["resumos_atualizados"] += 1
                print(
                    f"~ med_id={med_id} resumo prescritor: "
                    f"freq={resumo.get('frequencia_texto') or '-'} "
                    f"dur={resumo.get('duracao_texto') or '-'}"
                )
                if not args.dry_run:
                    _atualizar_resumo_prescritor(cur, med_id, resumo)

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()

    print("Resumo:", dict(contagem))


if __name__ == "__main__":
    main()
