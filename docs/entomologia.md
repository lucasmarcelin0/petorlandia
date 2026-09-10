# Dados entomológicos e censitários

A página `/sfa/entomologia` usa a mesma autorização interna do SFA. O acesso na
barra lateral fica depois de Ações, antes do rodapé SFA. Possui quatro abas:
Planejamento, Entomologia, Censo 2022 e Mapas de campo. Não consulta dados dos participantes.

## Fontes e recorte entregue

- `Dados.zip / Visita a Imóvel.csv`: 2.371 registros de 05/01 a 08/09/2026,
  72 códigos censitários, área operacional 1. Arquivo com preâmbulo, separador
  ponto e vírgula e codificação Windows-1252. O importador também aceita UTF-8.
- [IBGE, setores com atributos 2022 de SP](https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/malha_com_atributos/setores/shp/UF/SP/SP_setores_CD2022.zip):
  seleção por `CD_MUN = 3534302`, 78 setores, coordenadas geográficas SIRGAS 2000.
- [Dicionário da malha com atributos](https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/malha_com_atributos/Dicionario_de_dados_malha_agregados.xlsx):
  V0001 = pessoas; V0002 = domicílios totais; V0007 = domicílios particulares
  ocupados; V0005 = média de moradores em domicílios particulares ocupados.
- 13 imagens de campo e `MAPA VETORES 2018.pdf` do ZIP, convertidos em 14
  imagens de consulta com até 3.600 pixels por dimensão. A numeração operacional
  desses mapas não foi associada automaticamente aos setores do IBGE.

Hashes SHA-256 das fontes tabulares e da malha estão no `source` do snapshot.
Nenhuma instrução eventualmente contida nos anexos foi usada como comando.
Os mapas não foram georreferenciados manualmente, e não há pontos inventados.

## Semântica e conferência

Uma linha representa um registro do relatório de visitas; não é um imóvel único.
Somas podem conter revisitas. O campo ID não permite deduplicação confiável.
Uma linha repetida após a remoção de identificadores foi mantida; todas as linhas
da fonte foram conservadas. LOGIN e AGENTE não são incluídos no snapshot.

Conferência do recorte: 16.507 imóveis trabalhados, 215 ocorrências de imóveis com
larvas, 61 com A. aegypti, 1 com A. albopictus, 422 larvas de A. aegypti, 13.571
imóveis fechados e 1.207 recusas. Há 422 registros com IM. LARVA preenchido e
1.949 sem informação (vazio não equivale a zero). O preenchimento é calculado por
registro, não por imóvel. Não se calculam IIP, Breteau, incidência ou correlações.

As somas de larvas mostram valores conhecidos; se todos forem vazios, o resultado
fica indisponível. Períodos sem registros não viram zeros na série temporal.
Os filtros são inclusivos nas duas datas e se aplicam a todos os indicadores,
mapa, gráficos, tabela paginada e CSV da aba Entomologia. A legenda do mapa usa
apenas os setores mapeáveis. O Censo tem seleção territorial própria e ano fixo.

43 registros correspondem a 5 códigos ausentes na malha: `353430205000050`,
`353430205000072`, `353430205000075`, `353430205000098`, `353430205000108`.
Esses registros permanecem na análise e podem ser isolados por Localização.
Mesmo os códigos coincidentes representam uma associação exploratória: validar
a versão do cadastro operacional e as mudanças de limites antes de cruzamentos
espaciais ou correlações. Os mapas de campo não são a malha censitária.

Totais do arquivo censitário recortado: 38.319 pessoas, 15.334 domicílios totais
e 13.566 domicílios particulares ocupados. São os atributos da malha 2022
selecionada, não estimativas populacionais de 2026. Não são denominadores de
visitas. Densidade é população / área em km². Dados censitários ausentes não
seriam convertidos em zero; totais incompletos ficam indisponíveis.

## Atualizar a fotografia dos dados

Não há gravação no banco nem migração. `services/data/entomologia/snapshot.json`
e `maps/` acompanham o código; as rotas protegidas servem os dados e as imagens.
Nenhum download externo é feito pelo servidor em cada acesso. O navegador usa
OpenStreetMap para o fundo de ruas; os limites e indicadores funcionam sem esse
fundo. Leaflet e o código dos gráficos são locais.

Para substituir a exportação, use o ambiente de desenvolvimento com `pyshp`:

```powershell
python scripts/import_entomologia.py "C:/caminho/Dados.zip" "C:/caminho/SP_setores_CD2022.zip"
```

Para atualizar os mapas, use Pillow e pypdfium2 (somente na preparação):

```powershell
python scripts/prepare_entomologia_maps.py "C:/caminho/Dados.zip"
```

O importador valida cabeçalhos, datas, município, valores e projeção, escreve um
arquivo temporário e substitui o snapshot somente após concluir. Não extrai
diretórios arbitrários do ZIP. Reinicie os processos Flask depois de atualizar
para invalidar o cache em memória. Não envie os ZIPs brutos ao repositório.

Antes de publicar, confira os novos totais e atualize as expectativas de teste
da fotografia conscientemente. Testes:

```powershell
node tests/test_entomologia_model.js
python -m pytest tests/test_entomologia.py tests/test_sfa_security.py tests/test_sfa_analysis_route.py tests/test_url_map_contract.py -q
```

O CSV exporta todas as linhas do recorte, inclusive além da página visível; vazios
continuam vazios. A exportação é processada localmente no navegador.
## Planejamento operacional

A aba inicial Planejamento permite janelas inclusivas de 7, 14 e 28 dias, ancoradas por padrão na última data do arquivo. Compara com a janela imediatamente anterior de igual duração e sinaliza intervalos não cobertos pela fonte. Os filtros são independentes da exploração entomológica.

Há listas separadas de focos registrados, dificuldades de acesso e incompletude, por setor ou pela chave área–setor–quarteirão. A tela exibe até 20 candidatos; o CSV inclui todos os candidatos e as datas de ambas as janelas. A lista não estima risco nem informa se a ocorrência continua pendente. O botão “Ver registros” abre o recorte correspondente em Entomologia.

O estudo [plano_vigilancia_orlandia.md](plano_vigilancia_orlandia.md) documenta os achados, programas sugeridos, indicadores e integrações necessárias. A [auditoria reproduzível](analises/planejamento_orlandia.ipynb) confere as contagens em Python, independentemente do modelo JavaScript. Suas cinco células foram executadas sequencialmente e salvas com saída, usando Python sem kernel Jupyter; o formato recebeu verificações estruturais locais. Para reexecutar em Jupyter, abra o notebook na raiz do projeto ou em seu diretório.
