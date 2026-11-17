# Compare simple booth and section support cutoffs against independent manual labels in pre-scoring workbooks.
# Inputs: agents/drafts/*_independent_full.xlsx; results are written next to this script.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
import csv
import re

from openpyxl import load_workbook

PROJECT = Path(__file__).resolve().parents[3]
RESULTS = Path(__file__).resolve().parent
APARTMENTS = {
    'Concorde Midway': ('concorde_before_scoring.xlsx', 'Concorde Midway'),
    'Purnima Classic': ('purnima_independent_full.xlsx', 'Purnima Classic'),
    'Silicon Oasis': ('silicon_independent_full.xlsx', 'Silicon Oasis'),
    'Tirumala Vintage': ('tirumala_independent_full.xlsx', 'Tirumala Vintage'),
}


def normalize(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).split())


def read_rows(name, filename, label):
    folder = PROJECT / 'agents' / 'drafts'
    if name == 'Concorde Midway':
        folder = PROJECT / 'agents' / 'research' / 'concorde-first-pass'
    book = load_workbook(folder / filename, read_only=True, data_only=True)
    values = book['voters_mapped_tohouse'].values
    columns = next(values)
    rows = [dict(zip(columns, item)) for item in values]
    book.close()
    if name == 'Concorde Midway':
        # The review copy has 226 labelled rows and 502 completely blank rows.
        # Infer omitted rows as No Match only after checking every other cell exactly.
        review = load_workbook(folder / 'concorde_AI_review.xlsx', read_only=True, data_only=True)
        reviewed_values = review['voters_mapped_tohouse'].values
        reviewed_columns = next(reviewed_values)
        assert reviewed_columns == columns
        reviewed = [dict(zip(columns, item)) for item in reviewed_values]
        review.close()
        key_columns = [column for column in columns if column != 'strength']
        def key(row):
            return tuple(row[column] for column in key_columns)
        original_keys = {key(row) for row in rows}
        assert len(original_keys) == len(rows)
        labelled = {key(row): row['strength'] for row in reviewed if row['strength']}
        assert len(labelled) == sum(bool(row['strength']) for row in reviewed)
        assert set(labelled) <= original_keys
        assert sum(not any(row.values()) for row in reviewed) == len(rows) - len(labelled) == 502
        for row in rows:
            row['strength'] = labelled.get(key(row), 'No Match (inferred)')
    booths, section_parts, sections = defaultdict(set), defaultdict(set), defaultdict(set)
    booth_rows, section_part_rows, section_rows = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in rows:
        unit = str(row['apartment_unit'] or '')
        section = str(row['section_raw'] or '').strip()
        part = str(row['part'] or '').strip()
        if not unit:
            continue
        booths[part, str(row['pollingname'] or '').strip()].add(unit)
        booth_rows[part, str(row['pollingname'] or '').strip()].append(unit)
        if section:
            section_parts[part, section].add(unit)
            sections[section].add(unit)
            section_part_rows[part, section].append(unit)
            section_rows[section].append(unit)
    for row in rows:
        unit = str(row['apartment_unit'] or '')
        part = str(row['part'] or '').strip()
        section = str(row['section_raw'] or '').strip()
        row['booth_count'] = len(booths[part, str(row['pollingname'] or '').strip()] - {unit})
        row['section_part_count'] = len(section_parts.get((part, section), set()) - {unit})
        row['section_count'] = len(sections.get(section, set()) - {unit})
        row['booth_voters'] = sum(other != unit for other in booth_rows[part, str(row['pollingname'] or '').strip()])
        row['section_part_voters'] = sum(other != unit for other in section_part_rows.get((part, section), []))
        row['section_voters'] = sum(other != unit for other in section_rows.get(section, []))
        row['apartment'] = name
        row['exact_apartment'] = bool(re.search(r'\b' + re.escape(normalize(label)) + r'\b', normalize(row['house_number'])))
        row['truth'] = str(row['strength']).split(' - ')[0]
    return rows


data = []
for name, (filename, label) in APARTMENTS.items():
    rows = read_rows(name, filename, label)
    data += rows
    print(name, len(rows), dict(Counter(r['truth'] for r in rows)))

fields = ['apartment','apartment_unit','serial_number','voter_name','strength','name_match_pct',
          'house_number','section_raw','part','booth_count','section_part_count','section_count',
          'booth_voters','section_part_voters','section_voters','exact_apartment']
with (RESULTS / 'manual_row_features.csv').open('w', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(data)

summary = []
for grouping in ('booth_count', 'section_part_count', 'section_count', 'booth_voters', 'section_part_voters', 'section_voters'):
    for threshold in (1, 2, 3, 5, 10, 20, 50):
        for name, scope in [('All', data), *((n, [r for r in data if r['apartment'] == n]) for n in APARTMENTS)]:
            predicted = lambda r: r['exact_apartment'] or r[grouping] >= threshold
            label = lambda r: r['truth'] in ('Strong', 'Medium')
            tp = sum(predicted(r) and label(r) for r in scope)
            fp = sum(predicted(r) and not label(r) for r in scope)
            fn = sum(not predicted(r) and label(r) for r in scope)
            tn = sum(not predicted(r) and not label(r) for r in scope)
            summary.append([grouping, threshold, name, tp, fp, fn, tn, round(tp/(tp+fn),3) if tp+fn else '', round(tp/(tp+fp),3) if tp+fp else ''])
with (RESULTS / 'section_threshold_summary.csv').open('w', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['grouping','threshold','apartment','supported_retained','unlikely_or_no_match_retained','supported_missed','unlikely_or_no_match_excluded','recall','precision'])
    writer.writerows(summary)
for entry in summary:
    if entry[2] == 'All':
        print(*entry)


# Compare two fixed three-tier rules using the same candidate population.
def grade(row, grouping):
    score = float(row['name_match_pct'] or 0)
    if grouping == 'section':
        count = row['section_count']
        if row['exact_apartment'] or count >= 10:
            return 'Strong'
        if count >= 3 and score >= 95:
            return 'Medium'
    else:
        count = row['booth_count']
        if row['exact_apartment'] or count >= 5:
            return 'Strong'
        if count >= 3:
            return 'Medium'
    return 'Weak'


with (RESULTS / 'grading_confusion.csv').open('w', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['scheme', 'apartment', 'grade', 'human_strong', 'human_medium',
                     'human_unlikely', 'human_no_match', 'human_no_match_inferred'])
    for scheme in ('section', 'booth'):
        for apartment in APARTMENTS:
            rows = [row for row in data if row['apartment'] == apartment]
            for tier in ('Strong', 'Medium', 'Weak'):
                counts = Counter(row['truth'] for row in rows if grade(row, scheme) == tier)
                writer.writerow([scheme, apartment, tier, *(counts[level] for level in
                    ('Strong', 'Medium', 'Unlikely', 'No Match', 'No Match (inferred)'))])
