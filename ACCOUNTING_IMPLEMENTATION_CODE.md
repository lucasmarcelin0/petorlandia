# Accounting Integration: Ready-to-Use Code Snippets

This document contains production-ready code snippets for implementing the 7 accounting gaps.

## 1. Enums & Data Structures

### 1.1 Add to models.py (after imports)

```python
# Add these imports
import enum

# Classification Origin Enum
class ClassificationOrigin(enum.Enum):
    PJ_PAYMENT = 'pj_payment'
    ORCAMENTO = 'orcamento'
    BLOCO_ORCAMENTO = 'bloco_orcamento'
    CONSULTA = 'consulta'
    MANUAL = 'manual'
    INSURANCE_CLAIM = 'insurance'
    REFUND = 'refund'

# PJ Payment Status Enum
class PJPaymentStatus(enum.Enum):
    PENDING = 'pendente'
    NOTA_FISCAL_RECEIVED = 'recebido_nf'
    PARTIAL = 'parcial'
    PAID = 'pago'
    OVERDUE = 'vencido'
    CANCELLED = 'cancelado'
    REFUNDED = 'reembolsado'

# Notification Category Enum
class ClinicNotificationCategory(enum.Enum):
    TAX_LIABILITY = 'tax_liability'
    UNPROCESSED_PAYMENT = 'unprocessed_payment'
    CLASSIFICATION_DELAY = 'classification_delay'
    MISSING_INVOICE = 'missing_invoice'
    ORPHANED_SCHEDULE = 'orphaned_schedule'
    RECONCILIATION = 'reconciliation'
    AUDIT = 'audit'
    INSURANCE_CLAIM = 'insurance_claim'
    VENDOR_OVERDUE = 'vendor_overdue'
```

---

## 2. Model Updates

### 2.1 Update ClassifiedTransaction model

```python
# In models.py - ClassifiedTransaction class

class ClassifiedTransaction(db.Model):
    __tablename__ = 'classified_transactions'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'raw_id', name='uq_classified_raw_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    date = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    month = db.Column(db.Date, nullable=False, index=True)
    
    # NEW: Use enum instead of string
    origin = db.Column(
        db.Enum(ClassificationOrigin, name='classification_origin'),
        nullable=False,
        index=True
    )
    
    description = db.Column(db.String(255), nullable=False)
    value = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    category = db.Column(db.String(80), nullable=False, index=True)
    subcategory = db.Column(db.String(80), nullable=True)
    raw_id = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    
    # NEW: Audit trail
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_by_method = db.Column(db.String(20), nullable=True)  # 'api', 'cli', 'auto', 'ui'
    reclassified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    
    # NEW: Insurance tracking (Gap #4)
    coverage_id = db.Column(db.Integer, db.ForeignKey('health_coverage.id'), nullable=True)
    payer_type = db.Column(db.String(20), nullable=True)  # 'particular', 'plan'
    insurance_claim_id = db.Column(db.Integer, nullable=True)
    
    # NEW: Consulta reference (Gap #1)
    consulta_id = db.Column(db.Integer, db.ForeignKey('consulta.id'), nullable=True)

    # Relationships
    clinic = db.relationship(
        'Clinica',
        backref=db.backref('classified_transactions', cascade='all, delete-orphan', lazy=True),
    )
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    coverage = db.relationship('HealthCoverage', foreign_keys=[coverage_id])
    consulta = db.relationship('Consulta', foreign_keys=[consulta_id])

    def __repr__(self):
        return f"<{self.origin.value} {self.category} R$ {self.value}>"


# NEW: Audit trail model
class ClassifiedTransactionAudit(db.Model):
    __tablename__ = 'classified_transaction_audit'

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(
        db.Integer,
        db.ForeignKey('classified_transactions.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    action = db.Column(db.String(20), nullable=False)  # 'created', 'updated', 'reclassified'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    old_value = db.Column(db.JSON, nullable=True)
    new_value = db.Column(db.JSON, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    transaction = db.relationship('ClassifiedTransaction', backref=db.backref('audit_logs'))
    user = db.relationship('User')

    def __repr__(self):
        return f"<Audit {self.action} on CT#{self.transaction_id}>"
```

### 2.2 Update PJPayment model

