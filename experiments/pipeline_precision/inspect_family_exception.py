# Test an offline cross-part family exception on reviewed candidate snapshots and actual section results.
# Inputs: reviewed candidate workbooks, existing output workbooks, and pipeline_section/pipeline_changes.csv.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
import csv
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_section'))
from compare_from_candidates import make_candidates, matching


def key(row):
    return (row['apartment'], str(row['serial']), str(row['unit']), str(row['status'] or ''))


def words(value):
    return matching.normalized_name_words(value).strip()


def main():
    candidates = make_candidates()
    names = {'silicon_oasis': 'silicon', 'tirumala_vintage': 'tirumala'}
    selected = {key(row) for row in candidates if row['current']}
    with (HERE.parent / 'pipeline_section/pipeline_changes.csv').open() as handle:
        for row in csv.DictReader(handle):
            if row['variant'] != 'section2_score0_dominance1':
                continue
            candidate_key = (names.get(row['apartment'], row['apartment']), row['serial'], row['unit'], row['status'])
            if row['change'] == 'lost':
                selected.discard(candidate_key)
            elif row['change'] == 'gained':
                selected.add(candidate_key)

    # Seed only original selected direct-name voters, grouped by apartment and flat.
    groups = defaultdict(list)
    for row in candidates:
        if key(row) in selected and 'voter_name_match' in str(row['link_type']):
            groups[(row['apartment'], str(row['unit']))].append(row)

    # A candidate qualifies if either person explicitly names the other as a relation.
    # Require different voter rows, a different polling part, and at least two words
    # in the relationship name. This estimates candidate eligibility, not final output.
    results = []
    for candidate in candidates:
        if key(candidate) in selected:
            continue
        for anchor in groups[(candidate['apartment'], str(candidate['unit']))]:
            if str(anchor['serial']) == str(candidate['serial']) or str(anchor['part']) == str(candidate['part']):
                continue
            a_name, a_relative = words(anchor['voter_name']), words(anchor['relation_name'])
            b_name, b_relative = words(candidate['voter_name']), words(candidate['relation_name'])
            matching_names = [n for n in (b_relative if b_relative == a_name else '',
                                          a_relative if a_relative == b_name else '') if n]
            if any(len(n.split()) >= 2 for n in matching_names):
                results.append(candidate)
                break

    # Check whether all characters of the target flat appear together in the
    # candidate's address after removing separators. This is only an offline
    # approximation, not the matcher's unambiguous address parser.
    def complete_flat(row):
        flat = re.sub(r'[^A-Z0-9]', '', str(row['unit']).upper())
        address = re.sub(r'[^A-Z0-9]', '', str(row['house_number']).upper())
        return bool(flat and flat in address)

    print('Cross-part explicit family exception; historical candidates only')
    for variant in ('family', 'family_complete_flat_text'):
        for apartment in ('concorde', 'purnima', 'silicon', 'tirumala', 'ALL'):
            subset = [r for r in results if (apartment == 'ALL' or r['apartment'] == apartment)
                      and (variant == 'family' or complete_flat(r))]
            print(variant, apartment, len(subset), dict(Counter(r['manual'] for r in subset)),
                  'previously_on_first_sheet', sum(r['current'] for r in subset))
    for row in results:
        row['complete_flat_text'] = complete_flat(row)
    with (HERE / 'family_exception_candidates.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]) if results else ['apartment'])
        writer.writeheader()
        writer.writerows(results)


if __name__ == '__main__':
    main()
