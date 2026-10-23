"""Bounded image decoding and explicitly selected OCR preprocessing experiments."""
import io
import math
import warnings


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {'rotate_degrees', 'crop', 'grayscale', 'autocontrast'}:
        raise ValueError('Unknown image preprocessing options')
    angle = options.get('rotate_degrees', 0)
    if type(angle) not in (int, float) or not math.isfinite(angle) or not -15 <= angle <= 15:
        raise ValueError('rotate_degrees must be between -15 and 15')
    for key in ('grayscale', 'autocontrast'):
        if type(options.get(key, False)) is not bool:
            raise ValueError(f'{key} must be boolean')
    crop = options.get('crop', [0, 0, 1, 1])
    if (not isinstance(crop, list) or len(crop) != 4
            or any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in crop)
            or crop[0] >= crop[2] or crop[1] >= crop[3]):
        raise ValueError('crop must be normalized [left, top, right, bottom] coordinates')


def decode(content, maximum_pixels=40_000_000):
    from PIL import Image, ImageOps
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in {'PNG', 'JPEG'} or getattr(source, 'n_frames', 1) != 1:
                raise ValueError('Only single-frame PNG and JPEG images are supported')
            if source.width * source.height > maximum_pixels:
                raise ValueError('Image exceeds pixel limit')
            kind = 'png' if source.format == 'PNG' else 'jpg'
            source.load()  # Verify full decoding before any catalog/raw writes.
            oriented = ImageOps.exif_transpose(source)
            rgba = oriented.convert('RGBA')
            page = Image.new('RGB', rgba.size, 'white')
            page.paste(rgba, mask=rgba.getchannel('A'))
    return page, kind


def prepare(content, maximum_side, options=None, maximum_pixels=40_000_000):
    from PIL import Image, ImageOps
    options = options or {}
    validate_options(options)
    page, _ = decode(content, maximum_pixels)
    original_size = list(page.size)
    crop = options.get('crop', [0, 0, 1, 1])
    box = [round(crop[0] * page.width), round(crop[1] * page.height),
           round(crop[2] * page.width), round(crop[3] * page.height)]
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError('Crop contains no pixels')
    page = page.crop(box)
    if options.get('rotate_degrees'):
        page = page.rotate(options['rotate_degrees'], resample=Image.Resampling.BICUBIC,
                           expand=True, fillcolor='white')
    if options.get('grayscale'): page = ImageOps.grayscale(page).convert('RGB')
    if options.get('autocontrast'): page = ImageOps.autocontrast(page)
    page.thumbnail((maximum_side, maximum_side), Image.Resampling.LANCZOS)
    stream = io.BytesIO(); page.save(stream, format='PNG')
    return stream.getvalue(), {'original_dimensions': original_size, 'crop_pixels': box,
                               'options': options, 'output_dimensions': list(page.size),
                               'coordinate_system': 'ocr_input_pixels'}


def reading_order(lines, width, columns=1):
    """Optional two-column ordering, with full-width lines separating vertical bands.

    Explicit experiment only: it cannot infer tables or diagram semantics.
    Original upstream lines/boxes remain in raw_result.
    """
    if columns == 1: return list(range(len(lines)))
    if columns != 2 or not width or width <= 0:
        raise ValueError('Reading order supports one or two columns')
    positioned = []
    for index, line in enumerate(lines):
        box = line.get('bbox')
        if not box or len(box) != 4:
            raise ValueError('Two-column ordering requires line bounding boxes')
        x1, y1, x2, y2 = box
        positioned.append((index, x1, y1, x2, y2))
    split = width / 2
    spanning = sorted((r for r in positioned if r[1] < split < r[3]), key=lambda r: (r[2], r[1]))
    pending = [r for r in positioned if r not in spanning]
    order = []
    for boundary in [*spanning, None]:
        band = [r for r in pending if boundary is None or (r[2] + r[4]) / 2 < boundary[2]]
        band.sort(key=lambda r: (r[1] >= split, r[2], r[1]))
        order.extend(r[0] for r in band)
        used = {r[0] for r in band}; pending = [r for r in pending if r[0] not in used]
        if boundary is not None: order.append(boundary[0])
    return order
