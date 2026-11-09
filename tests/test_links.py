import pymupdf as fitz
import pytest

from pdf_editor.engine import PDFEngine


@pytest.fixture
def engine():
    value = PDFEngine()
    yield value
    value.close()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_link_area_survives_rotation_edit_save_and_undo(engine, tmp_path, rotation):
    engine.doc[0].set_rotation(rotation)
    engine.set_link(0, (40, 60, 180, 100), uri='https://example.com/path?q=1')
    original = engine.links(0)[0]
    assert tuple(original['from']) == pytest.approx((40, 60, 180, 100))
    engine.set_link(0, (50, 70, 190, 110), uri='mailto:test@example.com', xref=original['xref'])
    assert engine.links(0)[0]['uri'] == 'mailto:test@example.com'
    engine.undo()
    assert engine.links(0)[0]['uri'].startswith('https://')
    engine.redo()
    engine.save(tmp_path / 'links.pdf')
    engine.open(tmp_path / 'links.pdf')
    saved = engine.links(0)[0]
    assert tuple(saved['from']) == pytest.approx((50, 70, 190, 110))
    engine.delete_link(0, saved['xref'])
    assert engine.links(0) == []
    engine.undo()
    assert len(engine.links(0)) == 1


def test_internal_link_preserves_other_annotations_and_content(engine):
    engine.insert_blank(0)
    engine.add_text(0, (30, 30, 400, 90), 'Keep this text')
    engine.annotate(0, (300, 300, 330, 330), 'note', 'Keep this comment')
    engine.set_link(0, (30, 30, 180, 90), target_page=1)
    link = engine.links(0)[0]
    assert link['kind'] == fitz.LINK_GOTO and link['page'] == 1
    engine.delete_link(0, link['xref'])
    assert 'Keep this text' in engine.text(0)
    assert next(engine.doc[0].annots()).info['content'] == 'Keep this comment'


@pytest.mark.parametrize('uri', ['javascript:alert(1)', 'file:///C:/secret', 'https://', 'https://user:password@example.com', 'https://example.com/\nfoo', 'https://example.com/a b', 'mailto:'])
def test_invalid_links_are_rejected_without_changes(engine, uri):
    with pytest.raises(ValueError):
        engine.set_link(0, (30, 30, 200, 70), uri=uri)
    assert engine.links(0) == []
    assert not engine.dirty and not engine.can_undo


def test_invalid_destination_and_stale_xref_are_rejected(engine):
    with pytest.raises(ValueError):
        engine.set_link(0, (30, 30, 200, 70), target_page=7)
    with pytest.raises(ValueError):
        engine.set_link(0, (30, 30, 200, 70), uri='https://example.com', xref=98765)
    assert not engine.dirty


def test_cropped_rotated_link_coordinates(engine):
    page = engine.doc[0]
    page.set_cropbox((30, 50, 500, 700))
    page.set_rotation(90)
    engine.set_link(0, (40, 60, 180, 100), uri='https://example.com')
    assert tuple(engine.links(0)[0]['from']) == pytest.approx((40, 60, 180, 100))
