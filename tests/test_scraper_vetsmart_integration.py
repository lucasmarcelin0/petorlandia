"""Teste de integração do parser: rodar `extrair_produto_do_html` contra HTML
sintético que imita a estrutura da página da Prednisona no VetSmart.

Isso é um "golden test": se a estrutura da VetSmart mudar ou o parser regredir,
esse teste falha e aponta exatamente qual campo ficou errado. Mais valioso que
testar o HTML em si é testar o contrato dos dados que nos interessam:
principio_ativo, apresentações (com concentração numérica), e doses estruturadas
(com indicação, intervalo_horas, duracao_min_dias).
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import importar_medicamentos_vetsmart as scraper  # noqa: E402


# HTML sintético baseado no markup real da VetSmart para Prednisona industrializada
# (comprimido 5 mg). Cobre os casos que historicamente vazaram no scraper:
#  - apresentação sem concentração no <li> (manipulado)
#  - duração embutida no texto de frequência ("por 7 dias")
#  - múltiplas indicações no mesmo protocolo (Alergia + Imunossupressão)
HTML_PREDNISONA = """
<html>
<body>
  <h2 class="side-nav-title">Prednisona LigVet</h2>
  <div class="side-nav-subtitle">POR LigVet Farmácia de Manipulação</div>

  <meta itemprop="manufacturer" content="LigVet Farmácia de Manipulação"/>
  <meta itemprop="drugClass" content="Anti-inflamatório Esteroidal"/>
  <meta itemprop="administrationRoute" content="Oral"/>
  <meta itemprop="activeIngredient" content="Prednisona"/>

  <p><b>Espécies:</b> Cães e Gatos</p>

  <section class="container-content">
    <div class="title-content">Apresentações e concentrações</div>
    <div class="content-comercial-info">
      <ul>
        <li><span itemprop="dosageForm">Comprimido</span> - 5 mg</li>
        <li><span itemprop="dosageForm">Cápsulas</span></li>
        <li><span itemprop="dosageForm">Suspensão</span></li>
      </ul>
    </div>
  </section>

  <section class="container-content">
    <div class="title-content">Administração e doses</div>
    <div class="content-comercial-info">
      <p><b>Via:</b> Oral</p>
      <p><b>Dose:</b></p>
      <ul>
        <li>Cães: 0,5 - 1 mg/kg</li>
        <li>Cães: 2 mg/kg</li>
        <li>Gatos: 1 mg/kg</li>
      </ul>
      <p><b>Frequência:</b> Alergias e imunossupressão: 12h. Dermatite atópica: 24hrs por 7 dias.</p>
    </div>
  </section>

  <section class="container-content">
    <div class="title-content">Indicações e contraindicações</div>
    <div class="content-comercial-info">
      <p>Indicações: atopia, dermatite de contato, alergias, doenças osteoarticulares,
      endocrinopatias (por exemplo: hipocortisolismo), neoplasias.</p>
    </div>
  </section>
</body>
</html>
"""


HTML_DIPIRONA = """
<html>
<body>
  <h2 class="side-nav-title">Dipirona Vet</h2>
  <div class="side-nav-subtitle">POR Vet Farma</div>
  <meta itemprop="manufacturer" content="Vet Farma"/>
  <meta itemprop="drugClass" content="Analgésico"/>
  <meta itemprop="administrationRoute" content="VO, IM"/>
  <meta itemprop="activeIngredient" content="Dipirona"/>
  <meta itemprop="warning" content="Usar com cautela em pacientes desidratados."/>
  <p><b>Espécies:</b> Cães e Gatos</p>

  <section class="container-content">
    <div class="title-content">Administração e doses</div>
    <div class="content-comercial-info">
      <p><b>Via:</b> VO, IM</p>
      <ul>
        <li>Cães: Alergia VO 0,5 - 1 mg/kg Imunossupressão IM 2 mg/kg</li>
        <li>Gatos: 1 mg/kg</li>
      </ul>
      <p><b>Frequência:</b> 12/12 horas</p>
    </div>
  </section>

  <section class="container-content">
    <div class="title-content">Indicações e contraindicações</div>
    <div class="content-comercial-info">
      <h2>Indicações</h2>
      <p>Controle da dor aguda; controle da febre.</p>
      <h2>Contraindicações</h2>
      <p>Não usar em gestantes.</p>
      <h2>Efeitos adversos</h2>
      <p>Vômito transitório.</p>
    </div>
  </section>

  <section class="container-content">
    <div class="title-content">Interações medicamentosas</div>
    <div class="content-comercial-info interaction">
      <ul>
        <li>Fenobarbital: monitorar resposta clínica e ajustar dose.</li>
        <li>Diuréticos: usar com cautela.</li>
      </ul>
    </div>
  </section>
