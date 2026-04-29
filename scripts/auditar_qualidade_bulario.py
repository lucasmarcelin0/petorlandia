"""Audita a qualidade do bulário estruturado.

Uso:
  python scripts/auditar_qualidade_bulario.py
  python scripts/auditar_qualidade_bulario.py --limit 100 --markdown-out relatorio.md --json-out relatorio.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from models.base import Medicamento  # noqa: E402
from services.bulario import montar_monografia_medicamento  # noqa: E402


def _percentual(parte: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((parte / total) * 100, 2)


def _carregar_medicamentos(limit: int) -> List[Medicamento]:
    query = Medicamento.query.order_by(Medicamento.id.asc())
    if limit > 0:
        query = query.limit(limit)
    return query.all()


def _coletar_metricas(medicamentos: List[Medicamento]) -> Dict[str, Any]:
    total = len(medicamentos)
    com_doses = 0
    com_indicacoes = 0
    com_contra = 0
    com_interacoes = 0
    somente_legado = 0
    vazios_com_obs: List[Dict[str, Any]] = []

    for med in medicamentos:
        mono = montar_monografia_medicamento(med)
        secoes = mono["secoes"]
        tabs = mono["resumo_posologia"]["tabs"]
        metadata = secoes.get("metadata") or {}
        parser_version = metadata.get("parser_version")

        if tabs:
            com_doses += 1
        if secoes["indicacoes"]["itens"]:
            com_indicacoes += 1
        if secoes["contraindicacoes"]["resumo"] or secoes["contraindicacoes"]["itens"]:
            com_contra += 1
        if secoes["interacoes"]["itens"]:
            com_interacoes += 1
        if parser_version == "legacy-fallback-v1":
            somente_legado += 1

        tem_conteudo_clinico = mono["tem_conteudo_clinico"]
        if med.observacoes and not tem_conteudo_clinico:
            vazios_com_obs.append({
                "id": med.id,
                "nome": med.nome,
                "observacoes_preview": (med.observacoes or "")[:220],
            })

    return {
        "total_medicamentos": total,
        "com_doses_estruturadas": {
            "count": com_doses,
            "percent": _percentual(com_doses, total),
        },
        "com_indicacoes": {
            "count": com_indicacoes,
            "percent": _percentual(com_indicacoes, total),
        },
        "com_contraindicacoes_destacaveis": {
            "count": com_contra,
            "percent": _percentual(com_contra, total),
        },
        "com_interacoes_estruturadas": {
            "count": com_interacoes,
            "percent": _percentual(com_interacoes, total),
        },
        "apenas_fallback_legado": {
            "count": somente_legado,
            "percent": _percentual(somente_legado, total),
        },
        "top_clinica_vazia_com_observacoes": vazios_com_obs[:20],
    }


def _render_markdown(metricas: Dict[str, Any]) -> str:
    linhas = [
        "# Auditoria do Bulário",
        "",
        f"- Total de medicamentos auditados: **{metricas['total_medicamentos']}**",
        f"- Com doses estruturadas: **{metricas['com_doses_estruturadas']['count']}** ({metricas['com_doses_estruturadas']['percent']}%)",
        f"- Com pelo menos uma indicação: **{metricas['com_indicacoes']['count']}** ({metricas['com_indicacoes']['percent']}%)",
        f"- Com contraindicações destacáveis: **{metricas['com_contraindicacoes_destacaveis']['count']}** ({metricas['com_contraindicacoes_destacaveis']['percent']}%)",
        f"- Com interações estruturadas: **{metricas['com_interacoes_estruturadas']['count']}** ({metricas['com_interacoes_estruturadas']['percent']}%)",
        f"- Apenas fallback legado: **{metricas['apenas_fallback_legado']['count']}** ({metricas['apenas_fallback_legado']['percent']}%)",
        "",
        "## Top medicamentos com observações mas sem seção clínica útil",
        "",
    ]

    vazios = metricas["top_clinica_vazia_com_observacoes"]
    if not vazios:
        linhas.append("- Nenhum caso encontrado.")
    else:
        for item in vazios:
            linhas.append(
                f"- `{item['id']}` {item['nome']}: {item['observacoes_preview'].replace(chr(10), ' ')}"
            )
    linhas.append("")
    return "\n".join(linhas)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--markdown-out", default="")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    with app.app_context():
        medicamentos = _carregar_medicamentos(args.limit)
        metricas = _coletar_metricas(medicamentos)

    markdown = _render_markdown(metricas)
    print(markdown)

    if args.markdown_out:
        Path(args.markdown_out).write_text(markdown, encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(metricas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
