# Accounting Integration Implementation Checklist

## Quick Start Checklist

### Phase 1: Foundation (Week 1)

- [ ] **Data Audit**
  - [ ] Query Payment table for NULL amounts
  - [ ] Query ClassifiedTransaction for missing origins
  - [ ] Check PlantonistaEscala orphans: `WHERE status IN ('realizado','confirmado') AND pj_payment_id IS NULL`
  - [ ] Create report: "Data Quality Issues Summary"

- [ ] **Create Enums**
  - [ ] Define `ClassificationOrigin` enum in models.py
  - [ ] Define `PJPaymentStatus` enum in models.py
  - [ ] Define `ClinicNotificationCategory` enum in models.py
  - [ ] Create migration for enum types

- [ ] **Add Audit Trail**
  - [ ] Create `ClassifiedTransactionAudit` model
  - [ ] Add `created_by_id` to `ClassifiedTransaction`
  - [ ] Add `created_by_method` field (values: 'api', 'cli', 'auto', 'ui')
  - [ ] Migration script

- [ ] **Fix Payment.amount**
  - [ ] Create migration: `ALTER TABLE payment ALTER COLUMN amount SET NOT NULL DEFAULT 0.00`
  - [ ] Backfill existing NULL values with 0.00
  - [ ] Write test: `test_payment_amount_not_null`

**Estimated Effort:** 12-16 hours

---

### Phase 2: Gap #1 - Consulta Classification (Week 2)

- [ ] **Model Changes**
  - [ ] Add `consulta_id` foreign key to `ClassifiedTransaction`
  - [ ] Add `consulta` relationship
  - [ ] Migration script

- [ ] **Service Implementation**
  - [ ] Create `services/finance.py::_sync_consulta_classification(consulta)` function
  - [ ] Handle missing orcamento_items case
  - [ ] Calculate total_value from items
  - [ ] Set category='receita_servico', subcategory='consulta'

- [ ] **Event Listener Setup**
  - [ ] Add SQLAlchemy event listener in models.py:
    - Trigger: `after_update` on Consulta
    - Condition: `status == 'completed'`
    - Action: Call `_sync_consulta_classification()`
  - [ ] Wrap in try-catch with logging

- [ ] **Testing**
  - [ ] Unit test: `test_consulta_creates_classified_transaction`
  - [ ] Unit test: `test_consulta_without_items_skips_classification`
  - [ ] Integration test: Complete flow
  - [ ] Edge case: Consulta status changes back to 'pending'

- [ ] **Backfill Existing Data**
  - [ ] Create migration script to classify completed consultas
  - [ ] Run on staging first
  - [ ] Validate results before production

**Estimated Effort:** 16-20 hours

---

### Phase 3: Gap #2 - Payment/Vendor Reconciliation (Week 2-3)

- [ ] **Model Changes**
  - [ ] Add `payment_id` foreign key to `PJPayment` (optional)
  - [ ] Add `payment_reference` field (memo)
  - [ ] Add `allocated_at` timestamp
  - [ ] Migration script

- [ ] **Service Implementation**
  - [ ] Create `services/finance.py::_sync_payment_classification(payment)` function
  - [ ] Link Payment → PJPayment when allocated
  - [ ] Track "received" vs "allocated" states
  - [ ] Create notification for unallocated payments

- [ ] **API Endpoint**
  - [ ] `POST /api/contabilidade/payments/allocate`
  - [ ] Request body: `{payment_id, pj_payment_id, amount}`
  - [ ] Validate: Payment amount matches PJPayment valor
  - [ ] Create audit log entry
  - [ ] Return reconciliation summary

- [ ] **Testing**
  - [ ] Unit test: Payment allocation
  - [ ] Unit test: Over-allocation prevention
  - [ ] Integration test: Reconciliation report
  - [ ] Edge case: Partial payment allocation

**Estimated Effort:** 12-16 hours

---

### Phase 4: Gap #3 - Service Reconciliation (Week 3)

- [ ] **Model Changes**
  - [ ] Create `ConsultaServiceRecord` junction model
  - [ ] Fields: `id`, `consulta_id`, `service_id`, `quantity`, `amount`, `billed_at`
  - [ ] Add relationship to Consulta
  - [ ] Migration script