```python
# In models.py - PJPayment class

class PJPayment(db.Model):
    __tablename__ = 'pj_payments'
    __table_args__ = (
        db.CheckConstraint('valor >= 0', name='ck_pj_payments_valor_positive'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    prestador_nome = db.Column(db.String(150), nullable=False)
    prestador_cnpj = db.Column(db.String(20), nullable=False)
    nota_fiscal_numero = db.Column(db.String(80), nullable=True)
    tipo_prestador = db.Column(
        db.String(50),
        nullable=True,
        default='especialista',
        server_default='especialista',
    )
    plantao_horas = db.Column(db.Numeric(5, 2), nullable=True)
    valor = db.Column(db.Numeric(14, 2), nullable=False)
    data_servico = db.Column(db.Date, nullable=False)
    data_pagamento = db.Column(db.Date, nullable=True)
    
    # NEW: Use enum instead of string
    status = db.Column(
        db.Enum(PJPaymentStatus, name='pj_payment_status'),
        nullable=False,
        default=PJPaymentStatus.PENDING,
        server_default='pendente',
    )
    
    observacoes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=now_in_brazil,
        onupdate=now_in_brazil,
    )
    
    # NEW: Payment allocation tracking (Gap #2)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=True)
    payment_reference = db.Column(db.String(255), nullable=True)
    allocated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('pj_payments', cascade='all, delete-orphan', lazy=True),
    )
    payment = db.relationship('Payment', backref=db.backref('vendor_payments', lazy=True))

    def is_paid(self):
        return self.status == PJPaymentStatus.PAID

    def __repr__(self):
        return f"<PJPayment {self.prestador_nome} R$ {self.valor}>"
```

### 2.3 Update ClinicNotification model

```python
# In models.py - ClinicNotification class

class ClinicNotification(db.Model):
    __tablename__ = 'clinic_notifications'

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=True)
    type = db.Column(db.String(20), nullable=False, default='info')
    
    # NEW: Category enum
    category = db.Column(
        db.Enum(ClinicNotificationCategory, name='notification_category'),
        nullable=True
    )
    
    month = db.Column(db.Date, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now_in_brazil)
    resolved = db.Column(db.Boolean, nullable=False, default=False)
    resolution_date = db.Column(db.DateTime(timezone=True), nullable=True)
    
    # NEW: Context/metadata
    metadata = db.Column(db.JSON, nullable=True)
    related_id = db.Column(db.Integer, nullable=True)  # CT ID, Payment ID, etc

    clinic = db.relationship(
        'Clinica',
        backref=db.backref('clinic_notifications', cascade='all, delete-orphan', lazy=True),
    )

    def __repr__(self):
        return f"<Notification [{self.category}] {self.title}>"
```

### 2.4 Add to ClinicTaxes model

```python
# In models.py - ClinicTaxes class - add these fields

class ClinicTaxes(db.Model):
    __tablename__ = 'clinic_taxes'
    __table_args__ = (
        db.UniqueConstraint('clinic_id', 'month', name='uq_clinic_taxes_clinic_month'),
    )

    id = db.Column(db.Integer, primary_key=True)
    clinic_id = db.Column(db.Integer, db.ForeignKey('clinica.id'), nullable=False, index=True)
    month = db.Column(db.Date, nullable=False, index=True)
    iss_total = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    das_total = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    retencoes_pj = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    fator_r = db.Column(db.Numeric(6, 4), nullable=False, default=Decimal('0.0000'))
    faixa_simples = db.Column(db.Integer, nullable=True)
    projecao_anual = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal('0.00'))
    created_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, onupdate=now_in_brazil, nullable=False)
    
    # NEW: Track recalculation (Gap #6)
    recalculated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    previous_liability = db.Column(db.Numeric(14, 2), nullable=True)
    
    clinic = db.relationship(
        'Clinica',
        backref=db.backref('tax_reports', cascade='all, delete-orphan', lazy=True),
    )

    def __repr__(self):
        return f"<ClinicTaxes clinic={self.clinic_id} month={self.month}>"
```

---

## 3. Service Functions

### 3.1 Add to services/finance.py

