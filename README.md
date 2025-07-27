# PetOrlândia

This project is a Flask application for managing pets. The repository now includes basic unit tests.

## Running the tests

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Execute the tests with `pytest`:
   ```bash
   pytest
   ```

The tests run without needing external services or a database connection.

## Offline Usage

PetOrlândia can operate with limited connectivity thanks to a small service worker
and an offline queue. Forms marked with `data-sync="true"` will save their data
locally whenever the network is unavailable. Once the device goes back online the
queued requests are automatically sent to the server.

The file `static/offline.js` implements this behaviour and is cached by the
service worker.

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
with a `status` parameter indicating `success` or `failure`.

If for any reason the webhook notification is not delivered, the application now
checks the payment status directly with Mercado Pago when the buyer visits the
`/payment_status/<id>` page. When an approved payment is detected a delivery
request is automatically created for the associated order.

When creating a payment preference the application now includes the
`external_reference` field with the ID of the pending payment. This allows
each Mercado Pago `payment_id` to be correlated with your own records.

Mercado Pago also recommends sending a unique identifier for each product
in the `items.id` field of the preference payload. The checkout process
already does this by using the product's ID, which helps improve the
approval rate of transactions.
