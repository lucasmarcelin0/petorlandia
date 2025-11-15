# Backfill contábil e agendamentos

O comando `flask classify-transactions-history` recompõe classificações de
receita e despesa para meses anteriores. Ele aceita janelas maiores (basta
informar `--months N` com o tamanho desejado), múltiplas clínicas e oferece um
modo verboso para acompanhar cada combinação processada.

```bash
flask classify-transactions-history \
  --months 18 \
  --clinic-id 12 --clinic-id 34 \
  --reference-month 2024-06 \
  --verbose
```

Principais opções:

* `--months`: quantidade de meses a partir do mês de referência. Use valores
  altos para recuperar históricos longos; o comando valida apenas que o número
  seja maior que zero.
* `--clinic-id`: pode ser informado várias vezes para delimitar clínicas
  específicas. Quando omitido, todas as clínicas são processadas.
* `--reference-month`: mês inicial (`YYYY-MM`). Padrão: mês atual.
* `--verbose`: imprime logs detalhando cada clínica/mês processados e quaisquer
  falhas detectadas.

Ao final o comando informa quantas combinações foram processadas e destaca
falhas individuais (que também ficam registradas no log da aplicação).

## Agendamento mensal automático

O arquivo `scheduler.py` ativa um agendador baseado em APScheduler (registrado
como `scheduler: python scheduler.py` no `Procfile`). Ele executa o mesmo
backfill de maneira recorrente — ideal para garantir que orçamentos adicionados
após o fechamento do mês apareçam automaticamente na contabilidade.

Variáveis suportadas:

| Variável | Descrição |
| --- | --- |
| `ACCOUNTING_BACKFILL_MONTHS` | Número de meses reprocessados a cada execução (padrão `6`). |
| `ACCOUNTING_BACKFILL_CLINICS` | Lista de IDs separados por vírgula (padrão: todas as clínicas). |
| `ACCOUNTING_BACKFILL_REFERENCE` | Mês base manual; quando vazio usa o mês atual. |
| `ACCOUNTING_BACKFILL_DAY` / `ACCOUNTING_BACKFILL_HOUR` / `ACCOUNTING_BACKFILL_MINUTE` | Janela do cron para o disparo mensal (padrões `2`, `4` e `30`). |
| `ACCOUNTING_BACKFILL_TZ` | Fuso horário usado pelo agendador (`UTC` por padrão). |

Ative o processo `scheduler` (por exemplo, em um dyno "clock" do Heroku ou em um
serviço equivalente) para garantir que o backfill rode mensalmente. Logs são
emitidos para cada execução, detalhando combinações processadas e eventuais
falhas.