```python
# Core classification helper for Consulta (Gap #1)

def _sync_consulta_classification(consulta) -> Optional[ClassifiedTransaction]:
    """
    Create or update classified transaction for completed consultation.
    
    Args:
        consulta: Consulta instance
        
    Returns:
        ClassifiedTransaction if created/updated, None if skipped
    """
    if not consulta or not getattr(consulta, 'clinica_id', None):
        return None
    
    if consulta.status != 'completed':
        return None
    
    # Calculate total from orcamento items
    orcamento_items = getattr(consulta, 'orcamento_items', [])
    total_value = sum(
        Decimal(str(item.valor or 0)) 
        for item in orcamento_items 
        if item and item.valor
    )
    
    if total_value <= 0:
        # No services billed, skip classification
        return None
    
    reference_date = getattr(consulta, 'data_consulta', None) or date.today()
    month = reference_date.replace(day=1)
    
    raw_id = f"consulta:{consulta.id}"
    
    classification = ClassifiedTransaction.query.filter_by(
        origin=ClassificationOrigin.CONSULTA,
        raw_id=raw_id
    ).first()
    
    if classification is None:
        classification = ClassifiedTransaction(
            origin=ClassificationOrigin.CONSULTA,
            raw_id=raw_id,
            created_by_method='auto'
        )
    
    animal = getattr(consulta, 'animal', None)
    animal_name = animal.name if animal else "Paciente"
    
    classification.clinic_id = consulta.clinica_id
    classification.date = datetime.combine(reference_date, time.min)
    classification.month = month
    classification.description = f"Consulta #{consulta.id} - {animal_name}"[:255]
    classification.value = _quantize_currency(total_value)
    classification.category = 'receita_servico'
    classification.subcategory = 'consulta'
    classification.consulta_id = consulta.id
    
    db.session.add(classification)
    return classification


# Helper to sync payment allocation (Gap #2)

def _sync_payment_classification(payment) -> Optional[dict]:
    """
    Sync customer payment to vendor payment allocation.
    
    Returns:
        Dict with 'allocated_id' (PJPayment ID) and 'amount' if allocated
    """
    if not payment or not payment.order_id:
        return None
    
    order = getattr(payment, 'order', None)
    if not order or not order.clinic_id:
        return None
    
    # Find unallocated vendor payments for this clinic that month
    payment_month = payment.created_at.date().replace(day=1)
    
    pending_vendors = PJPayment.query.filter(
        PJPayment.clinic_id == order.clinic_id,
        PJPayment.payment_id.is_(None),
        func.date_trunc('month', PJPayment.data_servico) == payment_month
    ).order_by(PJPayment.created_at).all()
    
    if not pending_vendors:
        return None
    
    # Try to match payment amount to vendor payment
    payment_amount = Decimal(str(payment.amount or 0))
    
    for vendor_payment in pending_vendors:
        vendor_amount = Decimal(str(vendor_payment.valor or 0))
        
        if payment_amount >= vendor_amount:
            # Allocate
            vendor_payment.payment_id = payment.id
            vendor_payment.payment_reference = f"Payment #{payment.id}"
            vendor_payment.allocated_at = now_in_brazil()
            
            db.session.add(vendor_payment)
            
            return {
                'allocated_id': vendor_payment.id,
                'amount': vendor_amount
            }
    
    return None


# Refresh taxes dynamically (Gap #6)

def _refresh_clinic_taxes(clinic_id: int, month: date) -> Optional[ClinicTaxes]:
    """
    Recalculate tax obligations based on current classified transactions.
    
    Args:
        clinic_id: Clinica ID
        month: Month to calculate (YYYY-MM-01)
        
    Returns:
        Updated ClinicTaxes record
    """
    if not clinic_id or not month:
        return None
    
    taxes = ClinicTaxes.query.filter_by(
        clinic_id=clinic_id,
        month=month
    ).first()
    
    if taxes is None:
        taxes = ClinicTaxes(
            clinic_id=clinic_id,
            month=month
        )
    
    # 1. Get revenue transactions
    revenue_query = db.session.query(
        func.coalesce(func.sum(ClassifiedTransaction.value), 0)
    ).filter(
        ClassifiedTransaction.clinic_id == clinic_id,
        ClassifiedTransaction.month == month,
        ClassifiedTransaction.category.in_(REVENUE_CATEGORIES)
    )
    
    total_revenue = Decimal(str(revenue_query.scalar() or 0))
    
    # 2. Calculate ISS (5% of service revenue)
    service_query = db.session.query(
        func.coalesce(func.sum(ClassifiedTransaction.value), 0)
    ).filter(
        ClassifiedTransaction.clinic_id == clinic_id,
        ClassifiedTransaction.month == month,
        ClassifiedTransaction.category == 'receita_servico'
    )
    
    service_revenue = Decimal(str(service_query.scalar() or 0))
    iss_total = _quantize_currency(service_revenue * Decimal('0.05'))
    
    # 3. Get PJ payment retentions (5%)
    pj_query = db.session.query(
        func.coalesce(func.sum(PJPayment.valor), 0)
    ).filter(
        PJPayment.clinic_id == clinic_id,
        func.date_trunc('month', PJPayment.data_servico) == month,
        PJPayment.status != PJPaymentStatus.CANCELLED
    )
    
    pj_total = Decimal(str(pj_query.scalar() or 0))
    retencoes = _quantize_currency(pj_total * VET_WITHHOLDING_RATE)
    
    # 4. Calculate DAS bracket (simplified - use annual projection)
    annual_revenue = total_revenue * 12
    faixa = _calculate_das_bracket(annual_revenue)
    das_amount = _calculate_das_amount(annual_revenue, faixa)
    
    # 5. Calculate Fator R (service costs / revenue)
    # For now, use pj_total / service_revenue
    if service_revenue > 0:
        fator_r = _quantize_factor(pj_total / service_revenue)
    else:
        fator_r = Decimal('0')
    
    # Check for significant changes
    old_liability = Decimal(str(taxes.iss_total or 0)) + Decimal(str(taxes.das_total or 0))
    new_liability = iss_total + das_amount
    
    taxes.iss_total = iss_total
    taxes.das_total = das_amount
    taxes.retencoes_pj = retencoes
    taxes.fator_r = fator_r
    taxes.faixa_simples = faixa
    taxes.projecao_anual = annual_revenue
    taxes.previous_liability = old_liability
    taxes.recalculated_at = now_in_brazil()
    taxes.updated_at = now_in_brazil()
    
    db.session.add(taxes)
    
    # Create alert if liability changed significantly
    if old_liability != Decimal('0') and new_liability != old_liability:
        change_percent = ((new_liability - old_liability) / old_liability * 100)
        
        if abs(change_percent) > 5:
            notification = ClinicNotification(
                clinic_id=clinic_id,
                month=month,
                title=f"Mudança na obrigação fiscal ({change_percent:+.1f}%)",
                message=f"Obrigação anterior: R$ {old_liability:.2f} → Nova: R$ {new_liability:.2f}",
                type='warning' if abs(change_percent) > 10 else 'info',
                category=ClinicNotificationCategory.TAX_LIABILITY,
                metadata={
                    'old_liability': str(old_liability),
                    'new_liability': str(new_liability),
                    'change_percent': float(change_percent)
                }
            )
            db.session.add(notification)
    
    return taxes


# Helper to create audit log entry

def _audit_classified_transaction(
    transaction: ClassifiedTransaction,
    action: str,
    user_id: Optional[int] = None,
    reason: Optional[str] = None
) -> ClassifiedTransactionAudit:
    """Create audit log for transaction change."""
    
    audit = ClassifiedTransactionAudit(
        transaction_id=transaction.id,
        action=action,
        user_id=user_id,
        reason=reason,
        new_value={
            'category': transaction.category,
            'subcategory': transaction.subcategory,
            'value': str(transaction.value),
            'description': transaction.description
        }
    )
    
    db.session.add(audit)
    return audit
```

