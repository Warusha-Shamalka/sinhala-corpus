"""Conservative exam metadata hints from resource-specific titles and URLs.

Hints are evidence for pairing proposals, never verified answers or language labels.
Conflicting identifiers remain unknown rather than selecting the first match.
"""
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

from pipeline.discovery.filters import extract_grade, extract_medium_hint, subject_matches


FIELDS = ('exam', 'subject', 'exam_year', 'medium', 'paper_number', 'paper_kind',
          'grade', 'session', 'syllabus', 'issuer')


def metadata(title, url, subjects, row=None):
    parts = urlsplit(url)
    path = re.sub(r'/(?:downloadfile|download|file)/\d+/?$', '', unquote(parts.path), flags=re.I)
    path = re.sub(r'(?<![a-zA-Z0-9])[0-9a-fA-F]{16,}(?![a-zA-Z0-9])', ' ', path)
    query = ' '.join(value for key, value in parse_qsl(parts.query)
                     if key.casefold() in {'year', 'exam_year', 'subject', 'medium', 'paper', 'session', 'syllabus'})
    raw_text = unicodedata.normalize('NFC', unquote(f'{title} {path} {query}')).casefold()
    text = re.sub(r'[_\-]+', ' ', raw_text)
    values = {field: set() for field in FIELDS}
    values['exam_year'].update(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', text))
    for exam, pattern in (
        ('A-Level', r'\b(?:a\s*[/.-]?\s*l|advance(?:d)?\s+level)\b|උසස් පෙළ'),
        ('O-Level', r'\b(?:o\s*[/.-]?\s*l|ordinary\s+level)\b|සාමාන්‍ය පෙළ'),
        ('Grade-5-Scholarship', r'\b(?:grade\s*5\s+scholarship|scholarship\s+exam)\b|ශිෂ්‍යත්ව'),
    ):
        if re.search(pattern, text): values['exam'].add(exam)
    subject, _ = subject_matches(text, subjects)
    if subject: values['subject'].add(subject)
    medium = extract_medium_hint(text, subjects)
    if medium: values['medium'].add(medium)
    # Capture all media too, so a bilingual/conflicting title never becomes a single-medium match.
    for language, phrases in subjects.get('medium_markers', {}).items():
        if extract_medium_hint(text, {'medium_markers': {language: phrases}}):
            values['medium'].add(language)
    roman = {'i': '1', 'ii': '2', 'iii': '3', 'iv': '4'}
    for match in re.finditer(r'(?:\bpaper\s*(?:no\.?\s*|number\s*)?|පත්‍රය\s*|පත්‍ර\s*)([1-4]|iv|iii|ii|i)(?![\w])', text):
        value = match[1]
        values['paper_number'].add(roman.get(value, value))
        # A combined I & II document is not silently treated as Paper I alone.
        suffix = text[match.end():]
        continuation = re.match(r'\s*(?:and|&|\+|/)\s*(?:paper\s*)?([1-4]|iv|iii|ii|i)(?![\w])', suffix)
        if continuation: values['paper_number'].add(roman.get(continuation[1], continuation[1]))
    for kind, pattern in (('model', r'\bmodel\s+(?:papers?|exam)|ආදර්ශ'),
                          ('term_test', r'\bterm\s*(?:test|exam)|වාර\s*පරීක්ෂණ'),
                          ('past', r'\bpast\s+papers?|පසුගිය\s*ප්‍රශ්න')):
        if re.search(pattern, text): values['paper_kind'].add(kind)
    if values['paper_kind'] & {'model', 'term_test'}:
        values['paper_kind'].discard('past')  # "term-test past paper" is a term test.
    grade, _ = extract_grade(raw_text, subjects)
    if grade:
        values['grade'].add(grade)
    else:
        for grade in re.findall(r'\b(?:grade|class)\s*(1[0-3]|[1-9])(?!\d)', text):
            values['grade'].add(grade)
    for session, pattern in (('may_june', r'\bmay\s*/\s*june\b'),
                             ('october_november', r'\b(?:october|oct)\s*/\s*(?:november|nov)\b'),
                             ('first_term', r'\b(?:first|1st|1)\s+term\b'),
                             ('second_term', r'\b(?:second|2nd|2)\s+term\b'),
                             ('third_term', r'\b(?:third|3rd|3)\s+term\b')):
        if re.search(pattern, text): values['session'].add(session)
    for version in ('new', 'old', 'revised', 'updated'):
        if re.search(rf'\b{version}\s+(?:syllabus|curriculum)\b', text): values['syllabus'].add(version)
    for province in ('western', 'central', 'eastern', 'northern', 'southern', 'north western',
                     'north central', 'uva', 'sabaragamuwa'):
        if re.search(rf'(?<!\w){province}\s+province\b', text): values['issuer'].add(province + ' province')
    # Prefer the specific province name over its contained suffix.
    values['issuer'] = {v for v in values['issuer'] if not any(v != other and other.endswith(v) for other in values['issuer'])}
    if row:
        for key in FIELDS:
            value = row.get(key, '')
            if value:
                if key == 'medium': value = {'sinhala': 'si', 'tamil': 'ta', 'english': 'en'}.get(value.casefold(), value)
                values[key].add(value)
        if row.get('language'): values['medium'].add(row['language'])
        if row.get('education_level') in {'A-Level', 'O-Level'}:
            values['exam'].add(row['education_level'])
    conflicts = {key: sorted(found) for key, found in values.items() if len(found) > 1}
    result = {key: next(iter(found)) if len(found) == 1 else '' for key, found in values.items()}
    result.update(conflicts=conflicts, evidence={'title': title, 'source_url': url}, verified=False)
    return result


def enrich_candidate(candidate, subjects):
    """Populate only the existing exam_year column; preserve medium as an audit hint."""
    if candidate['document_type'] not in {'past_paper', 'marking_scheme'}:
        return candidate
    info = metadata(candidate['title'], candidate['source_url'], subjects)
    candidate['exam_year'] = info['exam_year']
    return candidate
