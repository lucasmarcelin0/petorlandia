# PetOrlândia

A comprehensive Flask application for managing veterinary clinics, pets, appointments, and business operations.

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- PostgreSQL or compatible database
- pip (Python package manager)

### Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   - Copy `.env.example` to `.env` (if available)
   - Set required variables: `FLASK_APP`, `FLASK_ENV`, `SQLALCHEMY_DATABASE_URI`

3. **Run migrations:**
   ```bash
   flask db upgrade
   ```

4. **Start the application:**
   ```bash
   flask run
   # or for production-like mode:
   python run_production.py
   ```

### Running Tests

Execute tests with `pytest` (no external services required):
```bash
pytest
```

## 📖 Documentation

Full documentation is available in the [`docs/`](docs/) folder:

- **[📚 Documentation Index](docs/INDEX.md)** - Complete guide to all documentation
- **[🏗️ Architecture Guide](docs/ARCHITECTURE.md)** *(to be created)*
- **[🤝 Contributing Guide](docs/CONTRIBUTING.md)** - How to contribute to the project
- **[🧪 Testing & Validation](docs/TESTING_AND_VALIDATION.md)** - Testing guidelines
- **[⚙️ API Reference](docs/API.md)** *(to be created)*

### Troubleshooting & Common Issues

Check [`docs/correcciones/`](docs/correcciones/) for solutions to known issues:
- [Timezone Fixes](docs/correcciones/TIMEZONE_FIX_SUMMARY.md)
- [Migration Fixes](docs/correcciones/CORRECAO_MIGRATIONS.md)
- [Heroku Deployment](docs/correcciones/HEROKU_FIX_SUMMARY.md)

## 🛠️ Development & Maintenance

### Using Maintenance Scripts

Utility scripts for development and operations are in [`scripts/`](scripts/):

```bash
# Health check
python scripts/health_check.py

# Help with scripts
cat scripts/README.md
```

See [scripts/README.md](scripts/README.md) for available scripts and how to create new ones.

## Contabilidade — Backfill histórico

Para recompor classificações antigas ou acionar o novo agendador mensal consulte
`docs/accounting_backfill.md`, que documenta o comando
`flask classify-transactions-history`, suas opções avançadas e as variáveis do
job automático.

## Offline Usage

PetOrlândia can operate with limited connectivity thanks to a small service worker
and an offline queue. Forms marked with `data-sync="true"` will save their data
locally whenever the network is unavailable. Once the device goes back online the
queued requests are automatically sent to the server.

The file `static/offline.js` implements this behaviour and is cached by the
service worker.

### Ajustando o tempo limite do botão de envio

Formulários que usam `FormFeedback` (incluindo o fluxo offline) agora ativam um
watchdog de 5 segundos ao entrar no estado de carregamento. Caso nenhuma
resposta chegue dentro desse intervalo, o botão é reativado automaticamente e um
aviso é emitido para o usuário. Você pode ajustar esse comportamento de duas
formas:

* Adicione o atributo `data-loading-timeout` (em milissegundos) ao botão de
  envio ou ao próprio formulário para alterar o tempo limite padrão. Use `0`,
  `false` ou `off` para desativar o watchdog conscientemente quando operações
  mais longas forem esperadas.
* Opcionalmente defina `data-timeout-message` para personalizar a mensagem
  exibida quando o tempo limite expirar. O valor padrão é "O tempo limite foi
  atingido. Reativamos o botão para que você possa tentar novamente.".

Ao usar a API programática, também é possível passar `loadingTimeout` e
`timeoutMessage` nas opções de `FormFeedback.setLoading` ou
`FormFeedback.withSavingState` para substituir os valores de forma dinâmica.

## Mercado Pago

To enable payment integration you must provide credentials from your Mercado
Pago account. Create the following environment variables before running the
application:

```bash
export MERCADOPAGO_ACCESS_TOKEN="<your access token>"
export MERCADOPAGO_PUBLIC_KEY="<your public key>"
export MERCADOPAGO_WEBHOOK_SECRET="<random secret>"
export MERCADOPAGO_STATEMENT_DESCRIPTOR="PETORLANDIA"
export MERCADOPAGO_BINARY_MODE=0
```

`MERCADOPAGO_WEBHOOK_SECRET` **must** be set so webhook signatures can be
verified. When unset, notifications will be rejected.

These credentials are used when generating checkout preferences and embedding
payment widgets. Never commit your real keys into version control.

After checkout, Mercado Pago will redirect the buyer back to `/payment_status/<id>`
with a `status` parameter indicating `success` or `failure`. This page no
longer requires authentication so buyers are always redirected correctly.

If for any reason the webhook notification is not delivered, the application now
checks the payment status directly with Mercado Pago when the buyer visits the
`/payment_status/<id>` page. When an approved payment is detected a delivery
request is automatically created for the associated order.

When creating a payment preference the application now includes the
`external_reference` field with the ID of the pending payment. This allows
each Mercado Pago `payment_id` to be correlated with your own records.


According to Mercado Pago's documentation this value is mandatory, so make sure
to send your internal payment identifier in `external_reference` whenever a
preference is created.



Mercado Pago also recommends sending a unique identifier for each product
in the `items.id` field of the preference payload. The checkout process
already does this by using the product's ID, which helps improve the
approval rate of transactions.

The example script in `test.py` now includes this `id` field so you can
see how the payload should look.




To improve the approval rate, every item sent to Mercado Pago now also
includes a `description` taken from our product database.

It is also recommended to provide a valid `category_id` for each item. The
application stores this identifier in the `Product.mp_category_id` field and the
example script in `test.py` sends the value "others" by default. Update it with
the category that best represents your product to further reduce the chance of
fraud detection issues.

Mercado Pago also suggests sending additional buyer information to improve
security checks. Whenever available the application now includes the buyer's
address, phone number and CPF in the `payer` object of the preference payload.
Providing these fields can help reduce fraud rejections and increase approval
rates.

## Excelência nas funcionalidades de gestão

Para que o produto sustente qualquer estratégia comercial, priorize um
prontuário eletrônico confiável, agenda compartilhada em tempo real, controles
financeiros básicos, emissão de documentos e relatórios para a clínica. Mais
detalhes de como manter estabilidade, segurança e infraestrutura de nuvem estão
documentados em `docs/gestao_produto.md`.



