# Migração VetSmart → Petorlandia

Guia consolidado com todas as melhorias implementadas.

---

## Migração nova (sistema limpo)

```bash
python scripts/migrate_vetsmart.py --only-import
```

O script pergunta interativamente:
1. **Qual clínica** recebe os dados (lista todas as clínicas do banco)
2. **Qual veterinário** assina as consultas e vacinas importadas

Selecione a clínica correta e confirme — tudo é importado em uma única passagem.

---

## Migração com extração HTTP (dados ainda no VetSmart)

```bash
python scripts/migrate_vetsmart.py
```

Fluxo automático:
- Se há checkpoints em `scripts/vetsmart_raw/` → pergunta se reutiliza ou reextrai
- Se não há checkpoints → extrai do servidor Parse do VetSmart e importa

---

## Migração via JSON exportado (recomendado quando há Cloudflare)

```bash
python scripts/exportar_clientes_vetsmart.py   # gera o JSON via browser
python scripts/migrate_vetsmart.py --from-json vetsmart_tutores_animais.json
```

---

## O que é importado (e o que foi corrigido)

### Tutores
| Campo VetSmart | Campo Petorlandia | Status |
|---|---|---|
| `name` | `User.name` | ✅ |
| `cpf` | `User.cpf` | ✅ |
| `email` | `User.email` (com deduplicação) | ✅ |
| `phone` | `User.phone` | ✅ |
| `birthdate` | `User.date_of_birth` | ✅ corrigido |
| `rg` | `User.rg` | ✅ corrigido |
| `addressStreet` + `addressNumber` + `neighborhood` + `city` + `stateId` + `zipCode` + `addressComplement` | `User.address` (string) + `Endereco` (estruturado) | ✅ corrigido |

### Animais
| Campo VetSmart | Campo Petorlandia | Status |
|---|---|---|
| `name` / `specie` / `breed` / `gender` | `Animal.name/sex/species/breed` | ✅ |
| `birthdate` / `microchip` / `peso` | campos correspondentes | ✅ |
| `castrated` | `Animal.neutered` | ✅ |
| `deceased` | `Animal.is_alive` + `Animal.status` | ✅ corrigido (antes sempre `True`) |
| `temperament` + `pelage` + `size` + `notes` + `allergies` + `otherInfo` | `Animal.description` | ✅ corrigido |

### Prescrições
| Campo VetSmart | Campo Petorlandia | Status |
|---|---|---|
| Cada receita (`objectId`) | `BlocoPrescricao` (agrupa os medicamentos) | ✅ corrigido |
| `drugs[].drug` + `dosageForm` | `Prescricao.medicamento` ("Amoxicilina – 500mg, comprimido") | ✅ corrigido |
| `drugs[].dosage` | `Prescricao.dosagem` | ✅ |
| `drugs[].dosageData.interval` + `intervalUnit` | `Prescricao.frequencia` ("A cada 12 Horas") | ✅ corrigido (antes vazio) |
| `drugs[].dosageData.duration` + `durationUnit` | `Prescricao.duracao` ("7 Dias") | ✅ corrigido (antes vazio) |
| `drugs[].usage` | `Prescricao.observacoes` ("Via: Oral") | ✅ corrigido |
| `notes` (da receita) + `prescriptionType=1` | `BlocoPrescricao.instrucoes_gerais` | ✅ corrigido |

### Vacinas
| Campo VetSmart | Campo Petorlandia | Status |
|---|---|---|
| `vaccine` / `vaccineType` | `Vacina.nome` + `Vacina.tipo` | ✅ corrigido |
| `isReminder=true` | `Vacina.aplicada = False` (agendamento futuro) | ✅ corrigido (antes sempre `True`) |
| `currentShot` / `totalShots` | `Vacina.observacoes` ("Dose 1 de 3") | ✅ corrigido |

### Consultas
| Campo VetSmart | Campo Petorlandia | Status |
|---|---|---|
| `chiefComplaint` / `clinicalHistory` / `physicalExam` / `conduta` | campos correspondentes | ✅ |
| `exams` | `Consulta.exames_solicitados` (texto livre) | ⚠️ sem modelo estruturado |

---

## Idempotência — pode rodar mais de uma vez sem duplicar

A migração detecta e pula registros já existentes:

- **Tutores**: deduplica por CPF → e-mail → vetsmart_id  
- **Animais**: pula se já existe animal com mesmo nome + tutor + clínica  
- **BlocoPrescricao**: pula se já existe bloco com mesma data + animal + clínica + instrucoes

---

## Scripts auxiliares

### Se o banco já tem dados de uma migração anterior com problemas

```bash
# 1. Ver o estado atual
python scripts/diagnostico_migracao.py

# 2. Limpar duplicatas (sempre fazer dry-run antes)
python scripts/limpar_duplicatas_migracao.py --dry-run
python scripts/limpar_duplicatas_migracao.py

# 3. Corrigir endereços de tutores já migrados
python scripts/backfill_enderecos.py --dry-run
python scripts/backfill_enderecos.py

# 4. Corrigir modo dos animais migrados para "adotado"
python scripts/backfill_animais_adotados_vetsmart.py --dry-run
python scripts/backfill_animais_adotados_vetsmart.py

# 5. Reimportar prescrições com dados corretos
python scripts/backfill_prescricoes.py --dry-run
python scripts/backfill_prescricoes.py
```

### Descrição dos scripts

| Script | Função |
|---|---|
| `migrate_vetsmart.py` | Pipeline principal: extrai do VetSmart e importa tudo no banco |
| `diagnostico_migracao.py` | Mostra duplicatas, órfãos e contagens — não altera nada |
| `limpar_duplicatas_migracao.py` | Remove tutores/animais/blocos duplicados de múltiplas rodadas |
| `backfill_enderecos.py` | Atualiza endereços, data de nascimento e RG de tutores já migrados |
| `backfill_animais_adotados_vetsmart.py` | Corrige animais migrados para `modo=adotado` (e reconcilia `status`/`is_alive`) |
| `backfill_todos_animais_adotados.py` | Força `modo=adotado` para todos os animais (opcional por clínica) |
| `backfill_prescricoes.py` | Reimporta prescrições com estrutura correta (BlocoPrescricao + campos) |
| `exportar_clientes_vetsmart.py` | Exporta dados via browser (Playwright) — uso quando há Cloudflare |

---

## Parâmetros do migrate_vetsmart.py

```
--only-import              Importa dos checkpoints existentes (não extrai)
--only-extract             Só extrai e salva checkpoints, não importa
--from-json <arquivo>      Importa a partir de JSON exportado pelo Playwright
--target-clinic-id <id>    Define a clínica sem perguntar
--target-vet-user-id <id>  Define o veterinário sem perguntar
--added-by-user-id <id>    Define quem aparece como responsável nos registros
--network-dump <arquivo>   Atualiza credenciais Parse a partir de dump de rede
```

---

## Checkpoints

Os dados brutos extraídos ficam em `scripts/vetsmart_raw/`:

```
tutores.json      →  131 registros
animais.json      →  155 registros
consultas.json    →  169 registros
prescricoes.json  →  150 registros (312 medicamentos)
vacinas.json      →    8 registros
```

Se os checkpoints existirem, o script pergunta se reutiliza ou reextrai.
Para forçar reimportação dos checkpoints sem reextrair:

```bash
python scripts/migrate_vetsmart.py --only-import
```
