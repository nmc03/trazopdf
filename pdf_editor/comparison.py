import json
import math
import os
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageChops, ImageFilter

from .lang import _, N_

MAX_DPI, MAX_SIDE, MAX_PIXELS, TOL = 110, 1400, 2000000, 12
RESOLUTION = N_('Máx. 110 ppp, lado largo ≤ 1400 px, ≤ 2.000.000 px por página; tolerancia 12/255 por canal')
WHITE = (255, 255, 255)


def _open(path, label):
    if not Path(path).is_file():
        raise FileNotFoundError(_('No se encontró el {label} documento: {path}', label=label, path=path))
    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ValueError(_('No se pudo abrir el {label} documento (PDF dañado): {error}', label=label, error=exc)) from exc
    msg = None
    if not doc.is_pdf:
        msg = N_('no es un PDF válido.')
    elif doc.needs_pass:
        msg = N_('está protegido con contraseña.')
    elif doc.page_count <= 0:
        msg = N_('no contiene páginas.')
    if msg:
        doc.close()
        raise ValueError(_('El {label} documento {problem}', label=label, problem=_(msg)))
    return doc


def _scale(w, h):
    w, h = max(w, 1.0), max(h, 1.0)
    s = min(MAX_DPI / 72.0, MAX_SIDE / max(w, h), math.sqrt(MAX_PIXELS / (w * h)))
    for _attempt in range(300):
        pw, ph = math.ceil(w * s), math.ceil(h * s)
        if max(pw, ph) <= MAX_SIDE and pw * ph <= MAX_PIXELS:
            break
        s *= 0.99
    return s


def _info(doc, i):
    if i >= doc.page_count:
        return None
    p = doc.load_page(i)
    return p, (float(p.rect.width), float(p.rect.height)), int(p.rotation)


def _render(page, s):
    pix = page.get_pixmap(matrix=fitz.Matrix(s, s), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def _canvas(img, size):
    c = Image.new('RGB', size, WHITE)
    if img is not None:
        c.paste(img, (0, 0))
    return c


def _area(box, size):
    m = Image.new('L', size, 0)
    if box:
        m.paste(255, (0, 0, box[0], box[1]))
    return m


def _diff(a, b, abox, bbox):
    size = a.size
    r, g, bl = [x.point(lambda v: 255 if v > TOL else 0) for x in ImageChops.difference(a, b).split()]
    mask = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    mask = ImageChops.lighter(mask, ImageChops.difference(_area(abox, size), _area(bbox, size)))
    n = mask.histogram()[255]
    blend = Image.blend(a, b, 0.5)
    faded = Image.blend(blend.convert('L').convert('RGB'), Image.new('RGB', size, WHITE), 0.7)
    tint = Image.blend(blend, Image.new('RGB', size, (255, 0, 255)), 0.6)
    grown = mask.filter(ImageFilter.MaxFilter(3)) if n else mask
    return Image.composite(tint, faded, grown), round(n * 100.0 / (size[0] * size[1]), 4)


def _page(src, oth, i, out, written):
    num = i + 1
    try:
        lp, rp = _info(src, i), _info(oth, i)
        pr = [p for p in (lp, rp) if p]
        s = _scale(max(p[1][0] for p in pr), max(p[1][1] for p in pr))
        li = _render(lp[0], s) if lp else None
        ri = _render(rp[0], s) if rp else None
        im = [x for x in (li, ri) if x is not None]
        size = (max(x.size[0] for x in im), max(x.size[1] for x in im))
        lb = li.size if li is not None else None
        rb = ri.size if ri is not None else None
        li, ri = _canvas(li, size), _canvas(ri, size)
        diff, pct = _diff(li, ri, lb, rb)
        sc = bool(lp and rp and (abs(lp[1][0] - rp[1][0]) > 0.001 or abs(lp[1][1] - rp[1][1]) > 0.001 or lp[2] != rp[2]))
        status = 'added' if not lp else 'removed' if not rp else 'changed' if (sc or pct > 0) else 'equal'
        if not lp or not rp:
            pct = 100.0
        names = {}
        for key, img in (('left', li), ('right', ri), ('diff', diff)):
            names[key + '_image'] = 'page_%04d_%s.png' % (num, key)
            written.append(out / names[key + '_image'])
            img.save(str(out / names[key + '_image']), format='PNG', compress_level=3)
    except (InterruptedError, ValueError, OSError):
        raise
    except Exception as exc:
        raise ValueError(_('No se pudo procesar la página {page}: {error}', page=num, error=exc)) from exc
    e = {'page': num, 'status': status, 'changed_percent': float(pct)}
    e.update(names)
    e.update({'size_changed': sc,
              'left_size': [round(lp[1][0], 2), round(lp[1][1], 2)] if lp else None,
              'right_size': [round(rp[1][0], 2), round(rp[1][1], 2)] if rp else None,
              'image_size': list(size)})
    return e


def compare_documents(source_path, other_path, output_folder, progress=None, cancelled=None):
    """Compare appearance into a new or empty folder, never overwrite an earlier report."""
    out, written, docs = Path(output_folder), [], []
    if out.exists() and any(out.iterdir()):
        raise ValueError(_('La carpeta del informe debe estar vacía para no sobrescribir archivos.'))

    def check():
        if cancelled is not None and cancelled():
            raise InterruptedError(_('Comparación cancelada.'))
    try:
        src = _open(source_path, _('primer'))
        docs.append(src)
        oth = _open(other_path, _('segundo'))
        docs.append(oth)
        out.mkdir(parents=True, exist_ok=True)
        total = max(src.page_count, oth.page_count)
        pages = []
        for i in range(total):
            check()
            pages.append(_page(src, oth, i, out, written))
            if progress is not None:
                progress(i + 1, total)
            check()
        changed = [p['page'] for p in pages if p['status'] != 'equal']
        rep = {'resolution': _(RESOLUTION), 'tolerance': TOL, 'source_pages': src.page_count,
               'other_pages': oth.page_count, 'total_pages': total, 'changed_pages': changed,
               'pages': pages}
        tmp = out / 'comparison.json.tmp'
        written.append(tmp)
        tmp.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(str(tmp), str(out / 'comparison.json'))
        return rep
    except BaseException:
        for p in written:
            try:
                Path(p).unlink()
            except OSError:
                pass
        raise
    finally:
        for d in docs:
            d.close()