---

## 4. Event Listeners

### 4.1 Add to models.py (at end of file)

```python
from sqlalchemy import event
from flask import has_request_context, current_app

# Auto-classify Consulta on completion
@event.listens_for(Consulta, 'after_update')
def sync_consulta_on_completion(mapper, connection, target):
    """Trigger consultation classification when status changes to 'completed'."""
    if not has_request_context() or not target.status == 'completed':
        return
    
    try:
        from services.finance import _sync_consulta_classification
        _sync_consulta_classification(target)
    except Exception as e:
        current_app.logger.warning(f"Failed to classify Consulta #{target.id}: {e}")


# Auto-create PJPayment for PlantonistaEscala
@event.listens_for(PlantonistaEscala, 'after_update')
def auto_create_payment_on_confirmation(mapper, connection, target):
    """Auto-create PJPayment when escala is confirmed."""
    if not has_request_context() or target.pj_payment_id is not None:
        return
    
    if target.status not in ('confirmado', 'realizado'):
        return
    
    if not target.medico_nome or not target.medico_cnpj:
        current_app.logger.warning(f"Cannot auto-create payment: missing vendor details for Escala #{target.id}")
        return
    
    try:
        valor = Decimal(str(target.valor_previsto or 0))
        
        payment = PJPayment(
            clinic_id=target.clinic_id,
            prestador_nome=target.medico_nome,
            prestador_cnpj=target.medico_cnpj,
            tipo_prestador='plantonista',
            plantao_horas=target.plantao_horas,
            valor=valor,
            data_servico=target.inicio.date() if target.inicio else date.today(),
            status='pendente',
            observacoes=f"Auto-gerado de Escala #{target.id}"
        )
        
        db.session.add(payment)
        db.session.flush()
        
        target.pj_payment_id = payment.id
        
        # Log action
        current_app.logger.info(f"Auto-created PJPayment #{payment.id} for PlantonistaEscala #{target.id}")
        
    except Exception as e:
        current_app.logger.error(f"Failed to auto-create payment for Escala #{target.id}: {e}")


# Refresh taxes when transactions change
_tax_refresh_cooldown = {}

@event.listens_for(ClassifiedTransaction, 'after_insert')
@event.listens_for(ClassifiedTransaction, 'after_update')
@event.listens_for(ClassifiedTransaction, 'after_delete')
def auto_refresh_taxes(mapper, connection, target):
    """Refresh clinic taxes when classified transactions change."""
    if not has_request_context():
        return
    
    if not target.clinic_id or not target.month:
        return
    
    # Rate limit: don't refresh same clinic/month more than once per 60 seconds
    key = f"{target.clinic_id}:{target.month}"
    last_refresh = _tax_refresh_cooldown.get(key)
    
    if last_refresh and (datetime.utcnow() - last_refresh).total_seconds() < 60:
        return
    
    try:
        from services.finance import _refresh_clinic_taxes
        _refresh_clinic_taxes(target.clinic_id, target.month)
        _tax_refresh_cooldown[key] = datetime.utcnow()
        
    except Exception as e:
        current_app.logger.warning(f"Tax refresh failed for clinic {target.clinic_id}: {e}")


# Update ClassifiedTransaction when BlocoOrcamento discount changes
@event.listens_for(BlocoOrcamento, 'after_update')
def sync_bloco_discount_change(mapper, connection, target):
    """Update CT value when BlocoOrcamento discount changes."""
    if not has_request_context():
        return
    
    # Find matching CT
    raw_id = f"bloco_orcamento:{target.id}"
    
    ct = ClassifiedTransaction.query.filter_by(
        origin=ClassificationOrigin.BLOCO_ORCAMENTO,
        raw_id=raw_id
    ).first()
    
    if not ct:
        return
    
    new_value = target.total_liquido or target.total
    new_value = _quantize_currency(Decimal(str(new_value or 0)))
    
    if ct.value != new_value:
        old_value = ct.value
        
        # Create adjustment record
        adjustment = BlocoOrcamentoAdjustment(
            bloco_id=target.id,
            previous_value=old_value,
            new_value=new_value,
            reason='discount_change',
            adjusted_at=now_in_brazil()
        )
        db.session.add(adjustment)
        
        # Update CT
        ct.value = new_value
        ct.reclassified_at = now_in_brazil()
        db.session.add(ct)
        
        # Audit log
        from services.finance import _audit_classified_transaction
        _audit_classified_transaction(
            ct,
            'updated',
            reason=f"Discount change: {old_value} → {new_value}"
        )
        
        # Alert if large change
        if old_value != 0:
            pct_change = abs((new_value - old_value) / old_value * 100)
            if pct_change > 10:
                notification = ClinicNotification(
                    clinic_id=target.clinica_id,
                    month=target.data_criacao.date().replace(day=1),
                    title=f"Ajuste grande no bloco de orçamento (±{pct_change:.0f}%)",
                    message=f"Bloco #{target.id}: R$ {old_value} → R$ {new_value}",
                    type='warning',
                    category=ClinicNotificationCategory.AUDIT,
                    related_id=ct.id
                )
                db.session.add(notification)
```

