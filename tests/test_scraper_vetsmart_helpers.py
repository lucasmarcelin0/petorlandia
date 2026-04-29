"""Testes unitários dos helpers do scraper VetSmart (scripts/importar_medicamentos_vetsmart.py).

Focamos nas funções que extraem dados do HTML/texto bruto — nenhuma dessas
depende do banco ou de Playwright, então rodam offline e rápido.

Razão: o scraper é sensível a pequenas variações no markup da VetSmart (ordem
de campos, "Dermatite atópica" vs "atopia", "por 7 dias" no campo de frequência
vs duração). Sem testes, qualquer mudança no parser pode silenciosamente parar
de capturar dose/indicação/duração e os usuários só descobrem quando o
veterinário ver dose 8 mg onde deveria ser 16 mg.
"""
import sys
import pathlib

# O módulo não está num pacote — importa pelo path direto.
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import importar_medicamentos_vetsmart as scraper  # noqa: E402


# ── _extrair_indicacao ──────────────────────────────────────────────────────

def test_indicacao_dermatite_atopica_vence_alergia():
    # "Dermatite atópica" começa no texto antes de "alergia" ganharia sozinho;
    # mas mesmo em empate de posição, a ordem no _INDICACAO_PATTERNS garante
    # que o padrão específico vença.
    assert scraper._extrair_indicacao('Dermatite atópica em cães alérgicos') == 'Dermatite atópica'


def test_indicacao_imunossupressao_com_typos_vetsmart():
    # VetSmart escreve "imunosupressão" (um 's' só) e "imunossupresão" (um 'ss'+'s' só).
    for txt in ['imunosupressão', 'imunossupresão', 'imuno supressão', 'Imunossupressão']:
        assert scraper._extrair_indicacao(txt) == 'Imunossupressão', txt


def test_indicacao_endocrinopatias():
    assert scraper._extrair_indicacao('endocrinopatias') == 'Endocrinopatia'
    assert scraper._extrair_indicacao('hipocortisolismo') == 'Hipoadrenocorticismo'
    assert scraper._extrair_indicacao('síndrome de Cushing') == 'Hipercortisolismo'


def test_indicacao_osteoarticular_nao_vira_alergia():
    # "doenças osteoarticulares" nunca deve virar 'Alergia' só porque
    # 'alerg' também não está lá — teste de não-regressão de hierarquia.
    assert scraper._extrair_indicacao('doenças osteoarticulares') == 'Osteoarticular'


def test_indicacao_neoplasia():
    assert scraper._extrair_indicacao('pacientes portadores de neoplasias') == 'Neoplasia'
    assert scraper._extrair_indicacao('câncer pulmonar') == 'Neoplasia'
    assert scraper._extrair_indicacao('tumor mamário') == 'Neoplasia'


def test_indicacao_respiratorio_cobre_broncopat():
    # Do texto real da Prednisona VetSmart: "broncopatias".
    assert scraper._extrair_indicacao('broncopatias crônicas') == 'Respiratório'


def test_indicacao_none_se_texto_generico():
    assert scraper._extrair_indicacao('paciente clinicamente estável') is None
    assert scraper._extrair_indicacao('') is None
    assert scraper._extrair_indicacao(None) is None


# ── _intervalo_horas ────────────────────────────────────────────────────────

def test_intervalo_formato_barra():
    assert scraper._intervalo_horas('12/12 horas') == 12
    assert scraper._intervalo_horas('8/8h') == 8


def test_intervalo_formato_a_cada():
    assert scraper._intervalo_horas('a cada 24 horas') == 24
    assert scraper._intervalo_horas('a cada 6h') == 6


def test_intervalo_vezes_ao_dia():
    assert scraper._intervalo_horas('2 vezes ao dia') == 12
    assert scraper._intervalo_horas('3x por dia') == 8


def test_intervalo_fallback_liberal_com_multiplas_indicacoes():
    # Texto real do cache LigVet: pega o primeiro "Nh" plausível.
    t = 'Alergias e imunossupressão: 12h. Dermatite atópica: 24hrs por 7 dias.'
    assert scraper._intervalo_horas(t) == 12


def test_intervalo_dose_unica():
    assert scraper._intervalo_horas('Dose única após procedimento') is None


# ── _duracao_dias ──────────────────────────────────────────────────────────

def test_duracao_por_7_dias():
    # Regressão: texto real da LigVet — "por 7 dias" embutido no campo
    # frequência, mas a função deve achar quando chamada diretamente.
    assert scraper._duracao_dias('por 7 dias') == (7, 7)


def test_duracao_embutida_no_texto_de_frequencia():
    t = 'Dermatite atópica: 24hrs por 7 dias. Após administrar 0,5mg/kg/48hs'
    assert scraper._duracao_dias(t) == (7, 7)


def test_duracao_faixa():
    assert scraper._duracao_dias('5 a 10 dias') == (5, 10)
    assert scraper._duracao_dias('5-10 dias') == (5, 10)


def test_duracao_ate():
    assert scraper._duracao_dias('até 14 dias') == (None, 14)


