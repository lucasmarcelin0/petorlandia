# Dados entomológicos e censitários

A página `/sfa/entomologia` usa a mesma autorização interna do SFA. O acesso na
barra lateral fica depois de Ações, antes do rodapé SFA. Possui cinco abas:
Equipe, Planejamento, Entomologia, Censo 2022 e Mapas de campo. Não consulta dados dos participantes.
A aba Equipe, a atualização pelo navegador e a página pública `/aedes` estão
descritas em [entomologia_evolucao.md](entomologia_evolucao.md).

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

## Atualizar os dados pelo navegador

O caminho do dia a dia é `/sfa/entomologia/atualizar`: envio do CSV/ZIP, prévia
por dia, confirmação com responsável e opção de desfazer. Os envios ficam na
tabela `entomologia_importacao` e substituem, na base consolidada, os dias que
contêm; a fotografia abaixo continua sendo a base e não é alterada pelo servidor.

## Atualizar a fotografia dos dados

A fotografia versionada não depende do banco. `services/data/entomologia/snapshot.json`
e `maps/` acompanham o código; as rotas protegidas servem os dados e as imagens.
Nenhum download externo é feito pelo servidor em cada acesso. O navegador usa
Esri World Street Map para o fundo de ruas; os limites e indicadores funcionam sem esse
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


## Atlas integrado de campo (30/09/2026)

A visão inicial **Mapa integrado** reúne as 946 geometrias de quadras da camada
Quadras de `Copy of Cópia de 2026.kml`, organizadas em 72 códigos SC e nove áreas.
O GeoJSON versionado fica em `services/data/entomologia/territory.json`, servido
pela rota interna `/sfa/entomologia/territorio.json`. O arquivo bruto não é
publicado: apenas polígonos, códigos, áreas, IDs de origem e informações de
conferência. Pontos de casos, descrições, HTML e outras camadas são excluídos.

As coordenadas são preservadas sem simplificação, deslocamento ou ajuste ao
satélite. Shapely é usado somente na preparação para calcular rótulos no interior
dos polígonos. Uma geometria irregular e uma chave setor/quadra repetida são
sinalizadas; não se corrige nem se descarta a geometria original. A grafia
SC 0102 da fonte é preservada. Quadras com sufixos (899A–F, 900A–F) permanecem
distintas. A correspondência com as 14 folhas em papel e com a malha IBGE exige
conferência municipal; não houve georreferenciamento das imagens nem levantamento
cadastral. Nenhuma precisão métrica é presumida da imagem de satélite.

A busca aceita código exato de quadra, SC ou nome da área. No zoom da cidade,
rótulos mostram setores; no zoom 16 ou maior, mostram quadras. A posição usa um
ponto interior e uma verificação de colisão em pixels, recalculada ao mover,
ampliar ou redimensionar. A seleção de uma quadra apresenta apenas registros
candidatos com os mesmos códigos, sem validar o vínculo ou atribuir visitas
automaticamente. A camada IBGE é separada e opcional. Os mapas originais continuam
na própria visão, em uma seção recolhível com 14 miniaturas e zoom.

