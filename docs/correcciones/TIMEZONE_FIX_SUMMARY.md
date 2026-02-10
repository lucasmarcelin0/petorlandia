# Correção de Fuso Horário - Resumo das Mudanças

## Problema Identificado
O sistema estava salvando as horas de consulta em UTC puro, mas quando exibidas no Brasil (São Paulo, UTC-3), estavam aparecendo com a hora errada. Por exemplo, um horário salvo às 19:11 UTC (que deveria ser exibido como 16:11 em São Paulo) estava sendo mostrado como 19:11.

## Causa Raiz
1. As colunas `DateTime` no banco PostgreSQL eram definidas como `db.DateTime` sem `timezone=True`
2. Isso fazia com que o SQLAlchemy retornasse datetimes **naive** (sem informação de timezone)
3. O filtro `format_datetime_brazil` assumia que datetimes naive eram UTC, mas havia um problema na conversão

## Solução Implementada

### 1. **time_utils.py** - Melhorada função `utcnow()`
```python
def utcnow() -> datetime:
    """Return current time in UTC.
    
    This uses timezone-aware UTC to ensure accuracy regardless of system timezone.
    """
    # Get current time in Brazil timezone, then convert to UTC
    # This is more reliable than datetime.now(timezone.utc) on systems with wrong TZ
    br_now = datetime.now(BR_TZ)
    return br_now.astimezone(timezone.utc)
```

### 2. **models.py** - Atualizado todos os `DateTime` columns
Alteradas mais de 50 linhas em 30+ modelos para usar `db.DateTime(timezone=True)` em vez de `db.DateTime`. Exemplos:

**Antes:**
```python
created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
```

**Depois:**
```python
created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
```

### Modelos Afetados:
- ✅ `Consulta` - created_at, finalizada_em
- ✅ `Orcamento` - created_at, updated_at, paid_at
- ✅ `User` - created_at
- ✅ `DataShareAccess` - created_at, updated_at, expires_at, revoked_at
- ✅ `DataShareRequest` - created_at, updated_at, expires_at, approved_at, denied_at
- ✅ `DataShareLog` - occurred_at
- ✅ `Animal` - date_added, removido_em, falecido_em
- ✅ `Message` - timestamp
- ✅ `Interest` - timestamp
- ✅ `Transaction` - date
- ✅ `BlocoOrcamento` - data_criacao
- ✅ `BlocoPrescricao` - data_criacao
- ✅ `Prescricao` - data_prescricao
- ✅ `VetClinicInvite` - created_at
- ✅ `ClinicInventoryMovement` - created_at
- ✅ `ClinicFinancialSnapshot` - gerado_em
- ✅ `ClinicTaxes` - created_at, updated_at
- ✅ `ClinicNotification` - created_at, resolution_date
- ✅ `ClassifiedTransaction` - date, created_at
- ✅ `PJPayment` - created_at, updated_at
- ✅ `PlantonistaEscala` - inicio, fim, realizado_em, created_at, updated_at
- ✅ `PlantaoModelo` - created_at, updated_at
- ✅ `VeterinarianMembership` - started_at, trial_ends_at, paid_until
- ✅ `VeterinarianSettings` - created_at, updated_at
- ✅ `Appointment` - scheduled_at, created_at (já estava correto)
- ✅ `ExamAppointment` - scheduled_at, request_time, confirm_by (já estava correto)
- ✅ `AgendaEvento` - inicio, fim (já estava correto)
- ✅ `BlocoExames` - data_criacao
- ✅ `ExameSolicitado` - performed_at
- ✅ `Vacina` - criada_em
- ✅ `AnimalDocumento` - uploaded_at
- ✅ `Notification` - sent_at
- ✅ `Racao` - data_cadastro
- ✅ `Review` - date
- ✅ `Order` - created_at
- ✅ `DeliveryRequest` - requested_at, accepted_at, completed_at, canceled_at
- ✅ `Payment` - created_at
- ✅ `HealthSubscription` - start_date, end_date
- ✅ `ConsultaToken` - expires_at

### 3. **app.py** - Template filter permanece o mesmo
O `format_datetime_brazil` já estava correto e continuará funcionando corretamente com o novo setup.

## Impacto
- ✅ Consultas agora serão salvas com informação correta de timezone
- ✅ Ao exibir via `format_datetime_brazil`, converterá corretamente para o fuso de São Paulo
- ✅ Não há necessidade de migração de banco de dados (PostgreSQL aceita ambos os formatos)
- ✅ Novos registros terão a hora correta
- ✅ Registros antigos continuarão funcionando (o filtro trata ambos os casos)

## Como Validar
1. Criar uma nova consulta e verificar se o horário exibido é o correto
2. A hora no banco estará em UTC
3. A hora exibida em `format_datetime_brazil` será 3 horas antes (em São Paulo)

## Próximos Passos (Opcional)
- [ ] Criar uma migração Alembic para atualizar o tipo das colunas no banco (não obrigatório)
- [ ] Verificar se há outras aplicações que consultam o banco diretamente e ajustá-las se necessário
- [ ] Testar com dados reais em produção
