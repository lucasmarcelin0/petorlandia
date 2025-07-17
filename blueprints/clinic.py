from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user
from models import Consulta, Animal, TipoRacao, Species, Breed
from extensions import db

clinic_bp = Blueprint('clinic', __name__)

@clinic_bp.route('/consulta/<int:animal_id>')
@login_required
def consulta_direct(animal_id):
    if current_user.worker not in ['veterinario', 'colaborador']:
        abort(403)
    animal = Animal.query.get_or_404(animal_id)
    tutor = animal.owner
    edit_id = request.args.get('c', type=int)
    edit_mode = False
    if current_user.worker == 'veterinario':
        if edit_id:
            consulta = Consulta.query.get_or_404(edit_id)
            edit_mode = True
        else:
            consulta = Consulta.query.filter_by(animal_id=animal.id, status='in_progress').first()
            if not consulta:
                consulta = Consulta(animal_id=animal.id, created_by=current_user.id, status='in_progress')
                db.session.add(consulta)
                db.session.commit()
    else:
        consulta = None
    historico = []
    if current_user.worker == 'veterinario':
        historico = Consulta.query.filter_by(animal_id=animal.id, status='finalizada').order_by(Consulta.created_at.desc()).all()
    tipos_racao = TipoRacao.query.order_by(TipoRacao.marca.asc()).all()
    marcas_existentes = sorted(set([t.marca for t in tipos_racao if t.marca]))
    linhas_existentes = sorted(set([t.linha for t in tipos_racao if t.linha]))
    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()
    return render_template('consulta_qr.html', animal=animal, tutor=tutor, consulta=consulta,
                           historico_consultas=historico, edit_mode=edit_mode, worker=current_user.worker,
                           tipos_racao=tipos_racao, marcas_existentes=marcas_existentes,
                           linhas_existentes=linhas_existentes, species_list=species_list, breed_list=breed_list)

@clinic_bp.route('/finalizar_consulta/<int:consulta_id>', methods=['POST'])
@login_required
def finalizar_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem finalizar consultas.', 'danger')
        return redirect(url_for('index'))
    consulta.status = 'finalizada'
    db.session.commit()
    flash('Consulta finalizada e registrada no histórico!', 'success')
    return redirect(url_for('clinic.consulta_direct', animal_id=consulta.animal_id))

@clinic_bp.route('/consulta/<int:consulta_id>/deletar', methods=['POST'])
@login_required
def deletar_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    animal_id = consulta.animal_id
    if current_user.worker != 'veterinario':
        flash('Apenas veterinários podem excluir consultas.', 'danger')
        return redirect(url_for('index'))
    db.session.delete(consulta)
    db.session.commit()
    flash('Consulta excluída!', 'info')
    return redirect(url_for('clinic.consulta_direct', animal_id=animal_id))

@clinic_bp.route('/imprimir_consulta/<int:consulta_id>')
@login_required
def imprimir_consulta(consulta_id):
    consulta = Consulta.query.get_or_404(consulta_id)
    animal = consulta.animal
    tutor = animal.owner
    clinica = current_user.veterinario.clinica if current_user.veterinario else None
    return render_template('imprimir_consulta.html', consulta=consulta, animal=animal, tutor=tutor, clinica=clinica)