O atlas usa Esri World Imagery por padrão e Esri World Street Map como alternativa
de ruas. Após três erros na camada ativa, remove o fundo antes de tentar a
alternativa; se ambas falham, mantém quadras, números e controles sobre base limpa.
A base de ruas foi conferida visualmente: a alternativa CARTO exigia chave
e exibia uma marca d’água, conforme a [regra atual do provedor](https://carto.com/basemaps/apikey/),
e foi substituída por Esri World Street Map.
Não há chamadas a tile.openstreetmap.org: a política no-referrer do painel
conflitava com a [exigência de Referer daquele serviço](https://operations.osmfoundation.org/policies/tiles/). A política de privacidade
do painel e das imagens internas permanece no-referrer. As atribuições dos
provedores e escala métrica são exibidas. Entomologia e Censo também usam o novo
fundo de ruas. Leaflet, geometrias e rótulos são locais; imagens de fundo exigem
conectividade e disponibilidade dos provedores.

Preparar uma nova versão (Shapely é dependência de preparação, não do servidor):

```powershell
python scripts/prepare_entomologia_territory.py "C:/caminho/copia-do-mapa.kml"
node tests/test_field_map_model.js
node tests/test_sfa_map_layers.js
```

O atlas é a visão inicial. Equipe, Planejamento, Entomologia, Censo e atualização de dados permanecem disponíveis. Camadas enviadas pela equipe podem ser ativadas no atlas e continuam na visão de visitas. O território é servido pela mesma autorização do painel, com cache privado e no-referrer.


## Camadas operacionais e fonte Arboviroses (30/09/2026)

O painel de camadas do atlas consulta sob demanda um projeto completo KML/KMZ,
enviado em **Atualizar dados → Projeto completo do Google Earth**, com prévia,
confirmação, autoria, auditoria e opção de desfazer. A fotografia redigida fica
no banco `EntomologiaImportacao`, tipo `atlas_earth`; nunca no Git ou no HTML
inicial. A última fotografia ativa vence; desfazê-la restaura a anterior.
As quadras continuam na base territorial validada separadamente.

As camadas Rotina, Mutirão, Casos Dengue, Larvas e Atendimentos têm controles
independentes, enquadramento, subcamadas e filtro de mês das pastas. Nomes de
marcadores e descrições livres são descartados; permanecem geometria original,
categoria operacional, mês, rótulo da pasta, identificador técnico e eventual
número SINAN explicitamente rotulado. O mês não é uma data exata de ocorrência.
Novas alterações no Earth exigem uma nova exportação e envio; a data visível é
de importação, não de atualização automática do projeto remoto.

Pontos próximos de todas as fontes ativas são agrupados pelo espaço disponível
na tela. A posição do agrupamento é um ponto original, sem média geográfica ou
deslocamento dos dados. Os anéis mostram a proporção das camadas, e o clique
abre a composição e os elementos; duplo clique aproxima. Agrupamentos e rótulos
de quadra reservam espaço entre si. Contagens são elementos do arquivo, não
pessoas, imóveis ou visitas únicos; fontes não são deduplicadas por proximidade.

A planilha fornecida (`15UdUxNhuL3VUNpJr_iEiiWTVM-rlKtVcGPeY9jSFJ_E`,
gid `1339975360`) é lida pelo servidor com as credenciais Google existentes do
SFA, escopo somente leitura, ao ativar **Registros da planilha**. A consulta tem
cache de 90 segundos e atualização manual. O gid, os cabeçalhos utilizados e o
limite de 10 mil linhas são conferidos antes da leitura. Essa consulta não
executa a sincronização SINAN nem cria pacientes, ações ou notificações.

O atlas recebe somente linha de origem, chave SINAN, agravo, datas de notificação
e sintomas, exame, resultado, resultado final e classificação. Nome, endereço,
telefone, nascimento e campos livres não são enviados ao atlas. Uma geometria
só é atribuída se houver exatamente uma linha e um ponto clínico do Earth com
o mesmo SINAN explícito. Duplicatas e ausência de chave ficam sem posição, em
lista filtrável com acesso a todas as linhas e link para a fonte. Não há
geocodificação de endereços ou correspondência por nome.

Todas as rotas são internas, com `private, no-store` e `no-referrer`.
Casos Dengue e a consulta da planilha exigem o acesso completo já existente do
SFA. O papel adicional Combate à dengue recebe somente as camadas operacionais.
A indisponibilidade de uma fonte não remove as outras camadas ou o território.


## Editor compartilhado do atlas (1º de outubro de 2026)

O botão **Editar atlas** abre a tabela da camada selecionada. A equipe pode
criar, duplicar e renomear camadas, escolher sua cor, cadastrar e corrigir
registros, mover pontos, desenhar trajetos e polígonos, excluir dados incorretos
e exportar a tabela CSV ou a geometria GeoJSON. Registros sem posição confirmada
ficam na tabela, sem receber coordenadas estimadas.

As edições usam o banco do atlas. Não escrevem na planilha Google nem no projeto
Earth. O comando **Copiar planilha**, exclusivo de administradores identificados,
cria uma fotografia dos campos estruturados da consulta (sem nomes, telefones,
datas de nascimento ou endereços pessoais da fonte). Essa cópia pode ser editada
e posicionada no atlas; a consulta ao vivo da fonte continua separada.

Cada gravação registra a conta, o horário, o motivo e a versão anterior em
`entomologia_importacao`, tipo `atlas_edit`, e na auditoria SFA. A exclusão é
recuperável. Restaurar uma versão cria outra revisão e preserva a atual. O
histórico exibe as 100 revisões mais recentes; as demais continuam no banco.
As fontes originais permanecem intactas. Alterações locais em camadas Earth
prevalecem sobre novas importações até restaurar a fonte original.

Escritas exigem conta identificada, CSRF e o papel já existente de administrador
ou Combate à dengue. Camadas clínicas só podem ser editadas por administradores.
Um token de consulta não autoriza gravações. A versão enviada pelo formulário
deve coincidir com a atual; conflito retorna 409, preservando o formulário.
Um bloqueio transacional PostgreSQL serializa gravações, inclusive a primeira
edição de uma camada da fonte, entre threads e dynos. O histórico do editor não
pode ser alterado pelas rotas antigas de confirmação/desfazer importação.

A busca consulta somente o atlas e a referência urbana local OpenStreetMap.
Nenhum termo de busca ou endereço é transmitido a um geocodificador externo.
Nomes numéricos e por extenso são conciliados (Rua 2 / Rua Dois); trechos da mesma
via são reunidos para consulta. Um trecho de rua não localiza automaticamente
o número de um imóvel. Endereços e entradas precisam ser conferidos no campo.
O recorte OSM de 1º/10/2026 tem 1.197 geometrias de vias nomeadas e 69 equipamentos
ou parques. Cobertura e nomes seguem a fonte; não constituem cadastro oficial
completo. Licença ODbL e atribuição OpenStreetMap aparecem no mapa.

Os dois PDFs fornecidos ficam em rotas protegidas de consulta, preservados byte
por byte e identificados pelo SHA-256 no manifesto. O mapa de imóveis públicos
traz referência 2017/2018; o arquivo da base urbana foi atualizado em 2025, com
escala 1:10.000. A medida de desenho `/RL` do PDF urbano não é uma transformação
geográfica. Nenhuma folha foi esticada ou sobreposta ao satélite sem validação
de pontos de controle. A base das quadras e os limites IBGE permanecem referências
territoriais separadas do editor de registros.
