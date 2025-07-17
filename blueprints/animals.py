from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
try:
    from models import Animal, Species, Breed, Message, Interest
    from forms import AnimalForm, MessageForm
    from extensions import db
    from s3_utils import upload_to_s3
except ImportError:  # pragma: no cover - fallback for package imports
    from ..models import Animal, Species, Breed, Message, Interest
    from ..forms import AnimalForm, MessageForm
    from ..extensions import db
    from ..s3_utils import upload_to_s3
import uuid

animals_bp = Blueprint('animals', __name__)

@animals_bp.route('/add-animal', methods=['GET', 'POST'])
@login_required
def add_animal():
    form = AnimalForm()
    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()
    if form.validate_on_submit():
        image_url = None
        if form.image.data:
            file = form.image.data
            original_filename = secure_filename(file.filename)
            filename = f"{uuid.uuid4().hex}_{original_filename}"
            image_url = upload_to_s3(file, filename, folder='animals')
        species_id = request.form.get('species_id', type=int)
        breed_id = request.form.get('breed_id', type=int)
        animal = Animal(
            name=form.name.data,
            species_id=species_id,
            breed_id=breed_id,
            age=form.age.data,
            sex=form.sex.data,
            description=form.description.data,
            image=image_url,
            modo=form.modo.data,
            price=form.price.data if form.modo.data == 'venda' else None,
            status='disponível',
            owner=current_user,
            is_alive=True
        )
        db.session.add(animal)
        db.session.commit()
        flash('Animal cadastrado com sucesso!', 'success')
        return redirect(url_for('animals.list_animals'))
    return render_template('add_animal.html', form=form, species_list=species_list, breed_list=breed_list)

@animals_bp.route('/animals')
def list_animals():
    page = request.args.get('page', 1, type=int)
    per_page = 9
    modo = request.args.get('modo')
    query = Animal.query.filter(Animal.removido_em == None)
    if modo and modo.lower() != 'todos':
        query = query.filter_by(modo=modo)
    else:
        if not current_user.is_authenticated or current_user.worker not in ['veterinario', 'colaborador']:
            query = query.filter(Animal.modo != 'adotado')
    query = query.order_by(Animal.date_added.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    animals = pagination.items
    return render_template('animals.html', animals=animals, page=page, total_pages=pagination.pages, modo=modo)

@animals_bp.route('/animal/<int:animal_id>/adotar', methods=['POST'])
@login_required
def adotar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.status != 'disponível':
        flash('Este animal já foi adotado ou vendido.', 'danger')
        return redirect(url_for('animals.list_animals'))
    animal.status = 'adotado'
    animal.user_id = current_user.id
    db.session.commit()
    flash(f'Você adotou {animal.name} com sucesso!', 'success')
    return redirect(url_for('animals.list_animals'))

@animals_bp.route('/animal/<int:animal_id>/editar', methods=['GET', 'POST'])
@animals_bp.route('/editar_animal/<int:animal_id>', methods=['GET', 'POST'])
@login_required
def editar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.user_id != current_user.id:
        flash('Você não tem permissão para editar este animal.', 'danger')
        return redirect(url_for('auth.profile'))
    form = AnimalForm(obj=animal)
    species_list = Species.query.order_by(Species.name).all()
    breed_list = Breed.query.order_by(Breed.name).all()
    if form.validate_on_submit():
        form.populate_obj(animal)
        species_id = request.form.get('species_id')
        breed_id = request.form.get('breed_id')
        if species_id:
            animal.species_id = int(species_id)
        if breed_id:
            animal.breed_id = int(breed_id)
        db.session.commit()
        flash('Animal atualizado com sucesso!', 'success')
        return redirect(url_for('auth.profile'))
    return render_template('editar_animal.html', form=form, animal=animal, species_list=species_list, breed_list=breed_list)
