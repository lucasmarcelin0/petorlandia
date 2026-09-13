"""Calendário da doença e trabalho de campo. Nenhuma chamada externa."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json


VERSION = "collective-v3-disease-clock"


def hoje_local():
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def inicio_doenca(paciente):
    """Uma revisão explícita resolve divergências; nunca usar a entrevista como D0."""
    from services.sfa_service import parse_data
    contexto = getattr(paciente, "contexto", None)
    if contexto and contexto.inicio_sintomas:
        inicio = contexto.inicio_sintomas
        return (inicio, contexto.fonte_inicio or "Revisão") if inicio <= hoje_local() else (None, "Data futura")
    resposta = getattr(paciente, "resposta_t0", None)
    candidatos = []
    if resposta:
        try:
            payload = json.loads(resposta.dados_json or "{}")
        except (ValueError, AttributeError):
            payload = {}
        valor_inicio = getattr(resposta, "data_inicio_sintomas", None) or payload.get("data_inicio_sintomas")
        if payload.get("_instrument_version") == VERSION and not valor_inicio:
            return None, "Início dos sintomas não informado no T0; revisar"
        candidatos.append((valor_inicio, "T0"))
    log = getattr(paciente, "_sinan_log", None)
    if log:
        candidatos.append((log.data_inicio_sintomas, "SINAN"))
    elif getattr(paciente, "_sinan_dados", None):
        candidatos.append((paciente._sinan_dados.get("data_inicio_sintomas"), "SINAN"))
    elif not hasattr(paciente, "_sinan_log"):
        from services.sfa_service import montar_contexto_importado_formulario
        candidatos.append((montar_contexto_importado_formulario(paciente).get("data_inicio_sintomas"), "SINAN"))
    datas = [(parse_data(valor), fonte) for valor, fonte in candidatos if valor]
    if any(d is None or d > hoje_local() for d, _ in datas):
        return None, "Data inválida ou futura"
    if len({d for d, _ in datas}) > 1:
        return None, "Divergência entre T0 e SINAN"
    return datas[0] if datas else (None, "Início dos sintomas ausente")


def resumo_calendario(paciente):
    inicio, fonte = inicio_doenca(paciente)
    return {"inicio": inicio, "fonte": fonte,
            "dia_doenca": (hoje_local() - inicio).days if inicio else None,
            "t7": inicio + timedelta(days=7) if inicio else None,
            "t30": inicio + timedelta(days=30) if inicio else None}


def aplicar_calendario(paciente):
    """Só agenda pendências; datas de respostas históricas ficam preservadas."""
    from services.sfa_service import formatar_data
    calendario = resumo_calendario(paciente)
    for etapa in ("t7", "t30"):
        if getattr(paciente, f"respostas_{etapa}", None):
            continue
        if etapa == "t7" and getattr(paciente, "respostas_t10", None):
            paciente.status_t7 = "LEGADO_T10"
            paciente.data_t7 = None
            continue
        setattr(paciente, f"data_{etapa}", formatar_data(calendario[etapa]) if calendario[etapa] else None)
        if getattr(paciente, "resposta_t0", None) or paciente.status_t0 == "T0_Completo":
            status = "REVISAR_DATA" if not calendario[etapa] else (
                "ATRASADO" if calendario[etapa] < hoje_local() else "Aguardando")
            setattr(paciente, f"status_{etapa}", status)
    return calendario


def impedimento_etapa(paciente, etapa):
    if getattr(paciente, "retorno_contato", "") == "RECUSOU":
        return "Participação recusada. Entre em contato com a equipe para revisar sua decisão."
    if etapa == "t0":
        return None
    if not getattr(paciente, "resposta_t0", None):
        return "É necessário registrar o T0 antes do acompanhamento."
    if etapa == "t7" and getattr(paciente, "respostas_t10", None):
        return "Este episódio já tem um T10 histórico. A equipe deve acompanhar a etapa T30."
    calendario = resumo_calendario(paciente)
    if not calendario["inicio"]:
        return "A equipe precisa confirmar a data de início dos sintomas antes deste acompanhamento."
    alvo = calendario[etapa]
    if hoje_local() < alvo:
        return f"Este acompanhamento estará disponível em {alvo:%d/%m/%Y}, no D{7 if etapa == 't7' else 30} da doença."
    return None


def metadados_coleta(paciente, etapa, dados):
    from services.sfa_service import _data_resposta_stage, obter_payload_formulario
    calendario = resumo_calendario(paciente)
    data_coleta = hoje_local()
    inicio_intervalo = calendario["inicio"]
    if etapa != "t0":
        candidatos = ["t0"] if etapa == "t7" else ["t0", "t10", "t7"]
        anteriores = []
        for anterior in candidatos:
            resposta, payload = obter_payload_formulario(paciente, anterior)
            if resposta:
                dt = _data_resposta_stage(anterior, resposta, payload)
                if dt:
                    anteriores.append(dt)
        inicio_intervalo = max(anteriores) if anteriores else None
    dados["_calendario"] = {
        "base": "inicio_sintomas", "inicio_sintomas": str(calendario["inicio"] or ""),
        "fonte": calendario["fonte"], "data_coleta": data_coleta.isoformat(),
        "dia_doenca": calendario["dia_doenca"],
        "data_alvo": str(calendario.get(etapa) or ""),
        "intervalo_desde": str(inicio_intervalo or ""), "intervalo_ate": str(data_coleta),
        "regra_intervalo": "Desde o início no T0; desde a última resposta anterior nos seguimentos. Não somar períodos sobrepostos.",
    }


def pendencias_qualidade(pacientes):
    from services.sfa_service import obter_payload_formulario, t0_consentimento_aceito
    pendencias = []
    for p in pacientes:
        motivos = []
        inicio, fonte = inicio_doenca(p)
        if not inicio:
            motivos.append(fonte)
        log = getattr(p, "_sinan_log", None)
        if not log or not log.dados_json:
            motivos.append("SINAN sem complemento estruturado")
        elif log.revisao_status == "REVISAR":
            motivos.append("Conferir revisão da ficha SINAN")
        r, payload = obter_payload_formulario(p, "t0")
        if r and not t0_consentimento_aceito(payload.get("aceite_tcle")):
            motivos.append("Conferir evidência de consentimento do T0 histórico")
        if not getattr(p, "contexto", None) or not p.contexto.local_validado:
            motivos.append("Território ainda não validado")
        if motivos:
            pendencias.append({"paciente": p, "motivos": motivos})
    return pendencias


def semana_inicio(dia):
    """Domingo a sábado; a data inicial evita ambiguidade de ano/semana ISO."""
    return dia - timedelta(days=(dia.weekday() + 1) % 7)


def vigilancia_semanal(pacientes, snapshot, defasagem=0):
    """Agrega antes de relacionar: nunca multiplica episódios por visitas.

    Setores são da malha operacional do levantamento, não do Censo. Ausência
    de envio não representa zero. Residência não representa local de infecção.
    """
    from services.sfa_service import parse_data, paciente_eh_teste_sfa
    if defasagem not in range(5):
        raise ValueError("Defasagem deve estar entre zero e quatro semanas.")
    humanos, vetores = defaultdict(list), defaultdict(list)
    excluidos = defaultdict(int)
    for p in pacientes:
        if paciente_eh_teste_sfa(p):
            excluidos["testes"] += 1
            continue
        inicio, _ = inicio_doenca(p)
        contexto = getattr(p, "contexto", None)
        if not inicio:
            excluidos["sem_inicio_valido"] += 1
        elif not (contexto and contexto.local_validado and contexto.malha == "operacional"
                  and contexto.tipo_local == "RESIDENCIA" and contexto.setor):
            excluidos["sem_residencia_validada"] += 1
        else:
            humanos[(semana_inicio(inicio), contexto.setor)].append(p)
    for registro in snapshot.get("records", []):
        dia = parse_data(registro.get("date"))
        setor = str(registro.get("sector") or "").strip()
        if not dia or dia > hoje_local() or not setor:
            excluidos["visitas_sem_data_setor_validos"] += 1
            continue
        vetores[(semana_inicio(dia), setor)].append(registro)
    delta = timedelta(weeks=defasagem)
    chaves = set(humanos) | {(semana + delta, setor) for semana, setor in vetores}
    # Uma defasagem positiva não cria semanas futuras com falsos zeros humanos.
    chaves = {chave for chave in chaves if chave[0] <= semana_inicio(hoje_local())}
    linhas = []
    for semana, setor in sorted(chaves, reverse=True):
        pessoas = humanos.get((semana, setor), [])
        registros = vetores.get((semana - delta, setor), [])
        def soma(campo):
            valores = [r[campo] for r in registros if r.get(campo) is not None]
            return sum(valores) if valores else None
        linhas.append({"semana": semana, "setor": setor, "semana_vetor": semana - delta,
                       "semana_em_curso": semana + timedelta(days=6) >= hoje_local(),
                       "episodios": len(pessoas), "registros_vetor": len(registros),
                       "worked": soma("worked"), "positive": soma("positive"),
                       "closed": soma("closed"), "refused": soma("refused"),
                       "aegypti_larvae": soma("aegypti_larvae"),
                       "larvas_preenchidas": sum(r.get("aegypti_larvae") is not None for r in registros),
                       "classificacao_conhecida": sum(bool(p.contexto.classificacao and p.contexto.classificacao != "INDEFINIDA") for p in pessoas)})
    return {"linhas": linhas, "excluidos": dict(excluidos), "fonte": snapshot.get("source", {}),
            "defasagem": defasagem}
