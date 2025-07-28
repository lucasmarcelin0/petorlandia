# PetOrlândia

This project is a Flask application for managing pets. The repository now includes basic unit tests.

## Running the tests

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Execute the tests:
   ```bash
   pytest
   ```

   Generate a coverage report with:
   ```bash
   pytest --cov
   ```

The tests run without needing external services or a database connection and
are automatically executed on GitHub Actions for every push and pull request.

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



