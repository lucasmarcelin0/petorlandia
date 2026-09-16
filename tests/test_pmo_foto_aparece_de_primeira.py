"""Contratos da foto na tela de vacinação: aparecer de primeira, no animal certo.

Em campo apareceram três sintomas que têm a mesma raiz — a lista inteira é
reescrita (``innerHTML``) a cada ``render()``, e um ``render()`` dispara sozinho
a cada 3 s pela sincronização em tempo real:

1. "tenho que adicionar a foto duas vezes": o ``<input type="file">`` ficava
   DENTRO da lista. O app da câmera voltava e escrevia o arquivo num elemento já
   descartado do documento, então o ``change`` não subia até o listener e a foto
   se perdia em silêncio.
2. "tenho que clicar em outro lugar da tela para ela aparecer": a miniatura
   usava ``loading="lazy"`` e só ia buscar a imagem no toque seguinte; e, assim
   que o upload terminava, a cópia local era descartada antes de a versão do
   servidor terminar de baixar.
3. o alvo da foto viajava como ÍNDICE na lista — que muda quando um animal é
   incluído em campo (cães primeiro, gatos depois) ou quando a planilha é
   relida.
"""

import re
from pathlib import Path

import pytest


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "vacina_pmo" / "dashboard.html"


@pytest.fixture(scope="module")
def source():
    return TEMPLATE.read_text(encoding="utf-8")


def function_body(source, name):
    match = re.search(
        rf"(?:async\s+)?function\s+{re.escape(name)}\([^)]*\)\s*\{{(.*?)\n  \}}",
        source,
        re.S,
    )
    assert match, f"funcao {name} nao encontrada"
    return match.group(1)


def test_campos_de_arquivo_ficam_fora_da_lista_que_e_reescrita(source):
    """O <input> precisa sobreviver ao render que acontece enquanto a câmera está aberta."""
    assert 'id="pmo-photo-input-camera"' in source
    assert 'id="pmo-photo-input-gallery"' in source
    # Nenhum campo de arquivo pode voltar para dentro do HTML gerado por render().
    controls = function_body(source, "renderAnimalControls")
    assert "type=\"file\"" not in controls
    assert "pmo-animal-photo-input" not in source


def test_a_foto_escolhida_encontra_o_animal_mesmo_apos_re_render(source):
    pedido = function_body(source, "requestAnimalPhoto")
    assert "rememberPhotoTarget(target.animalId)" in pedido
    assert "input.value = ''" in pedido, "zerar antes do clique garante o change na segunda foto igual"
    assert "sessionStorage.setItem(PHOTO_TARGET_KEY" in function_body(source, "rememberPhotoTarget")
    assert "sessionStorage.getItem(PHOTO_TARGET_KEY)" in function_body(source, "recallPhotoTarget")
    assert "const animalId = recallPhotoTarget();" in source
    assert "queueAnimalPhotoUpload(animal, file)" in source


def test_nada_mais_enderecca_animal_por_posicao_na_lista(source):
    """Índice de lista não identifica animal: a ordem muda em campo."""
    assert "data-animal-index" not in source
    assert "animalIndex" not in source
    assert "editingAnimalNameIndex" not in source
    assert "data-animal-id" in source
    assert "function findRowAnimalById(row, animalId)" in source


def test_miniatura_nao_adia_o_carregamento(source):
    control = function_body(source, "renderAnimalPhotoControl")
    assert 'loading="lazy"' not in control, "lazy fazia a foto só aparecer no toque seguinte"
    assert 'decoding="async"' in control


def test_copia_local_segura_a_miniatura_ate_a_remota_carregar(source):
    control = function_body(source, "renderAnimalPhotoControl")
    assert "animal.pendingImageUrl || animal.localImageUrl || animal.imageUrl" in control

    upload = function_body(source, "uploadQueuedPhoto")
    assert "clearAnimalQueuedPhoto(animalId, { keepPreview: true })" in upload
    assert "swapToRemotePhotoWhenReady(animalId" in upload

    swap = function_body(source, "swapToRemotePhotoWhenReady")
    assert "probe.onload" in swap
    assert "releaseLocalPhotoPreview(id)" in swap
    assert "probe.onerror" not in swap, "sem a remota, a cópia local continua na tela"

    assert "'localImageUrl'," in function_body(source, "replaceStateRow")
