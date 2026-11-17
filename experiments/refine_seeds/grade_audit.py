# Compare confidence grades for the named-section and family eligibility experiments.
# Inputs: actual preliminary pipeline snapshots and reviewed voter-to-flat candidate labels.
# AUTHOR: Chinmay and AI

from collections import Counter
import csv
import pickle
import sys

from live_rule import HERE, SNAPSHOTS, identity, link, make_candidates, matcher, section_key, select


def grade_trial(captured, labels, variant):
    rows, _, support = select(captured, variant)
    source = captured['args'][0].set_index('_row_id')
    counts = Counter()
    for row in rows.to_dict('records'):
        row_id, unit = key = link(row)
        if not unit or row['apartment_status'] == matcher.UNASSIGNED_STATUS:
            continue
        complete = source.at[row_id, 'parsed_unit'] == unit
        exact_apartment = key in support['explicit']
        family_pair = key in support['paired']
        exact_name = key in support['exact']
        neighbors = len(support['named_flats'].get(section_key(row), set()) - {unit})
        score = row['name_match_pct'] or 0
        core = exact_apartment or family_pair
        strong = {
            'explicit_or_pair': core,
            'complete_with_2_named': core or complete and neighbors >= 2,
            'complete_with_2_named_and_75_name': core or complete and neighbors >= 2 and score >= 75,
            'complete_with_2_named_or_exact_name': core or complete and neighbors >= 2 or exact_name,
        }
        label = labels.get(identity(row), 'Unreviewed')
        label_group = {'Strong': 'supported', 'Medium': 'supported', 'Unlikely': 'lower', 'No Match': 'lower'}.get(label, label)
        for rule, is_strong in strong.items():
            counts[rule, 'Strong' if is_strong else 'Medium', label_group] += 1
    return [dict(rule=rule, grade=grade, label_group=label, count=count) for (rule, grade, label), count in sorted(counts.items())]


def main():
    candidates = make_candidates()
    rows = []
    variants = sys.argv[1:] or ('family_and_exact', 'section_complete', 'section_score')
    for path in sorted(SNAPSHOTS.glob('*.pickle')):
        with path.open('rb') as handle:
            captured, _, _ = pickle.load(handle)
        apt = {'silicon_oasis': 'silicon', 'tirumala_vintage': 'tirumala'}.get(path.stem, path.stem)
        labels = {(str(row['serial']), str(row['unit']), str(row['status'] or '')): row['manual']
                  for row in candidates if row['apartment'] == apt}
        for variant in variants:
            rows.extend(dict(apartment=path.stem, variant=variant, **result) for result in grade_trial(captured, labels, variant))
        del captured
    with (HERE / 'grades.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    main()
