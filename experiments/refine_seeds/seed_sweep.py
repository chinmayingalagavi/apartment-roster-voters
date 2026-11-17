# Compare independent section evidence rules on historical reviewed voter-to-flat candidates.
# Inputs: historical pre-scoring spreadsheets, manual review sheets, roster config, and saved current workbooks.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import csv
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_precision'))
sys.path.insert(0, str(HERE.parent / 'pipeline_section'))
from run import APARTMENTS, RESEARCH, build, matching, normalized_connection, prepare, row_key, valid_anchor
from compare_from_candidates import unassigned_rows


def location(row):
    section = row['section_raw']
    return (str(row['part']), section) if section and str(section).strip() else None


def same_roll_address(first, second):
    """Approximate the existing household grouping with visible spreadsheet fields."""
    return (
        location(first) is not None and location(first) == location(second)
        and abs(int(first['serial_number']) - int(second['serial_number'])) <= 5
        and bool(first['address_group']) and first['address_group'] == second['address_group']
    )


def build_features(apartment, output_name, apartment_name, config):
    source, baseline = prepare(apartment, output_name, apartment_name, config)
    baseline_keys = {row_key(row) for row in baseline}
    roster = build.normalize_roster(config, build.read_roster_source(config))
    extra = unassigned_rows(RESEARCH / f'{apartment}-first-pass' / f'{apartment}_before_scoring.xlsx')
    inputs = pd.DataFrame(source + extra).rename(columns={'voter_name': 'name'})
    address = build.build_address_fields(inputs, roster, config).to_dict('records')
    named_pattern = build.compile_terms_re(config.address_names, allow_joined_words=False)
    exact_address = lambda row: bool(named_pattern.search(matching.normalize_address(row['house_number'])))

    direct_by_unit = defaultdict(list)
    dominance_group = defaultdict(list)
    for i, row in enumerate(source):
        row['current'] = row_key(row) in baseline_keys
        row['target'] = exact_address(row)
        row['parse_complete'] = address[i]['parsed_unit'] == row['apartment_unit']
        row['clean_complete'] = row['parse_complete'] and not row['long_address']
        row['score'] = float(row['name_match_pct'] or 0)
        row['names'] = normalized_connection(row)
        row['paired'] = False
        row['related_pair'] = False
        if row['direct']:
            direct_by_unit[row['apartment_unit']].append(i)
            for name in row['names']:
                dominance_group[row['apartment_unit'], name].append(i)

    # Require two voters, distinct roster names and independent evidence tying the two voters together.
    for indices in direct_by_unit.values():
        for i, j in combinations(indices, 2):
            a, b = source[i], source[j]
            if a['serial_number'] == b['serial_number'] or len(a['names'] | b['names']) < 2:
                continue
            relates = (matching.relation_identifies_voter(a['relation_name'], b['voter_name'])
                       or matching.relation_identifies_voter(b['relation_name'], a['voter_name']))
            if relates or same_roll_address(a, b):
                a['paired'] = b['paired'] = True
            if relates:
                a['related_pair'] = b['related_pair'] = True

    # Freeze support before selection. Neither the candidate's own flat nor other rows for it count.
    sections = defaultdict(lambda: defaultdict(set))
    for i, row in enumerate(source + extra):
        section = location(row)
        flat = row['apartment_unit']
        if section is None or not flat:
            continue
        sections['any'][section].add(flat)
        if exact_address(row) and address[i]['parsed_unit'] == flat:
            for evidence in ('named', 'pair', 'rel', 'exact', 'known', 'exact95'):
                sections[evidence][section].add(flat)
        if i >= len(source) or not row['direct']:
            continue
        if row['paired']:
            sections['pair'][section].add(flat)
            sections['known'][section].add(flat)
        if row['related_pair']:
            sections['rel'][section].add(flat)
        if row['clean_complete'] and row['multiword'] and row['score'] >= 95:
            sections['exact95'][section].add(flat)
            if row['score'] == 100:
                sections['known'][section].add(flat)
                sections['exact'][section].add(flat)

    # Estimate which name anchors would survive and preserve the current two-dominator rule.
    for i, row in enumerate(source):
        section = location(row)
        row['other'] = {evidence: len(by_section[section] - {row['apartment_unit']}) for evidence, by_section in sections.items()}
        if row['direct']:
            score, booth = row['score'], row['other_booth_flats']
            row['remaining_connections'] = {
                name for name in row['names']
                if sum(source[j]['score'] >= score and source[j]['other_booth_flats'] >= booth
                       and (source[j]['score'] > score or source[j]['other_booth_flats'] > booth)
                       for j in dominance_group[row['apartment_unit'], name]) < 2
            }
    for row in source:
        row['anchors'] = frozenset(i for i in direct_by_unit[row['apartment_unit']] if valid_anchor(row, source[i]))
    return source


