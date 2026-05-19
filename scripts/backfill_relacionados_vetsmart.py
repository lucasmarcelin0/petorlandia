"""Backfill de um medicamento usando a página canônica do VetSmart.

Em vez de depender do nome do produto na lista paginada, este script:
  1. parte do `medicamento.vetsmart_produto_id` canônico;
  2. abre a página do princípio ativo no VetSmart;
  3. coleta os links em "Opções Veterinárias com ...";
  4. raspa a página canônica + cada opção relacionada;
  5. insere apresentações e doses no `med_id` alvo.

Uso típico:
  python scripts/backfill_relacionados_vetsmart.py --dry-run --med-id 2246
  python scripts/backfill_relacionados_vetsmart.py --apply   --med-id 2246

Fluxo recomendado:
  1. gerar snapshot + limpar filhos com `backfill_medicamentos_bulario.py`
  2. rodar este script em `--dry-run` para conferir as fontes descobertas
  3. rodar em `--apply` para gravar no banco
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List

from psycopg2.extras import RealDictCursor

import importar_medicamentos_vetsmart as vetsmart

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Instale: pip install playwright && python -m playwright install chromium")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Só raspa e mostra o que seria importado.")
    mode.add_argument("--apply", action="store_true", help="Importa no banco as apresentações e doses descobertas.")
    parser.add_argument(
        "--med-id",
        action="append",
        dest="med_ids",
        type=int,
        required=True,
        help="ID do medicamento alvo. Repita a flag para múltiplos IDs.",
    )
    parser.add_argument("--visible", action="store_true", help="Abre o navegador visível para depuração.")
    return parser.parse_args()


def buscar_alvos(cur, med_ids: List[int]) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT id, nome, principio_ativo, vetsmart_produto_id
          FROM medicamento
         WHERE id = ANY(%s)
         ORDER BY nome
        """,
        (med_ids,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    encontrados = {r["id"] for r in rows}
    faltantes = [mid for mid in med_ids if mid not in encontrados]
    if faltantes:
        raise SystemExit(f"Medicamentos não encontrados: {faltantes}")
    return rows


def _info_produto(pid: int, nome: str) -> Dict[str, Any]:
    return {
        "id": int(pid),
        "nome": (nome or f"Produto #{pid}")[:100],
        "url": f"{vetsmart.BASE_URL}/cg/produto/{int(pid)}",
    }


def resolver_info_canonico(page, med: Dict[str, Any]) -> Dict[str, Any]:
    if med.get("vetsmart_produto_id"):
        return _info_produto(med["vetsmart_produto_id"], med["nome"])

    alvo_norms = {
        vetsmart._norm(med.get("nome") or ""),
        vetsmart._norm(med.get("principio_ativo") or ""),
    } - {""}
    if not alvo_norms:
        raise SystemExit(f"[{med['id']}] {med['nome']}: sem nome/PA para buscar página canônica.")

    vetsmart.log.info(f"[{med['id']}] Sem vetsmart_produto_id; procurando página canônica na lista.")
    lista = vetsmart.scrape_lista_produtos(page)
    candidatos = [it for it in lista if vetsmart._norm(it["nome"]) in alvo_norms]
    if not candidatos:
        raise SystemExit(f"[{med['id']}] {med['nome']}: não achei página canônica na lista do VetSmart.")

    alvo_principal = vetsmart._norm(med.get("nome") or med.get("principio_ativo") or "")
    exato = next((it for it in candidatos if vetsmart._norm(it["nome"]) == alvo_principal), None)
    return exato or candidatos[0]


def descobrir_fontes(page, med: Dict[str, Any]):
    info_canonico = resolver_info_canonico(page, med)
    produto_canonico, html = vetsmart.scrape_detalhe_produto(page, info_canonico, return_html=True)
    relacionados = vetsmart._extrair_links_opcoes_veterinarias(html, excluir_pid=info_canonico["id"])
    return info_canonico, produto_canonico, relacionados


def processar_medicamento(conn, page, med: Dict[str, Any], apply: bool) -> Dict[str, Any]:
    info_canonico, produto_canonico, relacionados = descobrir_fontes(page, med)
    fontes = [info_canonico] + relacionados
    resumo_fontes = []
    total_apres = 0
    total_doses = 0

    for idx, info in enumerate(fontes, 1):
        if idx == 1:
            prod = produto_canonico
        else:
            prod = vetsmart.scrape_detalhe_produto(page, info)

        resumo_fontes.append(
            {
                "id": info["id"],
                "nome_lista": info["nome"],
                "nome_raspado": prod.nome,
                "principio_ativo": prod.principio_ativo,
                "fabricante": prod.fabricante,
                "apresentacoes": len(prod.apresentacoes or []),
                "doses": len(prod.doses or []),
            }
        )

        if apply:
            with conn.cursor() as cur:
                if idx == 1:
                    vetsmart._atualizar_medicamento_existente(cur, med["id"], prod)
                else:
                    cur.execute(
                        "SELECT conteudo_estruturado FROM medicamento WHERE id = %s",
                        (med["id"],),
                    )
                    row = cur.fetchone()
                    conteudo_atual = row.get("conteudo_estruturado") if isinstance(row, dict) else None
                    conteudo = vetsmart._mesclar_produto_vetsmart(conteudo_atual or {}, prod)
                    cur.execute(
                        "UPDATE medicamento SET conteudo_estruturado = %s WHERE id = %s",
                        (vetsmart.Json(conteudo), med["id"]),
                    )
                total_apres += vetsmart._inserir_apresentacoes_consolidado(cur, med["id"], prod)
                total_doses += vetsmart._inserir_doses_consolidado(cur, med["id"], prod.doses or [])

        if idx < len(fontes):
            time.sleep(vetsmart.DELAY_PAGINAS)

    if apply:
        conn.commit()

    return {
        "medicamento": med,
        "canonical": info_canonico,
        "fontes": resumo_fontes,
        "apresentacoes_inseridas": total_apres,
        "doses_inseridas": total_doses,
    }


def imprimir_resultado(resultado: Dict[str, Any], apply: bool) -> None:
    med = resultado["medicamento"]
    print("")
    print("=" * 72)
    print(f"[{med['id']}] {med['nome']} | PA={med.get('principio_ativo') or '-'}")
    print(f"Página canônica: {resultado['canonical']['url']}")
    print(f"Fontes encontradas: {len(resultado['fontes'])}")
    for fonte in resultado["fontes"]:
        print(
            f"  - pid={fonte['id']} | {fonte['nome_raspado']} | "
            f"PA={fonte['principio_ativo'] or '-'} | "
            f"fab={fonte['fabricante'] or '-'} | "
            f"apres={fonte['apresentacoes']} | doses={fonte['doses']}"
        )
    if apply:
        print(f"Inseridas: {resultado['apresentacoes_inseridas']} apresentações, {resultado['doses_inseridas']} doses")
    else:
        print("Modo dry-run: nenhuma linha foi gravada.")
    print("=" * 72)


def main():
    args = parse_args()
    med_ids = sorted(set(args.med_ids))

    conn = vetsmart.conectar_banco()
    try:
        with conn.cursor() as cur:
            meds = buscar_alvos(cur, med_ids)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.visible)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            vetsmart.log.info("Abrindo home para aceitar cookies…")
            page.goto(vetsmart.BASE_URL, wait_until="networkidle", timeout=30000)
            vetsmart.aguardar_e_aceitar_cookies(page, timeout=8000)
            time.sleep(1)

            for med in meds:
                try:
                    resultado = processar_medicamento(conn, page, med, apply=args.apply)
                    imprimir_resultado(resultado, apply=args.apply)
                except Exception as exc:
                    conn.rollback()
                    print("")
                    print("=" * 72)
                    print(f"[{med['id']}] {med['nome']} | ERRO: {exc}")
                    print("=" * 72)
                    raise

            browser.close()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