- [ ] **Service Implementation**
  - [ ] Modify Consulta completion workflow to validate services
  - [ ] Create `_validate_services_billed(consulta)` function
  - [ ] Return list of unbilled services
  - [ ] Warn user before completion if unbilled items found

- [ ] **OrcamentoItem Enhancement**
  - [ ] Add `service_source` field ('manual' | 'consulta_auto')
  - [ ] When auto-creating from services, set source='consulta_auto'
  - [ ] Migration script

- [ ] **Testing**
  - [ ] Unit test: Service billing validation
  - [ ] Unit test: Auto-create orcamento item
  - [ ] Integration test: Complete service → billing flow
  - [ ] Edge case: Duplicate service creation

**Estimated Effort:** 10-14 hours

---

### Phase 5: Gap #4 - Insurance Tracking (Week 4)

- [ ] **Model Changes**
  - [ ] Add `coverage_id` to `ClassifiedTransaction`
  - [ ] Add `payer_type` field ('particular' | 'plan')
  - [ ] Add `insurance_claim_id` field
  - [ ] Migration script
  - [ ] Update UniqueConstraint to exclude insurance fields

- [ ] **Service Implementation**
  - [ ] Modify `_sync_orcamento_payment_classification()` to:
    - Split transactions by payer_type
    - Create separate CT entries for plan vs particular
    - Link to HealthCoverage/HealthClaim
  - [ ] Create separate category: 'receita_seguro'

- [ ] **Reporting**
  - [ ] Create `GET /api/contabilidade/receivables/by-payer`
  - [ ] Create `GET /api/contabilidade/insurance-claims/reconciliation`
  - [ ] Dashboard: Insurance receivables aging

- [ ] **Testing**
  - [ ] Unit test: Insurance vs particular split
  - [ ] Unit test: Insurance claim linking
  - [ ] Integration test: Full insurance flow
  - [ ] Report validation: Totals match source data

**Estimated Effort:** 14-18 hours

---

### Phase 6: Gap #5 - PlantonistaEscala Auto-Payment (Week 4-5)

- [ ] **Model Changes**
  - [ ] Add DB constraint: `CHECK (pj_payment_id IS NOT NULL when status IN ('confirmado','realizado'))`
  - [ ] Migration script
  - [ ] Backfill: Auto-create missing PJPayments

- [ ] **Service Implementation**
  - [ ] Add `PlantonistaEscala.auto_create_payment()` method
  - [ ] Calculate payment value from hours × hourly rate
  - [ ] Create PJPayment with auto-generated description
  - [ ] Link bidirectionally

- [ ] **Event Listener Setup**
  - [ ] Trigger on: `PlantonistaEscala.status` → 'confirmado'
  - [ ] Action: `auto_create_payment()` if not already linked
  - [ ] Cascade status: if Escala status changes, update PJPayment status
  - [ ] Error logging with clinic notification

- [ ] **Notification System**
  - [ ] Create: "Vendor payment pending" when Escala realizado
  - [ ] Create: "Schedule without payment link" for orphaned Escalas
  - [ ] Weekly digest: Pending vendor payments

- [ ] **Testing**
  - [ ] Unit test: Auto-payment creation
  - [ ] Unit test: Status cascade
  - [ ] Integration test: Complete schedule → payment flow
  - [ ] Edge case: Payment already exists
  - [ ] Edge case: Missing medico_cnpj

- [ ] **Backfill Script**
  - [ ] Query: Confirmed/realizado Escalas without pj_payment_id
  - [ ] For each: Create PJPayment with status='pendente'
  - [ ] Log: "Backfilled X payments"
  - [ ] Validate: No duplicate payments created

**Estimated Effort:** 16-20 hours

---

### Phase 7: Gap #6 - Dynamic Tax Recalculation (Week 5-6)

- [ ] **Model Changes**
  - [ ] Add `recalculated_at` timestamp to `ClinicTaxes`
  - [ ] Add `previous_liability` field to track changes
  - [ ] Migration script

- [ ] **Service Implementation**
  - [ ] Create `services/finance.py::_refresh_clinic_taxes(clinic_id, month)` function
  - [ ] Calculate:
    - [ ] ISS total (5% of service revenue)
    - [ ] PJ withholdings (5% of vendor payments)
    - [ ] DAS bracket (based on annual projection)
    - [ ] Fator R (revenue / service costs)
  - [ ] Compare to previous: alert if liability changed >5%

