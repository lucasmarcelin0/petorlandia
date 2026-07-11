"""Agendamentos (o AppointmentForm final é o vigente).

Extraído de forms.py na modularização (2026-07-10).
"""
from flask_wtf import FlaskForm
from sqlalchemy import or_, false
from datetime import date
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    SelectMultipleField,
    RadioField,
    PasswordField,
    SubmitField,
    BooleanField,
    DecimalField,
    IntegerField,
    DateField,
    DateTimeField,
    TimeField,
    HiddenField,
    EmailField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    NumberRange,
    ValidationError,
)
# Some deployments might not have ``wtforms_sqlalchemy`` available. In that
# case we fall back to the compatible field that ships with Flask-Admin to
# avoid crashing the application when importing the forms module.
try:  # pragma: no cover - import guard
    from wtforms_sqlalchemy.fields import QuerySelectField
except ImportError:  # pragma: no cover - executed only when optional dep missing
    from flask_admin.contrib.sqla.fields import QuerySelectField
from flask_wtf.file import FileField, FileAllowed
try:
    from document_utils import format_cnpj, only_digits
except ImportError:
    from .document_utils import format_cnpj, only_digits
from models import PLANTONISTA_ESCALA_STATUS_CHOICES
from models import PRODUCT_CATEGORY_CHOICES




class AppointmentForm(FlaskForm):
    veterinario_id = SelectField('Veterinário', coerce=int, validators=[DataRequired()])
    scheduled_at = DateTimeField('Data e Hora', format='%Y-%m-%d %H:%M', validators=[DataRequired()])
    description = TextAreaField('Descrição', validators=[Optional()])
    submit = SubmitField('Agendar')


class AppointmentDeleteForm(FlaskForm):
    submit = SubmitField('Excluir')


