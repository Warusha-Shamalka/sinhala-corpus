"""Extract explicit MCQ blocks and answer keys into provisional, source-linked records."""
from collections import defaultdict
from pathlib import Path
import re
import unicodedata

from pipeline.collection import for_config
from pipeline.dataset.native import digest, encode, publish
from pipeline.discovery.crawler import read_catalog
from pipeline.download.downloader import recover, file_hash
from pipeline.processing.pages import current_pages, incomplete, load_settings


QUESTION = re.compile(r'^\s*(\d{1,3})[.)]\s+(.+)$', re.M)
OPTION = re.compile(r'^\s*[([]([1-5a-eA-E])[)\]]\s*(.+)$', re.M)
ANSWER = re.compile(r'^\s*(\d{1,3})\s*[.):-]\s*[(]?([1-5a-eA-E])[)]?\s*$', re.M)
ESSAY_HEADING = re.compile(r'^\s*(?:structured\s+essay|essay\s+(?:questions|paper)|රචනා\s*ප්‍රශ්න|ව්‍යුහගත\s*රචනා)', re.M | re.I)


def questions(text):
    found, issues = [], []
    if ESSAY_HEADING.search(text): return [], ['essay_heading_requires_page_review']
    starts = list(QUESTION.finditer(text))
    for i, start in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[start.end():end]
        choices = list(OPTION.finditer(block))
        if not 2 <= len(choices) <= 5:
            issues.append(f'question_{start[1]}_options_incomplete'); continue
        labels = [match[1].upper() for match in choices]
        expected = list('12345'[:len(labels)]) if labels[0].isdigit() else list('ABCDE'[:len(labels)])
        if labels != expected:
            issues.append(f'question_{start[1]}_option_labels_ambiguous'); continue
        stem = (start[2] + '\n' + block[:choices[0].start()]).strip()
        options = {match[1].upper(): block[match.start(2):choices[j+1].start() if j+1 < len(choices) else len(block)].strip()
                   for j, match in enumerate(choices)}
        found.append({'question_number': int(start[1]), 'stem': stem, 'options': options,
                      'source_character_span': [start.start(), end]})
    return found, issues


def answers(text):
    found, conflicts = {}, set()
    if ESSAY_HEADING.search(text): return {}, ['essay_heading_requires_page_review']
    for match in ANSWER.finditer(text):
        number, value = int(match[1]), match[2].upper()
        if number in found and found[number]['answer'] != value: conflicts.add(number)
        found[number] = {'answer': value, 'source_character_span': [match.start(), match.end()]}
    for number in conflicts: found.pop(number, None)
    return found, [f'answer_{n}_conflicting' for n in sorted(conflicts)]


def deduplicate_linked(records):
    unique, conflicts, issues = {}, set(), []
    def normalized(text): return ' '.join(unicodedata.normalize('NFC', text).split())
    for record in records:
        key = digest(encode({'stem': normalized(record['stem']),
                             'options': {k: normalized(v) for k, v in record['options'].items()}}))
        if key in conflicts: continue
        occurrence = {'question_source': record['provenance'], 'answer_source': record['answer_provenance'],
                      'question_number': record['question_number'], 'pair_key': record['pair_key']}
        if key not in unique:
            unique[key] = {**record, 'question_content_sha256': key, 'occurrences': [occurrence]}
        elif unique[key]['answer'] != record['answer']:
            conflicts.add(key); unique.pop(key)
            issues.append({'question_content_sha256': key, 'issue': 'identical_question_conflicting_answers'})
        else:
            unique[key]['occurrences'].append(occurrence)
    return list(unique.values()), issues