</body>
</html>
"""


def test_prednisona_integration_parse():
    prod = scraper.extrair_produto_do_html(HTML_PREDNISONA, pid=9999, nome_fallback='?')

    # Campos principais (schema.org)
    assert prod.nome == 'Prednisona LigVet'
    assert prod.principio_ativo == 'Prednisona'
    assert prod.via_administracao == 'Oral'
    assert prod.classificacao == 'Anti-inflamatório Esteroidal'
    assert prod.fabricante == 'LigVet Farmácia de Manipulação'
    assert prod.especies == 'Cães e Gatos'


def test_prednisona_apresentacoes_nao_vazam_nome_como_concentracao():
    prod = scraper.extrair_produto_do_html(HTML_PREDNISONA, pid=9999, nome_fallback='?')

    # 3 apresentações: comprimido 5mg, cápsulas, suspensão.
    formas = [(a['forma'], a.get('concentracao_valor'), a.get('concentracao_unidade'))
              for a in prod.apresentacoes]

    # Comprimido: tem concentração numérica.
    assert ('Comprimido', 5.0, 'mg') in formas, f'Esperava Comprimido 5mg em {formas}'

    # Cápsulas e suspensão: sem número → valor None, unidade None.
    # Regressão: antes o scraper podia pegar "Prednisona LigVet" como concentração.
    capsulas = next((a for a in prod.apresentacoes if a['forma'] == 'Cápsulas'), None)
    assert capsulas is not None, 'Cápsulas não extraídas'
    assert capsulas.get('concentracao_valor') is None
    assert capsulas.get('concentracao_unidade') is None
    # Também não pode vazar nome como texto de concentração.
    assert 'Prednisona' not in (capsulas.get('concentracao') or '')


def test_prednisona_indicacoes_extraidas():
    """As indicações da página devem ser preservadas no texto bruto e,
    quando passadas ao _extrair_indicacao, resolvidas nas canônicas."""
    prod = scraper.extrair_produto_do_html(HTML_PREDNISONA, pid=9999, nome_fallback='?')
    assert prod.indicacoes is not None
    # Cobertura: ao menos uma das indicações esperadas está no texto bruto.
    txt = prod.indicacoes.lower()
    assert 'atopia' in txt
    assert 'osteoarticulares' in txt
    assert 'endocrinopatias' in txt
    assert 'neoplasias' in txt

    # E o extrator reconhece cada uma das canônicas quando passado trechos.
    # (O mapeamento dose→indicação é coberto nos testes unitários; aqui
    # validamos só que o texto-fonte chegou completo ao produto.)
    assert scraper._extrair_indicacao('atopia') == 'Dermatite atópica'
    assert scraper._extrair_indicacao('doenças osteoarticulares') == 'Osteoarticular'
    assert scraper._extrair_indicacao('endocrinopatias') == 'Endocrinopatia'
    assert scraper._extrair_indicacao('neoplasias') == 'Neoplasia'


def test_refino_indicacao_corticoide_prioriza_contexto_clinico():
    assert scraper._refinar_indicacao_dose(
        'Uso prolongado',
        linha='Manutenção hipoadrenocortical: 0,2 a 0,4 mg/Kg em dias alternados',
        seg_txt='Manutenção hipoadrenocortical: 0,2 a 0,4 mg/Kg em dias alternados',
        frequencia_texto='em dias alternados (48h)',
        duracao_texto=None,
        indicacoes_texto='Indicado para endocrinopatias e dermatites alérgicas.',
        classificacao='Anti-inflamatório Esteroidal',
    ) == 'Hipoadrenocorticismo'

    assert scraper._refinar_indicacao_dose(
        'Anti-inflamatório',
        linha='Processos alérgicos: 1 mg/Kg a cada 12 horas',
        seg_txt='Processos alérgicos: 1 mg/Kg a cada 12 horas',
        frequencia_texto='12/12 horas',
        duracao_texto=None,
        indicacoes_texto='Indicado para dermatites alérgicas.',
        classificacao='Anti-inflamatório Esteroidal',
    ) == 'Alergia'


def test_pos_processar_doses_descarta_comprimido_ambiguo_sem_forca():
    doses = [{
        'dose': '1 comprimido/animal',
        'dose_raw_text': '1 comprimido / animal',
        'dose_unidade': 'COMPRIMIDOS_ANIMAL',
        'observacao': None,
    }]
    apresentacoes = [
        {'forma': 'comprimido', 'concentracao_valor': 5.0, 'concentracao_unidade': 'mg'},
        {'forma': 'comprimido', 'concentracao_valor': 20.0, 'concentracao_unidade': 'mg'},
    ]

    saida = scraper._pos_processar_doses_por_apresentacao(doses, apresentacoes)

    assert saida == []


def test_pos_processar_doses_enriquece_comprimido_quando_ha_forca_unica():
    doses = [{
        'dose': '1 comprimido/animal',
        'dose_raw_text': '1 comprimido / animal',
        'dose_unidade': 'COMPRIMIDOS_ANIMAL',
        'observacao': None,
    }]
    apresentacoes = [
        {'forma': 'comprimido', 'concentracao_valor': 20.0, 'concentracao_unidade': 'mg'},
    ]

    saida = scraper._pos_processar_doses_por_apresentacao(doses, apresentacoes)

    assert len(saida) == 1
    assert '20 mg' in saida[0]['dose']


def test_dipirona_gera_conteudo_estruturado_v3():
    prod = scraper.extrair_produto_do_html(HTML_DIPIRONA, pid=10001, nome_fallback='?')
    conteudo = prod.conteudo_estruturado

    assert conteudo["metadata"]["parser_version"] == "v3"
    assert conteudo["metadata"]["fonte"] == "vetsmart"
    assert conteudo["indicacoes"]["itens"] == ["Controle da dor aguda", "controle da febre"]
    assert "gestantes" in " ".join(conteudo["contraindicacoes"]["itens"]).lower()
    assert conteudo["interacoes"]["itens"][0]["agente"] == "Fenobarbital"
    assert conteudo["interacoes"]["itens"][0]["conduta"] == "Ajustar dose"
    assert "desidratados" in " ".join(conteudo["advertencias"]["itens"]).lower()
    assert "raw_sections_html" in conteudo
    assert "<ul>" in conteudo["raw_sections_html"]["Interações medicamentosas"]
    assert "Fenobarbital" in conteudo["raw_sections_html"]["Interações medicamentosas"]


def test_dipirona_doses_multiplas_indicacoes_na_mesma_linha():
    prod = scraper.extrair_produto_do_html(HTML_DIPIRONA, pid=10001, nome_fallback='?')
    doses_caes = [dose for dose in prod.doses if dose["especie_code"] in {"CAES", "AMBOS"}]
    indicacoes = [dose["indicacao"] for dose in doses_caes]
    assert "Alergia" in indicacoes
    assert "Imunossupressão" in indicacoes