def test_duracao_semanas_converte_em_dias():
    assert scraper._duracao_dias('2 semanas') == (14, 14)


def test_duracao_vazio_retorna_nada():
    assert scraper._duracao_dias('') == (None, None)
    assert scraper._duracao_dias(None) == (None, None)


# ── _estruturar_apresentacao_campos ────────────────────────────────────────

def test_apresentacao_mg_por_ml():
    # "Solução oral 50 mg/mL (50 ml)"
    out = scraper._estruturar_apresentacao_campos('Solução oral', '50 mg/mL (50 ml)', 'Dipirona')
    assert out['concentracao_valor'] == 50.0
    assert out['concentracao_unidade'] == 'mg/ml'
    assert out['volume_valor'] == 50.0
    assert out['volume_unidade'] == 'ml'


def test_apresentacao_mg_comprimido():
    out = scraper._estruturar_apresentacao_campos('Comprimido', '5 mg', 'Prednisona')
    assert out['concentracao_valor'] == 5.0
    assert out['concentracao_unidade'] == 'mg'


def test_apresentacao_sem_concentracao_mantem_vazio():
    # Regressão: antes o scraper colocava "Prednisona Animalia" como concentração
    # quando não havia número. Tem que ficar None/vazio.
    out = scraper._estruturar_apresentacao_campos(
        'Cápsulas', '', 'Prednisona Animalia Farma Cápsulas'
    )
    assert out['concentracao_valor'] is None
    assert out['concentracao_unidade'] is None


def test_apresentacao_numero_no_nome_como_fallback():
    # "Rilexine palatável 75" — heurística assume mg.
    out = scraper._estruturar_apresentacao_campos('Comprimido', 'Rilexine palatável 75', 'Rilexine')
    assert out['concentracao_valor'] == 75.0
    assert out['concentracao_unidade'] == 'mg'


def test_apresentacao_percentual_liquida_vira_mg_por_ml():
    out = scraper._estruturar_apresentacao_campos('Colírio', 'Tobramicina 0,35% (10 mL)', 'Tobramicina')
    assert out['concentracao_valor'] == 3.5
    assert out['concentracao_unidade'] == 'mg/ml'
    assert out['volume_valor'] == 10.0
    assert out['volume_unidade'] == 'ml'


# ── _norm_especie_code ──────────────────────────────────────────────────────

def test_especie_code_caes_e_gatos():
    assert scraper._norm_especie_code('Cães e Gatos') == 'AMBOS'
    assert scraper._norm_especie_code('Gatos') == 'GATOS'
    assert scraper._norm_especie_code('Cães') == 'CAES'
    assert scraper._norm_especie_code('felinos') == 'GATOS'
    assert scraper._norm_especie_code('caninos') == 'CAES'


# ── _extrair_doses_estruturadas: fallback de duração ───────────────────────

def test_doses_usam_duracao_da_frequencia_quando_duracao_vazia():
    """Cenário real do cache: duração em branco, mas freq tem 'por 7 dias'.
    Até o fix, as doses saíam com duracao_min_dias=None. Agora devem pegar 7.
    """
    doses = scraper._extrair_doses_estruturadas(
        dose_linhas=['Cães 0,5 mg/kg'],
        via='Oral',
        frequencia_texto='Dermatite atópica: 24hrs por 7 dias.',
        duracao_texto=None,
        especies_str='Cães e Gatos',
    )
    assert doses, 'parser não gerou doses'
    assert doses[0]['duracao_min_dias'] == 7
    assert doses[0]['duracao_max_dias'] == 7


def test_doses_extraem_gotas_por_olho_como_dose_estruturada():
    doses = scraper._extrair_doses_estruturadas(
        dose_linhas=['Cães e Gatos: 1 a 2 gotas por olho'],
        via='Oftálmico',
        frequencia_texto='8/8 horas',
        duracao_texto=None,
        especies_str='Cães e Gatos',
    )
    assert doses, 'parser não gerou dose oftálmica'
    assert doses[0]['dose_unidade'] == 'GOTAS_ANIMAL'
    assert doses[0]['dose_min'] == 1.0
    assert doses[0]['dose_max'] == 2.0
    assert doses[0]['dose'] == '1 - 2 gotas/olho'


def test_extrai_links_opcoes_veterinarias_do_bloco_canonico():
    html = """
    <html><body>
      <h2>OPÇÕES VETERINÁRIAS COM Cefalexina</h2>
      <div><a href="/cg/produto/1698/cefex">Cefex®</a></div>
      <div><a href="/CG/produto/170/petsporin">PetSporin</a></div>
      <div><a href="/cg/produto/2004/cefalexina">Cefalexina</a></div>
      <h2>Monitoramento</h2>
      <div><a href="/cg/produto/170/petsporin">PetSporin</a></div>
      <a href="/blog/post">Blog</a>
    </body></html>
    """
    links = scraper._extrair_links_opcoes_veterinarias(html, excluir_pid=2004)
    assert [l["id"] for l in links] == [1698, 170]
    assert [l["nome"] for l in links] == ["Cefex®", "PetSporin"]


