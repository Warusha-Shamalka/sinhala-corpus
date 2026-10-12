"""Normalize Unicode and line endings without rewriting Sinhala or equations."""
import unicodedata

VERSION = 'native-clean-1'


def clean(text):
    return unicodedata.normalize('NFC', text.replace('\r\n', '\n').replace('\r', '\n')).strip()


def reasons(page, text, min_chars=80, min_sinhala_ratio=0.8):
    result = []
    if page.get('extraction_method') != 'poppler-bbox-layout':
        result.append('not_native_pdf')
    if page.get('ocr_required') is not False or page.get('errors'):
        result.append('extraction_flagged')
    chars = [c for c in text if not c.isspace()]
    if len(chars) < min_chars:
        result.append('short_text')
    if '\ufffd' in text:
        result.append('replacement_character')
    if any(unicodedata.category(c) == 'Cc' and c not in '\n\t' for c in text):
        result.append('control_character')
    letters = [c for c in text if unicodedata.category(c).startswith('L')]
    ratio = sum('\u0d80' <= c <= '\u0dff' for c in letters) / len(letters) if letters else 0
    if ratio < min_sinhala_ratio:
        result.append('little_sinhala_or_legacy_font')
    return result
