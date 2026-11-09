"""Conservative image occurrence editing without rewriting shared image objects.

Only direct, axis-aligned Image Do operations without complex graphics state
are editable. Nested forms, inline images, clipping and ExtGState are listed
but deliberately refused. Callers provide transaction/rollback boundaries.
"""
from contextlib import contextmanager
import math

import pymupdf as fitz
from pypdf.generic import ContentStream, DecodedStreamObject, FloatObject, NameObject

from .lang import _


@contextmanager
def _unrotated(page):
    rotation = page.rotation
    try:
        if rotation:
            page.set_rotation(0)
        yield
    finally:
        if rotation:
            page.set_rotation(rotation)


def _inspect(page):
    with _unrotated(page):
        # MuPDF 1.28 caches IMGINFO on the Python Page handle, including after
        # Contents/crop edits. Invalidate before matching display occurrences.
        page._image_info = None
        infos = page.get_image_info(xrefs=True)
        matrix = fitz.Matrix(page.transformation_matrix)
        resources = {row[7]: row[0] for row in page.get_images(full=True) if row[9] == 0}
    images = [dict(index=i, rect=fitz.Rect(info['bbox']), xref=info['xref'], editable=False,
                   reason=_('La imagen está anidada, es inline o usa una transformación no compatible.'))
              for i, info in enumerate(infos)]
    content = page.read_contents()
    if len(content) > 20 * 1024 * 1024:
        return images, None, {}, matrix
    try:
        raw = DecodedStreamObject()
        raw.set_data(content)
        stream = ContentStream(raw, None)
        operations = stream.operations
        # Moving an image out of an inherited clip or soft-mask group can
        # change its appearance; these pages remain available for reading.
        if any(operator in (b'W', b'W*', b'gs') for _, operator in operations):
            return images, stream, {}, matrix
        ctm, stack, candidates = fitz.Matrix(1, 0, 0, 1, 0, 0), [], {}
        for number, (operands, operator) in enumerate(operations):
            if operator == b'q':
                stack.append(fitz.Matrix(ctm))
            elif operator == b'Q':
                if not stack:
                    return images, stream, {}, matrix
                ctm = stack.pop()
            elif operator == b'cm':
                if len(operands) != 6:
                    return images, stream, {}, matrix
                ctm = fitz.Matrix(*(float(x) for x in operands)) * ctm
            elif operator == b'Do' and len(operands) == 1:
                xref = resources.get(str(operands[0]).lstrip('/'))
                if not xref or abs(ctm.b) > .00001 or abs(ctm.c) > .00001 or abs(ctm.a * ctm.d) < .000001:
                    continue
                bounds = fitz.Rect(0, 0, 1, 1) * ctm * matrix
                for image in images:
                    if image['index'] in candidates or image['xref'] != xref:
                        continue
                    if max(abs(a - b) for a, b in zip(bounds, image['rect'])) < .15:
                        candidates[image['index']] = (number, fitz.Matrix(ctm))
                        break
        if stack:
            return images, stream, {}, matrix
        for image in images:
            image['editable'] = image['index'] in candidates
            if image['editable']:
                image['reason'] = ''
        return images, stream, candidates, matrix
    except Exception:
        # A malformed/unsupported content stream must not prevent PDF reading.
        return images, None, {}, matrix


def list_images(page):
    return _inspect(page)[0]


def _selected(page, index):
    images, stream, candidates, matrix = _inspect(page)
    image = next((image for image in images if image['index'] == index), None)
    if image is None:
        raise ValueError(_('La imagen ya no existe. Vuelve a seleccionarla.'))
    if not image['editable']:
        raise ValueError(_('Esta imagen no admite edición individual: contiene una estructura o un estado gráfico complejo.'))
    number, ctm = candidates[index]
    return image, stream, number, ctm, matrix


def _write(page, stream, operations):
    stream.operations = operations
    doc = page.parent
    xref = doc.get_new_xref()
    doc.update_object(xref, '<<>>')
    doc.update_stream(xref, stream.get_data())
    # Content stream objects may be shared with another page. Always allocate
    # a new one and change only this page's Contents reference.
    page.set_contents(xref)
    page._image_info = None


def transform_image(page, index, target_rect):
    image, stream, number, ctm, matrix = _selected(page, index)
    target = fitz.Rect(target_rect)
    bounds = page.rect * page.derotation_matrix
    if target.is_empty or not all(math.isfinite(v) for v in target) or not bounds.contains(target):
        raise ValueError(_('La imagen debe quedar dentro de la página.'))
    original = image['rect']
    sx, sy = target.width / original.width, target.height / original.height
    transform = fitz.Matrix(sx, 0, 0, sy, target.x0 - original.x0 * sx, target.y0 - original.y0 * sy)
    local = ctm * matrix * transform * ~matrix * ~ctm
    replacement = [([], b'q'), ([FloatObject(value) for value in local], b'cm'), stream.operations[number], ([], b'Q')]
    operations = list(stream.operations)
    operations[number:number + 1] = replacement
    _write(page, stream, operations)


def delete_image(page, index):
    image, stream, number, ctm, matrix = _selected(page, index)
    operations = list(stream.operations)
    del operations[number]
    _write(page, stream, operations)


def replace_image(page, index, path):
    image, stream, number, ctm, matrix = _selected(page, index)
    operations = list(stream.operations)
    names = {row[7] for row in page.get_images(full=True) if row[9] == 0}
    # Import an independent image resource using MuPDF. Its helper drawing is
    # discarded when the original stream (with one replaced Do) is installed.
    with _unrotated(page):
        xref = page.insert_image((0, 0, 10, 10), filename=str(path))
    added = [row[7] for row in page.get_images(full=True) if row[9] == 0 and row[0] == xref and row[7] not in names]
    if len(added) != 1:
        raise ValueError(_('No se pudo aislar el recurso de la imagen nueva.'))
    operations[number] = ([NameObject('/' + added[0])], b'Do')
    _write(page, stream, operations)
