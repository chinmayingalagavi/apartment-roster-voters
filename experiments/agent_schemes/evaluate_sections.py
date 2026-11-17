# Evaluate simple section-count grading rules against reviewed first-pass voter-flat rows.
# Inputs are the four pre-scoring and manually reviewed workbooks and the existing AC outputs.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
import csv
import re
import sys

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'code'))
import matching

SOURCES = {
    'concorde': ('concorde', 'Concorde Midway'),
    'purnima': ('purnima', 'Purnima Classic'),
    'silicon': ('silicon_oasis', 'Silicon Oasis'),
    'tirumala': ('tirumala_vintage', 'Tirumala Vintage'),
}
RESEARCH = ROOT.parent / 'agents' / 'research'
DESTINATION = ROOT / 'experiments' / 'agent_schemes'
LABELS = ('Strong', 'Medium', 'Unlikely', 'No Match')


def read_sheet(path):
    book = load_workbook(path, read_only=True, data_only=True)
    values = book['voters_mapped_tohouse'].values
    headers = next(values)
    rows = [dict(zip(headers, row)) for row in values]
    book.close()
    return rows


def key(row):
    return tuple(str(row[field] or '') for field in ('serial_number', 'apartment_unit', 'apartment_status'))


def review_key(row):
    fields = ('epic_number', 'serial_number', 'apartment_unit', 'apartment_status',
              'apartment_connection', 'voter_link_type')
    return tuple(str(row[field] or '') for field in fields)


def canonical(value):
    return matching.normalize_address(value)


def evidence(row, primary):
    link = str(row['voter_link_type'] or '')
    if 'voter_name_match' in link:
        name = row['voter_name']
    elif 'relation_name_match' in link:
        name = row['relation_name']
    else:
        name = ''
    score = row['name_match_pct']
    score = float(score) if score is not None else 0
    multis = len(matching.full_word_tokens(matching.tokenize_name(name))) >= 2 if name else False
    return {
        'direct': 'voter_name_match' in link,
        'score': score,
        'multiple_words': multis,
        'exact_apartment': bool(re.search(r'\b' + re.escape(canonical(primary)) + r'\b', canonical(row['house_number']))),
    }


def predict(row, scheme):
    exact = row['exact_apartment']
    score = row['score']
    count = row['other_section_flats']
    part_count = row['other_part_section_flats']
    if scheme == 'exact_or_section5':
        strong = exact or count >= 5
        medium = count >= 2
    elif scheme == 'exact_or_section10':
        strong = exact or count >= 10
        medium = count >= 2
    elif scheme == 'exact_or_section20':
        strong = exact or count >= 20
        medium = count >= 2
    elif scheme == 'exact_or_partsection5':
        strong = exact or part_count >= 5
        medium = part_count >= 2
    elif scheme == 'exact_or_partsection10':
        strong = exact or part_count >= 10
        medium = part_count >= 2
    elif scheme == 'exact_or_section5_name80':
        strong = exact or (count >= 5 and score > 80)
        medium = count >= 2 and score > 75
    elif scheme == 'exact_or_section5_name90':
        strong = exact or (count >= 5 and score >= 90)
        medium = count >= 2 and score > 75
    elif scheme == 'exact_or_section5_name80_or_exactmulti':
        strong = exact or (count >= 5 and score > 80) or (row['direct'] and score == 100 and row['multiple_words'])
        medium = count >= 2 and score > 75
    elif scheme == 'exact_or_section3_name80':
        strong = exact or (count >= 3 and score > 80)
        medium = count >= 2 and score > 75
    elif scheme == 'exact_or_partsection5_name80':
        strong = exact or (part_count >= 5 and score > 80)
        medium = part_count >= 2 and score > 75
    elif scheme == 'section5_direct80':
        strong = exact or (count >= 5 and (not row['direct'] or score > 80))
        medium = count >= 2 and (not row['direct'] or score > 75)
    elif scheme == 'section5_direct90':
        strong = exact or (count >= 5 and (not row['direct'] or score >= 90))
        medium = count >= 2 and (not row['direct'] or score > 75)
    elif scheme == 'section10_direct80':
        strong = exact or (count >= 10 and (not row['direct'] or score > 80))
        medium = count >= 2 and (not row['direct'] or score > 75)
    elif scheme == 'section5_medium_unconditional':
        strong = exact or (count >= 5 and (not row['direct'] or score > 80))
        medium = count >= 2
    else:
        raise ValueError(scheme)
    return 'Strong' if strong else 'Medium' if medium else 'Weak'


