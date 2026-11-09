import hashlib
import io
import json

import fitz
import pytest
from PIL import Image

from pdf_editor.comparison import compare_documents

L = (612, 792)


def build(path, specs, **kw):
    doc = fitz.open()
    for size, draw in specs:
        page = doc.new_page(width=size[0], height=size[1])
        if draw:
            draw(page)
    doc.save(str(path), **kw)
    doc.close()
    return path


def text(p):
    p.insert_text((72, 100), 'Hola', fontsize=24)


def box(p):
    text(p)
    p.draw_rect(fitz.Rect(100, 200, 300, 400), color=(1, 0, 0), fill=(1, 0, 0))


def img(color):
    def d(p):
        buf = io.BytesIO()
        Image.new('RGB', (40, 40), color).save(buf, 'PNG')
        p.insert_image(fitz.Rect(100, 100, 300, 300), stream=buf.getvalue())
    return d


def run(tmp_path, a, b, **kw):
    return compare_documents(a, b, tmp_path / 'out', **kw)


def test_identical_and_json(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text), (L, None)])
    b = build(tmp_path / 'b.pdf', [(L, text), (L, None)])
    before = hashlib.sha256(a.read_bytes()).hexdigest()
    r = run(tmp_path, a, b)
    assert r['changed_pages'] == [] and r['total_pages'] == 2
    assert all(p['status'] == 'equal' and p['changed_percent'] == 0.0 for p in r['pages'])
    assert json.loads((tmp_path / 'out' / 'comparison.json').read_text(encoding='utf-8')) == r
    assert hashlib.sha256(a.read_bytes()).hexdigest() == before
    for p in r['pages']:
        sizes = {Image.open(tmp_path / 'out' / p[k]).size for k in ('left_image', 'right_image', 'diff_image')}
        assert sizes == {tuple(p['image_size'])}


def test_graphic_and_image_changes(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text), (L, text)])
    b = build(tmp_path / 'b.pdf', [(L, text), (L, box)])
    r = run(tmp_path, a, b)
    assert r['changed_pages'] == [2] and r['pages'][1]['changed_percent'] > 0
    c = build(tmp_path / 'c.pdf', [(L, img((255, 0, 0)))])
    d = build(tmp_path / 'd.pdf', [(L, img((0, 0, 255)))])
    assert run(tmp_path / 'images', c, d)['changed_pages'] == [1]


def test_added_removed_blank_page(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text)])
    b = build(tmp_path / 'b.pdf', [(L, text), (L, None)])
    p = run(tmp_path, a, b)['pages'][1]
    assert p['status'] == 'added' and p['changed_percent'] == 100.0 and p['left_size'] is None
    p = run(tmp_path / 'reverse', b, a)['pages'][1]
    assert p['status'] == 'removed' and p['changed_percent'] == 100.0 and p['right_size'] is None


def test_dimensions_changed(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, None)])
    b = build(tmp_path / 'b.pdf', [((500, 700), None)])
    p = run(tmp_path, a, b)['pages'][0]
    assert p['status'] == 'changed' and p['size_changed'] and p['changed_percent'] > 0
    assert p['left_size'] == [612.0, 792.0] and p['right_size'] == [500.0, 700.0]


def test_password(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text)])
    b = build(tmp_path / 'b.pdf', [(L, text)], encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='u', owner_pw='o')
    with pytest.raises(ValueError, match='contraseña'):
        run(tmp_path, a, b)


def test_malformed(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text)])
    bad = tmp_path / 'bad.pdf'
    bad.write_bytes(b'esto no es un pdf')
    with pytest.raises(ValueError):
        run(tmp_path, a, bad)


def test_cancellation_and_progress(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text), (L, text)])
    with pytest.raises(InterruptedError):
        run(tmp_path, a, a, cancelled=lambda: True)
    calls = []
    run(tmp_path, a, a, progress=lambda d, t: calls.append((d, t)))
    assert calls == [(1, 2), (2, 2)]
    with pytest.raises(InterruptedError):
        run(tmp_path / 'cancelled', a, a, progress=lambda d, t: calls.append(0), cancelled=lambda: len(calls) > 2)
    assert not (tmp_path / 'cancelled' / 'out' / 'comparison.json').exists()
    assert (tmp_path / 'out' / 'comparison.json').exists()


def test_existing_report_is_preserved(tmp_path):
    a = build(tmp_path / 'a.pdf', [(L, text)])
    run(tmp_path, a, a)
    report = (tmp_path / 'out' / 'comparison.json').read_bytes()
    with pytest.raises(ValueError, match='vacía'):
        run(tmp_path, a, a)
    assert (tmp_path / 'out' / 'comparison.json').read_bytes() == report


def test_huge_page_bounds(tmp_path):
    big = (14000, 9000)
    a = build(tmp_path / 'a.pdf', [(big, text)])
    b = build(tmp_path / 'b.pdf', [(big, box)])
    p = run(tmp_path, a, b)['pages'][0]
    w, h = Image.open(tmp_path / 'out' / p['diff_image']).size
    assert max(w, h) <= 1400 and w * h <= 2000000 and [w, h] == p['image_size']
