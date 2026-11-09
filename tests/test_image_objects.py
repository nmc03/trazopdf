import io
import pymupdf as fitz
import pytest
from PIL import Image

from pdf_editor.engine import PDFEngine
from pdf_editor.image_objects import list_images, transform_image, delete_image, replace_image


def png(color):
    output = io.BytesIO()
    Image.new('RGB', (100, 80), color).save(output, 'PNG')
    return output.getvalue()


@pytest.fixture
def shared():
    document = fitz.open()
    first = document.new_page(width=400, height=400)
    xref = first.insert_image((30, 40, 130, 120), stream=png('red'))
    first.insert_image((230, 40, 330, 120), xref=xref)
    first.insert_text((20, 300), 'Keep text')
    document.new_page(width=400, height=400).insert_image((30, 40, 130, 120), xref=xref)
    yield document
    document.close()


def test_move_resize_only_one_occurrence_and_save(shared, tmp_path):
    other_pixels = shared[1].get_pixmap().samples
    assert len(list_images(shared[0])) == 2
    transform_image(shared[0], 0, (50, 160, 200, 280))
    pix = shared[0].get_pixmap()
    assert pix.pixel(80, 80) == (255, 255, 255)
    assert pix.pixel(80, 200) == (255, 0, 0)
    assert pix.pixel(280, 80) == (255, 0, 0)
    assert shared[1].get_pixmap().samples == other_pixels
    assert 'Keep text' in shared[0].get_text()
    output = tmp_path / 'moved.pdf'
    shared.save(output)
    with fitz.open(output) as check:
        assert tuple(list_images(check[0])[0]['rect']) == pytest.approx((50, 160, 200, 280), abs=.1)


def test_delete_preserves_other_occurrences_and_vectors(shared):
    page = shared[0]
    page.draw_rect((20, 30, 140, 130), color=(0, 1, 0), fill=(0, 1, 0), overlay=False)
    delete_image(page, 0)
    pix = page.get_pixmap()
    assert pix.pixel(80, 80) == (0, 255, 0)
    assert pix.pixel(280, 80) == (255, 0, 0)
    assert len(list_images(page)) == 1
    assert len(list_images(shared[1])) == 1


def test_replace_preserves_shared_copies_and_z_order(shared, tmp_path):
    blue = tmp_path / 'blue.png'
    blue.write_bytes(png('blue'))
    page = shared[0]
    page.draw_rect((60, 60, 100, 100), color=(0, 1, 0), fill=(0, 1, 0), overlay=True)
    replace_image(page, 0, blue)
    assert page.get_pixmap().pixel(40, 50) == (0, 0, 255)
    assert page.get_pixmap().pixel(80, 80) == (0, 255, 0)
    assert page.get_pixmap().pixel(280, 80) == (255, 0, 0)
    assert shared[1].get_pixmap().pixel(80, 80) == (255, 0, 0)


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_cropped_rotated_images(shared, rotation):
    page = shared[0]
    page.set_cropbox((10, 20, 380, 390))
    page.set_rotation(rotation)
    images = list_images(page)
    assert images[0]['editable']
    transform_image(page, 0, (40, 150, 140, 230))
    assert page.rotation == rotation
    assert tuple(list_images(page)[0]['rect']) == pytest.approx((40, 150, 140, 230), abs=.1)


def test_shared_content_is_not_modified(shared):
    page = shared[0]
    content = page.get_contents()
    second = shared[1]
    shared.xref_set_key(second.xref, 'Resources', shared.xref_get_key(page.xref, 'Resources')[1])
    shared.xref_set_key(second.xref, 'Contents', '[' + ' '.join(f'{xref} 0 R' for xref in content) + ']')
    before = shared[1].get_pixmap().samples
    transform_image(page, 0, (50, 160, 150, 240))
    assert shared[1].get_pixmap().samples == before
    assert page.get_contents() != content


def test_nested_form_is_listed_but_not_edited(shared):
    with fitz.open() as target:
        page = target.new_page(width=400, height=400)
        page.show_pdf_page(page.rect, shared, 0)
        assert list_images(page) and not list_images(page)[0]['editable']
        before = page.get_pixmap().samples
        with pytest.raises(ValueError, match='estructura'):
            delete_image(page, 0)
        assert page.get_pixmap().samples == before


def test_transaction_undo_redo_and_failed_replacement(shared, tmp_path):
    engine = PDFEngine()
    try:
        engine.from_pdf_bytes(shared.tobytes())
        engine.transform_image(0, 0, (50, 160, 150, 240))
        assert engine.images(0)[0]['rect'].y0 == pytest.approx(160)
        engine.undo()
        assert engine.images(0)[0]['rect'].y0 == pytest.approx(40)
        engine.redo()
        before = engine.render(0).samples
        with pytest.raises(Exception):
            engine.replace_image(0, 0, tmp_path / 'missing.png')
        assert engine.render(0).samples == before
    finally:
        engine.close()


def test_clipped_images_are_refused_without_mutation(shared):
    page = shared[0]
    original = page.read_contents()
    xref = shared.get_new_xref()
    shared.update_object(xref, '<<>>')
    shared.update_stream(xref, b'q\n0 0 400 400 re W n\n' + original + b'\nQ')
    page.set_contents(xref)
    before = page.get_pixmap().samples
    assert all(not image['editable'] for image in list_images(page))
    with pytest.raises(ValueError):
        transform_image(page, 0, (40, 150, 140, 230))
    assert page.read_contents().startswith(b'q\n0 0 400 400 re W n')
    assert page.get_pixmap().samples == before
