#!/usr/bin/env python3
# Simulate candidate selection and grading from the reviewed first-pass workbooks and compare with current output.
# Inputs are the four initial and manual review workbooks and the four saved constituency output workbooks.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
import csv
from pathlib import Path
import re
import sys

import pandas as pd
from openpyxl import load_workbook

FINAL = Path(__file__).resolve().parents[2]
PROJECT = FINAL.parent
sys.path.insert(0, str(FINAL / 'code'))
import build_apartment_matches as build
import matching

RESEARCH = PROJECT / 'agents' / 'research'
OUT = Path(__file__).resolve().parent
APARTMENTS = {
    'concorde': ('concorde', 'Concorde Midway'),
    'purnima': ('purnima', 'Purnima Classic'),
    'silicon': ('silicon_oasis', 'Silicon Oasis'),
    'tirumala': ('tirumala_vintage', 'Tirumala Vintage'),
}
LABELS = ('Strong', 'Medium', 'Unlikely', 'No Match')


def load_sheet(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    data = iter(workbook['voters_mapped_tohouse'].values)
    header = next(data)
    result = [dict(zip(header, row)) for row in data]
    workbook.close()
    return [row for row in result if row.get('serial_number') is not None and row.get('apartment_unit')]


def row_key(row):
    return tuple(str(row[field] or '') for field in ('serial_number', 'apartment_unit', 'apartment_status'))


def review_key(row):
    fields = ('epic_number', 'serial_number', 'apartment_unit', 'apartment_status',
              'apartment_connection', 'voter_link_type')
    return tuple(str(row[field] or '') for field in fields)


def normalized_connection(row):
    if 'remaining_connections' in row:
        return row['remaining_connections']
    return {build.connection_name_key(value) for value in str(row['apartment_connection'] or '').split('; ') if value}


def name_words(row):
    return [token.text for key in ('voter_name', 'relation_name')
            for token in matching.full_word_tokens(matching.tokenize_name(row.get(key) or ''))]


def household_name_link(row, anchor):
    if any(matching.full_token_match(word, other) for word in name_words(row) for other in name_words(anchor)):
        return True
    return any(matching.whole_name_rule_match(row.get(first) or '', anchor.get(second) or '').matched
               for first in ('voter_name', 'relation_name') for second in ('voter_name', 'relation_name'))


def valid_anchor(row, anchor):
    if row_key(row) == row_key(anchor) or row['apartment_unit'] != anchor['apartment_unit']:
        return False
    if not normalized_connection(row).intersection(normalized_connection(anchor)):
        return False
    link_type = str(row['voter_link_type'] or '').split(';')
    if 'relation_name_match' in link_type:
        return matching.relation_identifies_voter(row['relation_name'] or '', anchor['voter_name'] or '')
    if 'same_address_household_member' in link_type:
        return (row['apartment_status'] == anchor['apartment_status']
                and row['address_group'] and row['address_group'] == anchor['address_group']
                and household_name_link(row, anchor))
    return False


def prepare(name, output_name, apartment_name, config):
    source = load_sheet(RESEARCH / f'{name}-first-pass' / f'{name}_before_scoring.xlsx')
    review_path = PROJECT / 'agents' / 'drafts' / f'{name}_independent_full.xlsx'
    if not review_path.exists():
        review_path = RESEARCH / f'{name}-first-pass' / f'{name}_AI_review.xlsx'
    review = load_sheet(review_path)
    grades = {review_key(row): row['strength'] for row in review}
    assert len(grades) == len(review)
    assert len({review_key(row) for row in source}) == len(source)
    assert set(grades).issubset({review_key(row) for row in source})
    if name == 'concorde':
        assert len(source) - len(review) == 502
    else:
        assert len(source) == len(review)

    # Use the current address parser to reproduce address groups for household links.
    roster = build.normalize_roster(config, build.read_roster_source(config))
    voter_frame = pd.DataFrame(source)
    voter_frame['name'] = voter_frame['voter_name']
    parsed = build.build_address_fields(voter_frame, roster, config)
    by_section, by_booth = defaultdict(set), defaultdict(set)
    for i, row in enumerate(source):
        row['manual'] = grades.get(review_key(row), 'No Match')
        row['address_group'] = parsed.iloc[i]['same_address_group_key']
        row['unique_unit'] = parsed.iloc[i]['address_unit'] == row['apartment_unit']
        row['long_address'] = bool(parsed.iloc[i]['has_long_unexplained_address'])
        row['multiword'] = build.has_multiple_name_words(row['voter_name'] or '')
        row['direct'] = 'voter_name_match' in str(row['voter_link_type'] or '').split(';')
        row['target'] = bool(re.search(r'\b' + re.escape(matching.normalize_address(apartment_name)) + r'\b',
                                       matching.normalize_address(row['house_number'])))
        if row['section_raw']:
            by_section[(row['part'], row['section_raw'])].add(row['apartment_unit'])
        by_booth[(row['part'], row['pollingname'])].add(row['apartment_unit'])
    for row in source:
        row['other_section_flats'] = len(by_section[(row['part'], row['section_raw'])] - {row['apartment_unit']}) if row['section_raw'] else 0
        row['other_booth_flats'] = len(by_booth[(row['part'], row['pollingname'])] - {row['apartment_unit']})
    visible = load_sheet(FINAL / 'output' / 'ac-no-grey' / f'{output_name}_voters.xlsx')
    return source, visible


def simulate(source, method, baseline_keys=None):
    # Candidate acceptance uses counts fixed on the unpruned preliminary set.
    accepted = []
    for row in source:
        section = row['other_section_flats']
        booth = row['other_booth_flats']
        score = float(row['name_match_pct'] or 0)
        if method in ('union_baseline', 'union_section3', 'union_section5'):
            threshold = {'union_baseline': 2, 'union_section3': 3, 'union_section5': 5}[method]
            keep = row_key(row) in baseline_keys or row['target'] or section >= threshold
        elif method in ('section2', 'section2_dom'):
            keep = row['target'] or section >= 2
        elif method == 'section2_dom_fullname':
            keep = (row['target'] or section >= 2 or
                    (row['direct'] and score == 100 and row['multiword']
                     and row['unique_unit'] and not row['long_address']))
        elif method == 'section3':
            keep = row['target'] or section >= 3
        elif method == 'section2_score70':
            keep = row['target'] or (section >= 2 and score > 70)
        elif method == 'booth2':
            keep = row['target'] or booth >= 2
        else:
            raise ValueError(method)
        if keep:
            accepted.append(row.copy())

    # For the optional ranking trial, discard only names dominated by two other voters.
    if method in ('section2_dom', 'section2_dom_fullname'):
        candidates = defaultdict(dict)
        for row in accepted:
            if row['direct']:
                for name in normalized_connection(row):
                    candidates[row['apartment_unit'], name][str(row['serial_number'])] = (
                        float(row['name_match_pct'] or 0), row['other_section_flats'])
        retained = []
        for row in accepted:
            if not row['direct']:
                retained.append(row)
                continue
            names = set()
            for name in normalized_connection(row):
                group = candidates[row['apartment_unit'], name]
                score, count = group[str(row['serial_number'])]
                dominators = sum(other_score >= score and other_count >= count
                                 and (other_score > score or other_count > count)
                                 for other_score, other_count in group.values())
                if dominators < 2:
                    names.add(name)
            if names:
                row['remaining_connections'] = names
                retained.append(row)
        accepted = retained

    # Require every dependent to have an accepted specific own-name voter at its flat.
    # Removing a dependent cannot remove an own-name anchor, so this reaches a fixed point in one pass.
    anchors = defaultdict(list)
    for row in accepted:
        if row['direct']:
            anchors[row['apartment_unit']].append(row)
    if method in ('union_baseline', 'union_section3', 'union_section5'):
        # Preserve an already displayed dependent's supporting voter when it was hidden by earlier filtering.
        candidates = defaultdict(list)
        for candidate in source:
            if candidate['direct']:
                candidates[candidate['apartment_unit']].append(candidate)
        for row in list(accepted):
            if row['direct'] or any(valid_anchor(row, anchor) for anchor in anchors[row['apartment_unit']]):
                continue
            options = [anchor for anchor in candidates[row['apartment_unit']] if valid_anchor(row, anchor)]
            if options:
                anchor = max(options, key=lambda item: (item['other_section_flats'], float(item['name_match_pct'] or 0)))
                accepted.append(anchor)
                anchors[row['apartment_unit']].append(anchor)
    return [row for row in accepted if row['direct'] or any(
        valid_anchor(row, anchor) for anchor in anchors[row['apartment_unit']]
    )]


def main():
    configs = build._load_apartment_run_config(build.DEFAULT_APARTMENTS_CSV)[0]
    results = []
    details = []
    for name, (output_name, apartment_name) in APARTMENTS.items():
        source, visible = prepare(name, output_name, apartment_name, configs[output_name])
        visible_by_key = {row_key(row): row for row in visible}
        assert len(visible_by_key) == len(visible), name
        labels = {row_key(row): row['manual'] for row in source}
        assert len(labels) == len(source), name
        total_positive = sum(label in ('Strong', 'Medium') for label in labels.values())
        for method in ('current', 'section2', 'section2_dom', 'section2_dom_fullname', 'section3', 'section2_score70', 'booth2', 'union_baseline', 'union_section3', 'union_section5'):
            selected = ([row for row in source if row_key(row) in visible_by_key] if method == 'current'
                        else simulate(source, method, set(visible_by_key)))
            selected_keys = {row_key(row) for row in selected}
            positive = sum(row['manual'] in ('Strong', 'Medium') for row in selected)
            negative = sum(row['manual'] in ('Unlikely', 'No Match') for row in selected)
            gained = selected_keys - set(visible_by_key)
            lost = (set(visible_by_key) & set(labels)) - selected_keys
            unreviewed = len(set(visible_by_key) - set(labels)) if method == 'current' else 0
            counts = {'apartment': name, 'method': method, 'candidate_rows': len(source),
                      'reviewer_positive_total': total_positive, 'selected_positive': positive,
                      'selected_negative': negative, 'unreviewed_output': unreviewed,
                      'gained_positive': sum(labels[k] in ('Strong', 'Medium') for k in gained),
                      'gained_negative': sum(labels[k] in ('Unlikely', 'No Match') for k in gained),
                      'lost_positive': sum(labels[k] in ('Strong', 'Medium') for k in lost),
                      'lost_negative': sum(labels[k] in ('Unlikely', 'No Match') for k in lost)}
            results.append(counts)
            for row in source:
                key = row_key(row)
                output_grade = ''
                if key in selected_keys:
                    if key in visible_by_key and (method.startswith('union_') or method == 'current'):
                        output_grade = str(visible_by_key[key]['strength']).split(' - ')[0]
                    elif row['target'] or row['other_section_flats'] >= 5:
                        output_grade = 'Strong'
                    elif row['other_section_flats'] >= 2:
                        output_grade = 'Medium'
                    else:
                        output_grade = 'Weak'
                details.append({'apartment': name, 'method': method, 'unit': row['apartment_unit'],
                                'serial_number': row['serial_number'], 'voter_name': row['voter_name'],
                                'manual': row['manual'], 'current': row_key(row) in visible_by_key,
                                'selected': key in selected_keys, 'output_grade': output_grade,
                                'section_flats': row['other_section_flats'], 'booth_flats': row['other_booth_flats'],
                                'link': row['voter_link_type'], 'score': row['name_match_pct']})
            print(counts)
    for filename, rows in (('results.csv', results), ('rows.csv', details)):
        with (OUT / filename).open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == '__main__':
    main()