def extract(config, policy_path, output, config_hash=None):
    selection = for_config(config, policy_path)
    settings = load_settings(config)
    rows = {row['doc_id']: row for row in read_catalog(settings['catalog_path'])}
    selected = {row['doc_id'] for row in selection['selected'] if row['document_type'] in {'past_paper', 'marking_scheme'}}
    indexed, issues = defaultdict(list), []
    versions = defaultdict(set)
    for path, record in current_pages(settings['output_root']):
        identity = record['identity']; doc = identity['doc_id']
        if doc not in selected or identity['raw_sha256'] != rows[doc]['sha256']: continue
        if config_hash and identity['processing_config_sha256'] != config_hash: continue
        versions[doc].add(identity['processing_config_sha256'])
        indexed[doc].append((path, record))
    if any(len(value) > 1 for value in versions.values()):
        raise ValueError('Multiple processing versions; select --config-hash')
    output_questions, output_answers, linked = [], [], []
    for pair in selection['pairs']:
        qmap, amap, bad_q, bad_a = {}, {}, set(), set()
        for role in ('paper_doc_id', 'marking_scheme_doc_id'):
            doc = pair[role]
            try: recover({**rows[doc], 'status': 'DOWNLOADED'}, settings['raw_root'])
            except Exception as exc:
                issues.append({'doc_id': doc, 'issue': f'raw_verification_failed: {exc}'}); continue
            if not indexed[doc]: issues.append({'doc_id': doc, 'issue': 'no_processed_pages'})
            for path, record in sorted(indexed[doc], key=lambda item: item[1]['identity']['page_number']):
                if incomplete(record):
                    issues.append({'doc_id': doc, 'page_number': record['identity']['page_number'], 'issue': 'incomplete_ocr'}); continue
                text = record['text']
                provenance = {'doc_id': doc, 'bundle': str(path.parent), 'identity': record['identity'],
                              'text_sha256': digest(text.encode()), 'source_url': rows[doc]['source_url']}
                if role == 'paper_doc_id':
                    entries, flags = questions(text)
                    if not entries and not flags: flags = ['no_explicit_mcq_questions']
                    for question in entries:
                        number = question['question_number']
                        if number in qmap and (qmap[number]['stem'], qmap[number]['options']) != (question['stem'], question['options']): bad_q.add(number)
                        qmap[number] = {**question, 'provenance': provenance}
                else:
                    entries, flags = answers(text)
                    if not entries and not flags: flags = ['no_explicit_mcq_answer_rows']
                    for flag in flags:
                        match = re.fullmatch(r'answer_(\d+)_conflicting', flag)
                        if match: bad_a.add(int(match[1]))
                    for number, answer in entries.items():
                        if number in amap and amap[number]['answer'] != answer['answer']: bad_a.add(number)
                        amap[number] = {**answer, 'provenance': provenance}
                issues.extend({'doc_id': doc, 'issue': flag} for flag in flags)
        for number in bad_q: qmap.pop(number, None)
        for number in bad_a: amap.pop(number, None)
        issues.extend({'pair': pair['pair_key'], 'question_number': n, 'issue': 'conflicting_duplicate'} for n in sorted(bad_q | bad_a))
        for number, question in sorted(qmap.items()):
            common = {'record_id': digest(encode([pair['pair_key'], number])), 'pair_key': pair['pair_key'],
                      'question_number': number, 'review_required': True, 'training_approved': False}
            output_questions.append({**common, **question})
            if number not in amap:
                issues.append({'record_id': common['record_id'], 'issue': 'answer_missing'}); continue
            answer = amap[number]
            if answer['answer'] not in question['options']:
                issues.append({'record_id': common['record_id'], 'issue': 'answer_option_mismatch'}); continue
            linked.append({**common, **question, 'answer': answer['answer'], 'answer_provenance': answer['provenance'],
                           'answer_character_span': answer['source_character_span']})
        output_answers.extend({'pair_key': pair['pair_key'], 'question_number': n, **answer,
                               'review_required': True, 'training_approved': False} for n, answer in sorted(amap.items()))
    linked, duplicate_issues = deduplicate_linked(linked)
    issues.extend(duplicate_issues)
    report = {'schema_version': 'provisional-mcq-extraction-1', 'questions': len(output_questions),
              'answers': len(output_answers), 'linked_mcqs': len(linked), 'issues': len(issues), 'training_approved': False,
              'policy_sha256': selection['policy_sha256'], 'catalog_sha256': selection['catalog_sha256']}
    report['parser_code_sha256'] = file_hash(Path(__file__))
    files = {name + '.jsonl': b''.join(encode(row) for row in records) for name, records in
             [('questions', output_questions), ('answers', output_answers), ('linked_mcqs', linked), ('issues', issues)]}
    files['selection.json'] = encode(selection)
    publish(Path(output), {**files, 'manifest.json': encode({**report,
             'output_sha256': {name: digest(content) for name, content in files.items()}})})
    return {**report, 'output': str(Path(output).resolve())}