- [ ] **Event Listener Setup**
  - [ ] Trigger on: `ClassifiedTransaction` insert/update/delete
  - [ ] Condition: Only if category in REVENUE_CATEGORIES
  - [ ] Action: Call `_refresh_clinic_taxes()` with rate limiting
  - [ ] Trigger on: `PJPayment` status changes to 'pago'

- [ ] **Notification System**
  - [ ] Create: "Tax liability changed" if delta >5%
  - [ ] Create: "DAS bracket changed" if annual projection crosses threshold
  - [ ] Daily digest: Recalculation summary

- [ ] **Testing**
  - [ ] Unit test: Tax calculation accuracy
  - [ ] Unit test: DAS bracket selection
  - [ ] Unit test: Fator R calculation
  - [ ] Integration test: Tax refresh on transaction change
  - [ ] Edge case: Zero revenue month
  - [ ] Edge case: Large PJ payment in month

**Estimated Effort:** 18-24 hours

---

### Phase 8: Gap #7 - BlocoOrcamento Value Tracking (Week 6)

- [ ] **Model Changes**
  - [ ] Create `BlocoOrcamentoAdjustment` model:
    - Fields: `id`, `bloco_id`, `previous_value`, `new_value`, `reason`, `adjusted_at`, `user_id`
  - [ ] Migration script

- [ ] **Service Implementation**
  - [ ] Add trigger on `BlocoOrcamento.discount_value` change
  - [ ] Add trigger on `BlocoOrcamento.discount_percent` change
  - [ ] When changed:
    - [ ] Find matching ClassifiedTransaction
    - [ ] Create adjustment record
    - [ ] Update CT.value to new total_liquido
    - [ ] If delta >10%, create notification "Large adjustment"

- [ ] **Alternative: Hybrid Property**
  - [ ] Make `ClassifiedTransaction.value` read-only (hybrid_property)
  - [ ] Calculate as: `SELECT bloco.total - bloco.discount_value`
  - [ ] Trade-off: Can't do reports on frozen value
  - [ ] Better to use adjustment tracking

- [ ] **Testing**
  - [ ] Unit test: Value update on discount change
  - [ ] Unit test: Adjustment record creation
  - [ ] Unit test: Large adjustment alert
  - [ ] Integration test: Full discount → reporting flow

**Estimated Effort:** 10-14 hours

---

### Phase 9: API Endpoints (Week 6-7)

- [ ] **Classification Endpoint**
  - [ ] `POST /api/contabilidade/classify`
  - [ ] Params: `clinic_id`, `month` (YYYY-MM), `origin` (optional)
  - [ ] Force reclassification for filtered period
  - [ ] Return: count of updated transactions
  - [ ] Requires: permission check

- [ ] **Reconciliation Endpoint**
  - [ ] `GET /api/contabilidade/reconcile`
  - [ ] Params: `clinic_id`, `month`
  - [ ] Compare:
    - Payment totals vs ClassifiedTransaction totals
    - Consulta revenue vs CT revenue
    - Orcamento amounts vs CT amounts
  - [ ] Return: discrepancies report

- [ ] **Audit Endpoint**
  - [ ] `GET /api/contabilidade/audit/{transaction_id}`
  - [ ] Return: full history with audit log
  - [ ] Show: who changed what, when, why

- [ ] **Tax Endpoint**
  - [ ] `GET /api/contabilidade/taxes/{clinic_id}/{month}`
  - [ ] Return: current taxes + calculation breakdown
  - [ ] Support force-refresh parameter

**Estimated Effort:** 10-12 hours

---

### Phase 10: Reporting (Week 7-8)

- [ ] **Revenue Recognition Report**
  - [ ] Template: `templates/contabilidade/revenue_recognition.html`
  - [ ] Show:
    - Services provided but not billed
    - Billed but not collected
    - Collected but not recorded
  - [ ] Filters: clinic, date range

- [ ] **Budget vs Actual Report**
  - [ ] Compare: estimated (Orcamento) vs actual (ClassifiedTransaction)
  - [ ] Show variance % by category
  - [ ] Trend charts

- [ ] **Insurance Receivables Report**
  - [ ] Aging: 0-30, 30-60, 60-90, 90+ days
  - [ ] By insurance company
  - [ ] By claim status