### 4.2 New Model: BlocoOrcamentoAdjustment

```python
# Add to models.py

class BlocoOrcamentoAdjustment(db.Model):
    __tablename__ = 'bloco_orcamento_adjustments'

    id = db.Column(db.Integer, primary_key=True)
    bloco_id = db.Column(db.Integer, db.ForeignKey('bloco_orcamento.id', ondelete='CASCADE'), nullable=False)
    previous_value = db.Column(db.Numeric(14, 2), nullable=False)
    new_value = db.Column(db.Numeric(14, 2), nullable=False)
    reason = db.Column(db.String(50), nullable=False)  # 'discount_change', 'item_removed', etc
    adjusted_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    adjusted_at = db.Column(db.DateTime(timezone=True), default=now_in_brazil, nullable=False)

    bloco = db.relationship('BlocoOrcamento', backref=db.backref('adjustments', cascade='all, delete-orphan'))
    adjusted_by = db.relationship('User')

    def __repr__(self):
        return f"<Adjustment Bloco#{self.bloco_id} {self.previous_value} → {self.new_value}>"
```

---

## 5. Database Migrations

### 5.1 Migration: Add new fields to classified_transactions

```python
# migrations/versions/xxx_add_accounting_enums.py

from alembic import op
import sqlalchemy as sa

def upgrade():
    # Create enums
    classification_origin_enum = sa.Enum(
        'pj_payment', 'orcamento', 'bloco_orcamento', 'consulta', 
        'manual', 'insurance', 'refund',
        name='classification_origin'
    )
    classification_origin_enum.create(op.get_bind())
    
    pj_payment_status_enum = sa.Enum(
        'pendente', 'recebido_nf', 'parcial', 'pago', 'vencido', 'cancelado', 'reembolsado',
        name='pj_payment_status'
    )
    pj_payment_status_enum.create(op.get_bind())
    
    notification_category_enum = sa.Enum(
        'tax_liability', 'unprocessed_payment', 'classification_delay', 
        'missing_invoice', 'orphaned_schedule', 'reconciliation', 'audit',
        'insurance_claim', 'vendor_overdue',
        name='notification_category'
    )
    notification_category_enum.create(op.get_bind())
    
    # Add columns to classified_transactions
    op.add_column('classified_transactions', 
                  sa.Column('created_by_id', sa.Integer(), nullable=True))
    op.add_column('classified_transactions', 
                  sa.Column('created_by_method', sa.String(20), nullable=True))
    op.add_column('classified_transactions', 
                  sa.Column('reclassified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('classified_transactions', 
                  sa.Column('coverage_id', sa.Integer(), nullable=True))
    op.add_column('classified_transactions', 
                  sa.Column('payer_type', sa.String(20), nullable=True))
    op.add_column('classified_transactions', 
                  sa.Column('insurance_claim_id', sa.Integer(), nullable=True))
    op.add_column('classified_transactions', 
                  sa.Column('consulta_id', sa.Integer(), nullable=True))
    
    # Add FK constraints
    op.create_foreign_key('fk_ct_created_by', 'classified_transactions', 'user',
                         ['created_by_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_ct_coverage', 'classified_transactions', 'health_coverage',
                         ['coverage_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_ct_consulta', 'classified_transactions', 'consulta',
                         ['consulta_id'], ['id'], ondelete='SET NULL')
    
    # Add columns to pj_payments
    op.add_column('pj_payments', 
                  sa.Column('payment_id', sa.Integer(), nullable=True))
    op.add_column('pj_payments', 
                  sa.Column('payment_reference', sa.String(255), nullable=True))
    op.add_column('pj_payments', 
                  sa.Column('allocated_at', sa.DateTime(timezone=True), nullable=True))
    
    op.create_foreign_key('fk_pj_payment', 'pj_payments', 'payment',
                         ['payment_id'], ['id'], ondelete='SET NULL')
    
    # Add columns to clinic_taxes
    op.add_column('clinic_taxes', 
                  sa.Column('recalculated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('clinic_taxes', 
                  sa.Column('previous_liability', sa.Numeric(14, 2), nullable=True))
    
    # Add columns to clinic_notifications
    op.add_column('clinic_notifications', 
                  sa.Column('category', notification_category_enum, nullable=True))
    op.add_column('clinic_notifications', 
                  sa.Column('metadata', sa.JSON(), nullable=True))
    op.add_column('clinic_notifications', 
                  sa.Column('related_id', sa.Integer(), nullable=True))
    
    # Create audit table
    op.create_table(
        'classified_transaction_audit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('old_value', sa.JSON(), nullable=True),
        sa.Column('new_value', sa.JSON(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['transaction_id'], ['classified_transactions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_cta_transaction_id', 'transaction_id'),
    )
    
    # Create adjustment table
    op.create_table(
        'bloco_orcamento_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bloco_id', sa.Integer(), nullable=False),
        sa.Column('previous_value', sa.Numeric(14, 2), nullable=False),
        sa.Column('new_value', sa.Numeric(14, 2), nullable=False),
        sa.Column('reason', sa.String(50), nullable=False),
        sa.Column('adjusted_by_id', sa.Integer(), nullable=True),
        sa.Column('adjusted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['bloco_id'], ['bloco_orcamento.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['adjusted_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_boa_bloco_id', 'bloco_id'),
    )


def downgrade():
    # Reverse migrations...
    op.drop_table('bloco_orcamento_adjustments')
    op.drop_table('classified_transaction_audit')
    # ... etc
```