def select(source, evidence, count, score, complete, rescue):
    eligible = set()
    for i, row in enumerate(source):
        section_ok = row['other'].get(evidence, 0) >= count and row['score'] >= score
        if complete == 'clean':
            section_ok = section_ok and row['clean_complete']
        elif complete == 'complete':
            section_ok = section_ok and row['parse_complete']
        exact_fallback = (row['direct'] and row['clean_complete']
                          and row['score'] == 100 and row['multiword'])
        fallback = ((rescue == 'pair' and row['paired'])
                    or (rescue in ('rel', 'rel_exact', 'rel_exact_inherit') and row['related_pair'])
                    or (rescue in ('rel_complete', 'rel_complete_exact', 'rel_complete_inherit')
                        and row['related_pair'] and row['parse_complete'])
                    or (rescue in ('exact', 'rel_exact', 'rel_complete_exact',
                                   'rel_exact_inherit', 'rel_complete_inherit') and exact_fallback))
        if row['target'] or section_ok or fallback:
            eligible.add(i)
    anchors = {i for i in eligible if source[i]['direct'] and source[i]['remaining_connections']}
    dependents = {i for i in eligible if not source[i]['direct'] and source[i]['anchors'] & anchors}
    if rescue.endswith('_inherit'):
        dependents.update(i for i, row in enumerate(source) if not row['direct'] and row['parse_complete']
                          and row['anchors'] & anchors)
    return anchors | dependents


def summarize(apartment, source, selected, rule):
    result = dict(apartment=apartment, rule=rule)
    for label, name in (('supported', 'supported'), ('lower', 'lower')):
        of_label = {i for i, row in enumerate(source) if ('supported' if row['manual'] in ('Strong', 'Medium') else 'lower') == label}
        before = {i for i in of_label if source[i]['current']}
        after = of_label & selected
        result.update({name: len(after), f'gained_{name}': len(after - before), f'lost_{name}': len(before - after)})
    return result


def main():
    configs = build._load_apartment_run_config(build.DEFAULT_APARTMENTS_CSV)[0]
    buildings = {key: build_features(key, name, apartment, configs[name])
                 for key, (name, apartment) in APARTMENTS.items()}
    rules = [(evidence, count, score, complete, rescue)
             for evidence in ('any', 'named', 'pair', 'rel', 'exact', 'exact95', 'known')
             for count in (1, 2, 3, 5)
             for score in (0, 50, 60, 70, 80, 90)
             for complete in ('any', 'complete', 'clean')
             for rescue in ('none', 'pair', 'rel', 'exact')]
    rules.extend(('named', 1, 0, 'any', rescue) for rescue in
                 ('rel_complete', 'rel_exact', 'rel_complete_exact', 'rel_exact_inherit', 'rel_complete_inherit'))
    results = []
    for rule in (None, *rules):
        name = '/'.join(map(str, rule)) if rule else 'current'
        apartment_counts = []
        for apt, source in buildings.items():
            selected = select(source, *rule) if rule else {i for i, row in enumerate(source) if row['current']}
            apartment_counts.append(summarize(apt, source, selected, name))
        results.extend(apartment_counts)
        numeric = {key: sum(row[key] for row in apartment_counts) for key in apartment_counts[0] if key not in ('apartment', 'rule')}
        results.append(dict(apartment='all', rule=name, **numeric))

    with (HERE / 'summary.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)


if __name__ == '__main__':
    main()