def test_coletar_links_produto_html_dedupa_ids():
    html = """
    <html><body>
      <a href="/cg/produto/1698/cefex">Cefex®</a>
      <a href="/cg/produto/1698/cefex">Cefex®</a>
      <a href="/cg/produto/4888/falexyl">Falexyl</a>
    </body></html>
    """
    links = scraper._coletar_links_produto_html(html)
    assert [l["id"] for l in links] == [1698, 4888]


def test_extrair_secao_indicacoes_contraindicacoes_com_subtitulos():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info">
          <h2>Indicações</h2>
          <p>Controle da dor aguda; controle da febre.</p>
          <h3>Contraindicações</h3>
          <ul><li>Não usar em gestantes.</li><li>Evitar em nefropatas.</li></ul>
          <h3>Advertências</h3>
          <p>Monitorar hidratação.</p>
          <h3>Efeitos adversos</h3>
          <p>Vômito, diarreia.</p>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_indicacoes_contraindicacoes(soup.div)
    assert "Controle da dor aguda" in secao["indicacoes"]["itens"][0]
    assert "gestantes" in " ".join(secao["contraindicacoes"]["itens"]).lower()
    assert secao["contraindicacoes"]["resumo"]
    assert secao["advertencias"]["itens"] == ["Monitorar hidratação"]
    assert secao["efeitos_adversos"]["itens"] == ["Vômito, diarreia"]


def test_extrair_secao_indicacoes_contraindicacoes_com_texto_corrido():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info">
          <p>Indicações: Otites e dermatites. Contraindicações: Não usar em felinos.
          Advertências: Usar com cautela em nefropatas.</p>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_indicacoes_contraindicacoes(soup.div)
    assert "Otites e dermatites" in " ".join(secao["indicacoes"]["itens"])
    assert "felinos" in " ".join(secao["contraindicacoes"]["itens"]).lower()
    assert "nefropatas" in " ".join(secao["advertencias"]["itens"]).lower()


def test_extrair_secao_indicacoes_reclassifica_frases_misturadas():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info">
          <p>Indicações: Controle da dor. Não usar em gestantes. Pode causar vômito transitório.
          Usar com cautela em nefropatas.</p>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_indicacoes_contraindicacoes(soup.div)
    assert "Controle da dor" in " ".join(secao["indicacoes"]["itens"])
    assert "gestantes" in " ".join(secao["contraindicacoes"]["itens"]).lower()
    assert "vômito" in " ".join(secao["efeitos_adversos"]["itens"]).lower()
    assert "nefropatas" in " ".join(secao["advertencias"]["itens"]).lower()


def test_extrair_secao_interacoes_em_lista():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info interaction">
          <ul>
            <li>Fenobarbital: monitorar resposta clínica e ajustar dose.</li>
            <li>Diuréticos - usar com cautela.</li>
          </ul>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_interacoes(soup.div)
    assert [item["agente"] for item in secao["itens"]] == ["Fenobarbital", "Diuréticos"]
    assert secao["itens"][0]["conduta"] == "Ajustar dose"
    assert secao["itens"][1]["grau"] == "Moderada"


def test_extrair_secao_interacoes_descarta_metadados_soltos():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info interaction">
          <p>Tipo de interação - Sinergismo</p>
          <p>Grau de interação - Moderado</p>
          <p>Conduta - monitorar</p>
          <p>Fenobarbital: monitorar resposta clínica e ajustar dose.</p>
          <p>O Aplicativo Vetsmart contém informações de interação medicamentosas em geral.</p>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_interacoes(soup.div)
    assert len(secao["itens"]) == 1
    assert secao["itens"][0]["agente"] == "Fenobarbital"


def test_extrair_secao_interacoes_interaction_wrap():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info interaction">
          <div class="interaction-wrap">
            <h2>Anticoagulantes</h2>
            <p><b>Tipo de interação</b> - Sinergismo/Antagonismo</p>
            <p><b>Grau de interação</b> - Moderado</p>
            <p><b>Efeito Clínico</b> - Efeito terapêutico aumentado.</p>
            <p><b>Conduta</b> - Ajustar dose</p>
          </div>
          <h2 class="interactions-warning">Aviso Legal - Interações Medicamentosas</h2>
          <p>O Aplicativo Vetsmart contém informações...</p>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_interacoes(soup.div)
    assert len(secao["itens"]) == 1
    assert secao["itens"][0]["agente"] == "Anticoagulantes"
    assert secao["itens"][0]["grau"] == "Moderado"
    assert secao["itens"][0]["conduta"] == "Ajustar dose"
    assert "Efeito clínico" in secao["itens"][0]["descricao"]


def test_extrair_secao_interacoes_disabled_retorna_vazio():
    soup = scraper.BeautifulSoup(
        """
        <div class="content-comercial-info interaction">
          <p class="disabled">Este produto não contém interações medicamentosas.</p>
        </div>
        """,
        "html.parser",
    )
    secao = scraper._extrair_secao_interacoes(soup.div)
    assert secao["itens"] == []
    assert secao["texto"] is None