---

## 6. API Endpoints

### 6.1 Add to app.py

```python
from flask import jsonify, request

# Endpoint to force classification
@app.route('/api/contabilidade/classify', methods=['POST'])
@login_required
def api_classify_transactions():
    """Force reclassification of transactions for a period."""
    
    _ensure_accounting_access()
    
    data = request.get_json() or {}
    clinic_id = data.get('clinic_id', type=int)
    month_str = data.get('month')  # YYYY-MM
    origin = data.get('origin')  # optional filter
    
    if not clinic_id or not month_str:
        return jsonify({'error': 'clinic_id and month required'}), 400
    
    try:
        month_date = datetime.strptime(month_str, '%Y-%m').date().replace(day=1)
    except ValueError:
        return jsonify({'error': 'Invalid month format (use YYYY-MM)'}), 400
    
    from services.finance import classify_transactions_for_month
    
    count = classify_transactions_for_month(clinic_id, month_date)
    
    return jsonify({
        'success': True,
        'clinic_id': clinic_id,
        'month': month_str,
        'transactions_processed': count
    })


# Endpoint for reconciliation
@app.route('/api/contabilidade/reconcile', methods=['GET'])
@login_required
def api_reconcile():
    """Compare payments vs classified transactions."""
    
    _ensure_accounting_access()
    
    clinic_id = request.args.get('clinic_id', type=int)
    month_str = request.args.get('month')
    
    if not clinic_id or not month_str:
        return jsonify({'error': 'clinic_id and month required'}), 400
    
    try:
        month_date = datetime.strptime(month_str, '%Y-%m').date().replace(day=1)
    except ValueError:
        return jsonify({'error': 'Invalid month format'}), 400
    
    end_date = month_date + relativedelta(months=1)
    
    # Get payment totals
    payment_total = db.session.query(
        func.coalesce(func.sum(Payment.amount), 0)
    ).filter(
        Payment.user_id.in_(
            db.session.query(ClinicStaff.user_id).filter(
                ClinicStaff.clinic_id == clinic_id
            )
        ),
        Payment.created_at >= month_date,
        Payment.created_at < end_date
    ).scalar() or Decimal('0')
    
    # Get CT totals
    ct_total = db.session.query(
        func.coalesce(func.sum(ClassifiedTransaction.value), 0)
    ).filter(
        ClassifiedTransaction.clinic_id == clinic_id,
        ClassifiedTransaction.month == month_date
    ).scalar() or Decimal('0')
    
    discrepancy = Decimal(str(payment_total or 0)) - Decimal(str(ct_total or 0))
    
    return jsonify({
        'month': month_str,
        'payment_total': str(payment_total),
        'classified_total': str(ct_total),
        'discrepancy': str(discrepancy),
        'matches': discrepancy == 0
    })


# Endpoint for audit trail
@app.route('/api/contabilidade/audit/<int:transaction_id>', methods=['GET'])
@login_required
def api_audit_transaction(transaction_id):
    """Get audit trail for a classified transaction."""
    
    _ensure_accounting_access()
    
    ct = ClassifiedTransaction.query.get(transaction_id)
    if not ct:
        return jsonify({'error': 'Transaction not found'}), 404
    
    # Verify access
    if not _user_can_access_clinic(current_user, ct.clinic_id):
        return jsonify({'error': 'Access denied'}), 403
    
    audit_logs = ClassifiedTransactionAudit.query.filter_by(
        transaction_id=transaction_id
    ).order_by(ClassifiedTransactionAudit.created_at.desc()).all()
    
    return jsonify({
        'transaction': {
            'id': ct.id,
            'origin': ct.origin.value,
            'category': ct.category,
            'value': str(ct.value),
            'description': ct.description,
            'created_at': ct.created_at.isoformat(),
        },
        'audit_trail': [
            {
                'action': log.action,
                'user': log.user.name if log.user else 'System',
                'timestamp': log.created_at.isoformat(),
                'reason': log.reason,
                'changes': {
                    'old': log.old_value,
                    'new': log.new_value
                }
            }
            for log in audit_logs
        ]
    })
```