schemes = ['current', 'exact_or_section5', 'exact_or_section10', 'exact_or_section20',
           'exact_or_partsection5', 'exact_or_partsection10', 'exact_or_section5_name80', 'exact_or_section5_name90',
           'exact_or_section5_name80_or_exactmulti', 'exact_or_section3_name80',
           'exact_or_partsection5_name80', 'section5_direct80', 'section5_direct90',
           'section10_direct80', 'section5_medium_unconditional']
dataset = []
for name, (output_name, primary) in SOURCES.items():
    initial = read_sheet(RESEARCH / f'{name}-first-pass' / f'{name}_before_scoring.xlsx')
    review_path = ROOT.parent / 'agents' / 'drafts' / f'{name}_independent_full.xlsx'
    if not review_path.exists():
        review_path = RESEARCH / f'{name}-first-pass' / f'{name}_AI_review.xlsx'
    reviewed = [row for row in read_sheet(review_path) if row['voter_name']]
    by_review_key = {review_key(row): row['strength'] for row in reviewed}
    assert len(by_review_key) == len(reviewed), name
    assert len({review_key(row) for row in initial}) == len(initial), name
    assert set(by_review_key).issubset({review_key(row) for row in initial}), name
    if name == 'concorde':
        assert len(initial) - len(reviewed) == 502
    else:
        assert len(initial) == len(reviewed)
    final = read_sheet(ROOT / 'output' / 'ac-no-grey' / f'{output_name}_voters.xlsx')
    final_grades = defaultdict(set)
    for row in final:
        final_grades[key(row)].add(str(row['strength'] or '').split(' - ')[0])
    section_units = defaultdict(set)
    part_section_units = defaultdict(set)
    for row in initial:
        label = row['section_raw']
        unit = row['apartment_unit']
        if label and unit:
            section_units[label].add(unit)
            part_section_units[(row['part'], label)].add(unit)
    for row_number, original in enumerate(initial, 2):
        grade = by_review_key.get(review_key(original), 'No Match')
        if grade not in LABELS:
            raise ValueError((name, row_number, grade))
        section = original['section_raw']
        flat = original['apartment_unit']
        grades = final_grades.get(key(original), set())
        base = 'Strong' if 'Strong' in grades else 'Medium' if 'Medium' in grades else 'Weak'
        record = {
            'apartment': name,
            'snapshot_row': row_number,
            'unit': flat,
            'epic': original['epic_number'],
            'voter_name': original['voter_name'],
            'section_raw': section,
            'human': grade,
            'current': base,
            'present_current_first_sheet': bool(grades),
            'other_section_flats': len(section_units[section] - {flat}) if section else 0,
            'other_part_section_flats': len(part_section_units[(original['part'], section)] - {flat}) if section else 0,
            **evidence(original, primary),
        }
        for scheme in schemes[1:]:
            record[scheme] = predict(record, scheme)
        dataset.append(record)

with (DESTINATION / 'row_predictions.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(dataset[0]))
    writer.writeheader()
    writer.writerows(dataset)

with (DESTINATION / 'confusion_counts.csv').open('w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['scheme', 'apartment', 'human_grade', 'model_strong', 'model_medium', 'model_weak_or_removed'])
    for scheme in schemes:
        for apartment in [*SOURCES, 'ALL']:
            subset = [r for r in dataset if apartment == 'ALL' or r['apartment'] == apartment]
            for human in LABELS:
                rows = [r for r in subset if r['human'] == human]
                counts = Counter(r[scheme] for r in rows)
                writer.writerow([scheme, apartment, human, counts['Strong'], counts['Medium'], counts['Weak']])

for scheme in schemes:
    print('\n' + scheme)
    for apartment in [*SOURCES, 'ALL']:
        rows = [r for r in dataset if apartment == 'ALL' or r['apartment'] == apartment]
        details = []
        for human in LABELS:
            group = [r for r in rows if r['human'] == human]
            c = Counter(r[scheme] for r in group)
            details.append(f"{human}={len(group)}:S{c['Strong']}/M{c['Medium']}/W{c['Weak']}")
        print(apartment, ' '.join(details))