class AppointmentRequestForm(FlaskForm):
    """Solicitação de agendamento pelo tutor — sem acesso à agenda do profissional."""

    animal_id = SelectField('Pet', coerce=int, validators=[DataRequired()], validate_choice=False)
    kind = SelectField(
        'Tipo de atendimento',
        choices=[('consulta', 'Consulta'), ('exame', 'Exame'), ('vacina', 'Vacina')],
        default='consulta',
        validators=[DataRequired()],
    )
    mode = SelectField(
        'Local',
        choices=[('clinica', 'Na clínica'), ('domicilio', 'A domicílio')],
        default='clinica',
        validators=[DataRequired()],
    )
    preferred_date = DateField('Data preferida', format='%Y-%m-%d', validators=[DataRequired()])
    preferred_time = TimeField('Horário preferido (opcional)', format='%H:%M', validators=[Optional()])
    notes = TextAreaField('Observações (opcional)', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Enviar solicitação')


class AppointmentRequestResponseForm(FlaskForm):
    """Resposta do profissional a uma solicitação (confirmar/recusar)."""

    date = DateField('Data', format='%Y-%m-%d', validators=[Optional()])
    time = TimeField('Horário', format='%H:%M', validators=[Optional()])
    response_note = TextAreaField('Mensagem ao tutor (opcional)', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Confirmar')


APPOINTMENT_KIND_CHOICES = [
    ('consulta', 'Consulta'),
    ('retorno', 'Retorno'),
    ('exame', 'Exame'),
    ('banho_tosa', 'Banho e Tosa'),
    ('vacina', 'Vacina'),
]


class AppointmentForm(FlaskForm):
    """Formulário para agendamento de consultas."""

    tutor_id = SelectField(
        'Tutor',
        coerce=int,
        validators=[Optional()],
        default=0,
    )

    animal_id = SelectField(
        'Animal',
        coerce=int,
        validators=[DataRequired()],
        validate_choice=False,
    )

    veterinario_id = SelectField(
        'Veterinário',
        coerce=int,
        validators=[DataRequired()],
        validate_choice=False,
    )

    date = DateField(
        'Data',
        validators=[DataRequired()],
        format='%Y-%m-%d',
    )

    time = TimeField(
        'Horário',
        format='%H:%M',
        validators=[DataRequired()],
    )

    kind = SelectField(
        'Tipo',
        choices=APPOINTMENT_KIND_CHOICES,
        validators=[DataRequired()],
        default='consulta',
    )

    reason = TextAreaField(
        'Motivo',
        validators=[Optional(), Length(max=500)],
    )

    submit = SubmitField('Agendar')

    animal_data = None

    def populate_animals(
        self,
        animals,
        *,
        restrict_tutors=False,
        selected_tutor_id=None,
        allow_all_option=True,
    ):
        """Populate animal choices and tutor selector metadata."""

        def _normalize_tutor_name(name, tutor_id):
            if name:
                return name
            if tutor_id:
                return f'Tutor #{tutor_id}'
            return 'Tutor não atribuído'

        records = []
        tutor_map = {}
        for animal in animals:
            tutor_id = getattr(animal, 'user_id', None)
            owner = getattr(animal, 'owner', None)
            tutor_name = getattr(owner, 'name', None)
            animal_id = getattr(animal, 'id', None)
            if animal_id is None:
                continue
            record = {
                'id': animal_id,
                'name': getattr(animal, 'name', None) or f'Animal #{animal_id}',
                'tutor_id': tutor_id,
                'tutor_name': _normalize_tutor_name(tutor_name, tutor_id),
            }
            records.append(record)
            if tutor_id:
                tutor_map[tutor_id] = _normalize_tutor_name(tutor_name, tutor_id)

        def _format_animal_label(item):
            name = item.get('name') or f"Animal #{item.get('id', '—')}"
            tutor_name = item.get('tutor_name')
            if tutor_name:
                return f"{name} — {tutor_name}"
            return name

        records.sort(key=lambda item: ((item['name'] or '').lower(), item['id']))
        self.animal_data = records
        self.animal_id.choices = [
            (item['id'], _format_animal_label(item)) for item in records
        ]

        if not hasattr(self, 'tutor_id'):
            return

        sorted_tutors = sorted(
            tutor_map.items(),
            key=lambda entry: (entry[1] or '').lower(),
        )

        choices = []
        if allow_all_option and (not restrict_tutors or len(sorted_tutors) > 1):
            choices.append((0, 'Todos os tutores'))
        choices.extend(
            (tutor_id, name or f'Tutor #{tutor_id}')
            for tutor_id, name in sorted_tutors
        )

        if not choices:
            if allow_all_option:
                choices = [(0, 'Todos os tutores')]
            else:
                choices = [(0, 'Nenhum tutor disponível')]

        self.tutor_id.choices = choices

        available_ids = {choice[0] for choice in choices}
        resolved_tutor_id = selected_tutor_id if selected_tutor_id in available_ids else None
        if resolved_tutor_id is None:
            if restrict_tutors and sorted_tutors:
                resolved_tutor_id = sorted_tutors[0][0]
            elif 0 in available_ids:
                resolved_tutor_id = 0
            elif sorted_tutors:
                resolved_tutor_id = sorted_tutors[0][0]
            else:
                resolved_tutor_id = 0

        self.tutor_id.data = resolved_tutor_id

    def __init__(
        self,
        tutor=None,
        is_veterinario=False,
        clinic_ids=None,
        *args,
        **kwargs,
    ):
        self._restricted_tutor_id = getattr(tutor, 'id', None)
        self._clinic_scope_ids = []
        require_clinic_scope = kwargs.pop('require_clinic_scope', None)
        if clinic_ids is not None:
            if isinstance(clinic_ids, (list, tuple, set)):
                candidates = clinic_ids
            else:
                candidates = [clinic_ids]
            for candidate in candidates:
                try:
                    value = int(candidate)
                except (TypeError, ValueError):
                    continue
                if value and value not in self._clinic_scope_ids:
                    self._clinic_scope_ids.append(value)
        self._clinic_scope_ids = [cid for cid in self._clinic_scope_ids if cid]
        if require_clinic_scope is None:
            require_clinic_scope = bool(is_veterinario)
        self._clinic_scope_required = bool(require_clinic_scope)
        self._is_veterinario_context = bool(is_veterinario)
        super().__init__(*args, **kwargs)
        from models import Animal, Veterinario, Clinica

        self._restricted_tutor_id = getattr(tutor, 'id', None)

        def _build_animal_query():
            query = Animal.query.filter(Animal.removido_em.is_(None))
            if self._clinic_scope_required and not self._clinic_scope_ids:
                return query.filter(false())
            if self._clinic_scope_ids:
                query = query.filter(Animal.clinica_id.in_(self._clinic_scope_ids))
            if self._restricted_tutor_id is not None:
                query = query.filter(Animal.user_id == self._restricted_tutor_id)
            return query

        def _build_veterinarian_query():
            query = Veterinario.query
            if self._clinic_scope_ids:
                query = query.filter(
                    or_(
                        Veterinario.clinica_id.in_(self._clinic_scope_ids),
                        Veterinario.clinicas.any(Clinica.id.in_(self._clinic_scope_ids)),
                    )
                )
            return query

        self._animal_query_factory = _build_animal_query
        self._veterinarian_query_factory = _build_veterinarian_query

        selected_animal_id = self.animal_id.data
        animal_query = self._animal_query_factory()
        if selected_animal_id:
            animals = animal_query.filter(Animal.id == selected_animal_id).all()
        else:
            animals = animal_query.all()

        restrict_tutors = self._restricted_tutor_id is not None
        allow_all = not restrict_tutors
        selected_tutor_id = None
        if restrict_tutors:
            selected_tutor_id = self._restricted_tutor_id
        elif animals:
            selected_tutor_id = getattr(animals[0], 'user_id', None)
        else:
            selected_tutor_id = self.tutor_id.data

        self.populate_animals(
            animals,
            restrict_tutors=restrict_tutors,
            selected_tutor_id=selected_tutor_id,
            allow_all_option=allow_all,
        )

        selected_vet_id = self.veterinario_id.data
        veterinarian_query = self._veterinarian_query_factory()
        if selected_vet_id:
            veterinarios = veterinarian_query.filter(Veterinario.id == selected_vet_id).all()
        else:
            veterinarios = veterinarian_query.all()

        def _vet_label(vet):
            return getattr(getattr(vet, 'user', None), 'name', None) or str(vet.id)

        self.veterinario_id.choices = [
            (v.id, _vet_label(v)) for v in veterinarios
        ]

        if selected_vet_id and selected_vet_id not in {choice[0] for choice in self.veterinario_id.choices}:
            vet = Veterinario.query.get(selected_vet_id)
            if vet:
                self.veterinario_id.choices.append((vet.id, _vet_label(vet)))

        if not self.kind.data:
            self.kind.data = 'consulta'

    def _animal_lookup_query(self):
        from models import Animal

        query = Animal.query.filter(Animal.removido_em.is_(None))
        if self._clinic_scope_required and not self._clinic_scope_ids:
            return query.filter(false())
        if self._clinic_scope_ids:
            query = query.filter(Animal.clinica_id.in_(self._clinic_scope_ids))
        if self._restricted_tutor_id is not None:
            query = query.filter(Animal.user_id == self._restricted_tutor_id)
        return query

    def _veterinarian_lookup_query(self):
        from models import Veterinario, Clinica

        query = Veterinario.query
        if self._clinic_scope_ids:
            query = query.filter(
                or_(
                    Veterinario.clinica_id.in_(self._clinic_scope_ids),
                    Veterinario.clinicas.any(Clinica.id.in_(self._clinic_scope_ids)),
                )
            )
        return query

    def validate_animal_id(self, field):
        if not field.data:
            raise ValidationError('Selecione um animal válido.')

        query = self._animal_lookup_query()
        from models import Animal

        animal = query.filter(Animal.id == field.data).first()
        if not animal:
            raise ValidationError('Selecione um animal válido para esta clínica.')

    def validate_veterinario_id(self, field):
        if not field.data:
            raise ValidationError('Selecione um veterinário válido.')

        query = self._veterinarian_lookup_query()
        from models import Veterinario

        veterinario = query.filter(Veterinario.id == field.data).first()
        if not veterinario:
            raise ValidationError('Selecione um veterinário válido para esta clínica.')