---

## 7. Tests

### 7.1 Unit tests for accounting gaps

```python
# tests/test_accounting_gaps.py

import pytest
from datetime import date, datetime
from decimal import Decimal
from models import (
    Consulta, Orcamento, OrcamentoItem, BlocoOrcamento,
    PJPayment, PlantonistaEscala, ClassifiedTransaction,
    ClinicTaxes, ClinicNotification, Payment, Clinica
)
from services.finance import (
    _sync_consulta_classification,
    _sync_payment_classification,
    _refresh_clinic_taxes
)


def test_consulta_creates_classified_transaction(app):
    """Verify Consulta → ClassifiedTransaction sync."""
    with app.app_context():
        # Create clinic
        clinic = Clinica(nome="Test Clinic", cnpj="00.000.000/0000-00")
        db.session.add(clinic)
        db.session.flush()
        
        # Create consulta
        consulta = Consulta(
            clinica_id=clinic.id,
            status='pending'
        )
        db.session.add(consulta)
        db.session.flush()
        
        # Add items
        item = OrcamentoItem(
            consulta_id=consulta.id,
            descricao="Test service",
            valor=Decimal('100.00'),
            clinica_id=clinic.id
        )
        db.session.add(item)
        db.session.commit()
        
        # Mark complete
        consulta.status = 'completed'
        db.session.commit()
        
        # Verify CT created
        ct = ClassifiedTransaction.query.filter_by(
            consulta_id=consulta.id
        ).first()
        
        assert ct is not None
        assert ct.value == Decimal('100.00')
        assert ct.category == 'receita_servico'
        assert ct.origin.value == 'consulta'


def test_plantonista_escala_auto_creates_payment(app):
    """Verify PlantonistaEscala → PJPayment auto-link."""
    with app.app_context():
        clinic = Clinica(nome="Test", cnpj="00.000.000/0000-00")
        db.session.add(clinic)
        db.session.flush()
        
        escala = PlantonistaEscala(
            clinic_id=clinic.id,
            medico_nome="Dr. Test",
            medico_cnpj="00.000.000/0001-00",
            turno="Noturno",
            inicio=datetime(2024, 5, 15, 20, 0),
            fim=datetime(2024, 5, 16, 8, 0),
            valor_previsto=Decimal('500.00'),
            status='agendado'
        )
        db.session.add(escala)
        db.session.flush()
        
        # Confirm
        escala.status = 'confirmado'
        db.session.commit()
        
        # Verify payment created
        assert escala.pj_payment_id is not None
        payment = PJPayment.query.get(escala.pj_payment_id)
        assert payment is not None
        assert payment.valor == Decimal('500.00')
        assert payment.prestador_nome == "Dr. Test"


def test_tax_refresh_on_transaction_change(app):
    """Verify ClinicTaxes auto-recalculates."""
    with app.app_context():
        clinic = Clinica(nome="Test", cnpj="00.000.000/0000-00")
        db.session.add(clinic)
        db.session.flush()
        
        month = date(2024, 5, 1)
        
        # Create initial taxes
        taxes = ClinicTaxes(
            clinic_id=clinic.id,
            month=month,
            iss_total=Decimal('500.00')
        )
        db.session.add(taxes)
        db.session.commit()
        
        # Add revenue transaction
        ct = ClassifiedTransaction(
            clinic_id=clinic.id,
            date=datetime(2024, 5, 15),
            month=month,
            origin=ClassificationOrigin.CONSULTA,
            raw_id="test:1",
            description="Test",
            value=Decimal('1000.00'),
            category='receita_servico'
        )
        db.session.add(ct)
        db.session.commit()
        
        # Verify taxes were recalculated
        taxes = db.session.query(ClinicTaxes).get(taxes.id)
        assert taxes.recalculated_at is not None
        assert taxes.iss_total == Decimal('50.00')  # 5% of 1000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

---

This provides a complete, production-ready implementation framework. Adapt to your specific requirements and test thoroughly before deploying to production.

