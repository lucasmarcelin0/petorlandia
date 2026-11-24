# Vídeos curtos da vacinação antirrábica (até 90 s cada)

Substituem o vídeo único de 6 minutos na página do link do tutor
(`/vacina-pmo/c/<token>`). Cada vídeo trata de **um** assunto e cabe em
até 90 segundos (~180 palavras faladas, em ritmo calmo).

## Como gravar

- Celular na **vertical** (9:16), publicado como YouTube Shorts **não listado**.
  A página aceita links `youtube.com/shorts/...`, `youtu.be/...` e `watch?v=`.
- Quem fala: alguém da equipe da Vigilância, de uniforme, em local real
  (sala da VISA, rua de bairro, carro da campanha). Rosto conhecido gera confiança.
- Legenda queimada no vídeo (muita gente assiste sem som) e o telefone
  **(16) 3820-8207** e o WhatsApp **(16) 99971-2712** na tela nos últimos 10 segundos dos vídeos 2 e 3.
- Nada de imagem de animal doente ou de pessoa com raiva: o tom é de cuidado,
  não de medo.
- Revisar os números com a fonte antes de gravar (ver "Fontes" no fim).

## Como publicar na página

Configurar no Heroku a variável `PMO_VACCINE_EDUCATIONAL_VIDEOS`, uma linha
por vídeo (ou separadas por `;`), no formato `Título | link`:

```
Parabéns, seu pet está protegido | https://youtube.com/shorts/AAAA
Viu um morcego? Não toque | https://youtube.com/shorts/BBBB
Mordida ou arranhão: o que fazer | https://youtube.com/shorts/CCCC
Raiva hoje: por que ainda vacinar | https://youtube.com/shorts/DDDD
```

Enquanto a variável estiver vazia, a página continua mostrando o vídeo longo
atual (`PMO_VACCINE_EDUCATIONAL_VIDEO_URL`). Vídeos podem entrar aos poucos:
com 1 ou 2 configurados, só eles aparecem.

---

## Vídeo 1 — "Parabéns, seu pet está protegido" (~60 s)

**Objetivo:** agradecer, explicar o que a vacina faz e o que observar depois.

| Tempo | Imagem | Fala |
|---|---|---|
| 0–8 s | Equipe acenando na rua, cão recebendo a vacina | "Parabéns! Seu cão ou gato acabou de ser vacinado contra a raiva." |
| 8–25 s | Close da carteirinha no celular | "A vacina protege por um ano. A carteirinha digital fica neste link: guarde, ela vale como comprovante." |
| 25–45 s | Animal descansando | "Hoje ele pode ficar mais quietinho ou com o local da vacina sensível. Isso passa em um ou dois dias. Inchaço grande, vômito ou falta de ar: procure um veterinário." |
| 45–60 s | Texto "Reforço: daqui a 1 ano" | "Daqui a um ano, vacine de novo. Cada animal vacinado protege a sua família e os vizinhos." |

## Vídeo 2 — "Viu um morcego? Não toque" (~75 s)

**Objetivo:** hoje o morcego é a principal fonte de raiva em cidades de SP.

| Tempo | Imagem | Fala |
|---|---|---|
| 0–10 s | Forro/telhado, morcego em foto de arquivo (sem manuseio) | "Morcego é importante para a natureza, mas pode transmitir raiva. E em 2026 já apareceram morcegos com raiva em várias cidades do interior paulista." |
| 10–30 s | Texto: "caído • voando de dia • dentro de casa" | "Morcego caído no chão, voando de dia ou dentro de casa pode estar doente." |
| 30–55 s | Mão colocando balde sobre um objeto (sem morcego real) | "Não pegue, nem com luva. Afaste crianças, cães e gatos. Se der, cubra com um balde ou caixa sem encostar e feche o cômodo." |
| 55–75 s | Telefone grande na tela | "Ligue para a Vigilância Sanitária de Orlândia, (16) 3820-8207, ou mande uma foto pelo WhatsApp, (16) 99971-2712. A gente busca o morcego e manda para exame." |

## Vídeo 3 — "Mordida ou arranhão: o que fazer" (~80 s)

**Objetivo:** atendimento rápido da pessoa e vacina humana gratuita no SUS.

| Tempo | Imagem | Fala |
|---|---|---|
| 0–12 s | Pia, mãos sob a torneira com sabão | "Foi mordido ou arranhado por cão, gato, ou teve contato com morcego ou sagui? Primeiro passo: lave o local com bastante água e sabão, na hora." |
| 12–35 s | Fachada de unidade de saúde / pronto-socorro | "Depois, procure no mesmo dia o pronto-socorro ou a unidade de saúde. Não espere doer, inflamar ou aparecer sintoma." |
| 35–60 s | Frasco de vacina humana, profissional de saúde | "Existe vacina contra a raiva para pessoas, e o SUS oferece de graça. Em alguns casos também é usado o soro. Quem decide é a equipe de saúde, avaliando o ferimento e o animal." |
| 60–80 s | Texto + telefone | "Se o animal for seu ou de um vizinho, não sacrifique nem abandone: ele precisa ser observado. A Vigilância orienta: (16) 3820-8207 ou WhatsApp (16) 99971-2712." |

> Conferir com a Vigilância Epidemiológica municipal qual unidade atende a
> profilaxia em Orlândia e, se for o caso, citar o nome dela neste vídeo.

## Vídeo 4 — "Raiva hoje: por que ainda vacinar" (~85 s)

**Objetivo:** dados atuais, sem alarmismo, para quem pergunta "ainda existe raiva?".

| Tempo | Imagem | Fala |
|---|---|---|
| 0–15 s | Gráfico simples em animação | "Ainda existe raiva? Existe. No mundo, a OMS estima dezenas de milhares de mortes por ano, quase sempre por mordida de cão não vacinado, na Ásia e na África." |
| 15–40 s | Mapa do Brasil | "No Brasil, a vacinação funcionou: em 2026 completamos 10 anos sem nenhum caso humano transmitido por cão." |
| 40–65 s | Morcego / sagui (fotos de arquivo) | "Mas o vírus continua circulando em animais silvestres. De 2010 a 2026 foram 54 casos humanos no país, e 23 deles vieram de morcegos. Em 2025, os 4 casos foram por contato com macacos." |
| 65–85 s | Volta à equipe na rua | "Por isso vacinamos todo ano: se um morcego doente encontrar seu cão ou gato vacinado, a raiva para ali. Obrigado por proteger Orlândia." |

---

## Fontes (revisadas em 24/11/2026)

- Ministério da Saúde — Raiva humana: <https://www.gov.br/saude/pt-br/assuntos/saude-de-a-a-z/r/raiva/raiva-humana>
  (54 casos de 2010 a 2026, 23 por morcegos; 4 casos em 2025, por primatas;
  1 caso em 2026 no Piauí até junho; atualizado em 11/06/2026).
- Agência Gov, ago/2026 — 10 anos sem raiva humana transmitida por cães:
  <https://agenciagov.ebc.com.br/noticias/202608/brasil-completa-10-anos-sem-raiva-humana-transmitida-por-caes-e-reforca-vacinacao-antirrabica-na-fronteira>
- Band, ago/2026 — morcegos com raiva em cidades de SP:
  <https://www.band.com.br/saude/casos-de-raiva-em-morcegos-urbanos-e-rebanhos-bovinos-disparam-em-sp-e-sc>
- OMS — Rabies fact sheet: <https://www.who.int/news-room/fact-sheets/detail/rabies>