- [ ] **Vendor Payment Report**
  - [ ] Outstanding vendor payments (pending)
  - [ ] Payment history with invoice tracking
  - [ ] Withholding tax breakdown

**Estimated Effort:** 16-20 hours

---

### Phase 11: Testing & QA (Week 8)

- [ ] **Unit Tests** (aim: 85%+ coverage)
  - [ ] Create: `tests/test_accounting_gaps.py`
  - [ ] All 7 gap implementations covered
  - [ ] Edge cases and error scenarios
  - [ ] Run: `pytest tests/test_accounting_gaps.py -v`

- [ ] **Integration Tests**
  - [ ] End-to-end appointment → reporting
  - [ ] End-to-end vendor payment flow
  - [ ] Insurance claim reconciliation
  - [ ] Tax calculation accuracy

- [ ] **Performance Tests**
  - [ ] Classify 1000 transactions: <5 seconds
  - [ ] Refresh taxes for 12 months: <10 seconds
  - [ ] Generate reports: <30 seconds

- [ ] **Data Migration Tests**
  - [ ] Dry-run on staging with prod backup
  - [ ] Validate data integrity before/after
  - [ ] Rollback procedure tested

**Estimated Effort:** 12-16 hours

---

### Phase 12: Deployment & Monitoring (Week 9)

- [ ] **Staging Deployment**
  - [ ] Run all migrations
  - [ ] Run backfill scripts
  - [ ] Validate: all tests pass
  - [ ] Smoke tests in UI
  - [ ] Performance baselines

- [ ] **Production Deployment**
  - [ ] Backup database
  - [ ] Deploy during low-traffic window
  - [ ] Monitor: error rates, slow queries
  - [ ] Have rollback plan ready

- [ ] **Monitoring Setup**
  - [ ] Alert: if auto-classification fails >3 times
  - [ ] Alert: if ClassifiedTransaction changes without audit trail
  - [ ] Alert: if tax recalc doesn't complete within 24hrs
  - [ ] Daily report: classification status by clinic

- [ ] **Documentation**
  - [ ] Update: docs/accounting_backfill.md
  - [ ] Create: docs/accounting_integration_guide.md
  - [ ] Create: docs/accounting_api.md
  - [ ] Add: troubleshooting section

**Estimated Effort:** 8-12 hours

---

## Summary by Phase

| Phase | Title | Hours | Week |
|-------|-------|-------|------|
| 1 | Foundation (Enums, Audit, Fixes) | 14 | Week 1 |
| 2 | Gap #1 - Consulta Classification | 18 | Week 2 |
| 3 | Gap #2 - Payment Reconciliation | 14 | Week 2-3 |
| 4 | Gap #3 - Service Reconciliation | 12 | Week 3 |
| 5 | Gap #4 - Insurance Tracking | 16 | Week 4 |
| 6 | Gap #5 - PlantonistaEscala AutoPay | 18 | Week 4-5 |
| 7 | Gap #6 - Dynamic Tax Recalc | 20 | Week 5-6 |
| 8 | Gap #7 - BlocoOrcamento Tracking | 12 | Week 6 |
| 9 | API Endpoints | 11 | Week 6-7 |
| 10 | Reporting | 18 | Week 7-8 |
| 11 | Testing & QA | 14 | Week 8 |
| 12 | Deployment & Monitoring | 10 | Week 9 |
| | **TOTAL** | **177 hours** | **9 weeks** |

**Team Recommendation:** 2 developers × 9 weeks = one full sprint cycle

---

## Success Criteria

After completion, verify:

✅ All 7 gaps closed with automated workflows  
✅ 100% of financial transactions have audit trail  
✅ Monthly reconciliation time <15 minutes  
✅ Tax calculations refresh within 6 hours of month-end  
✅ Zero orphaned records in accounting tables  
✅ 85%+ test coverage on accounting module  
✅ All new features documented in API docs  
✅ Accounting team sign-off on reporting accuracy  

---

## Quick Links

- **Main Analysis:** `ACCOUNTING_INTEGRATION_ANALYSIS.md`
- **Finance Module:** `services/finance.py`
- **Models:** `models.py` (search: `ClassifiedTransaction`, `ClinicTaxes`, `PJPayment`)
- **Accounting Routes:** `app.py` (search: `@app.route('/contabilidade')`)
- **Tests:** `tests/test_financial_snapshots.py`

