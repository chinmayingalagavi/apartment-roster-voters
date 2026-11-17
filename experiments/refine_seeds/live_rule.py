# Run named-section and corroborated-family selection on fresh in-memory candidate captures.
# Inputs: private capture files made from the constituency voter file, apartment rosters and current matcher.
# AUTHOR: Chinmay and AI

from argparse import ArgumentParser
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
import csv
import pickle
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
SNAPSHOTS = HERE.parent / 'refine_scores' / 'generated'
VARIANTS = ('named', 'family', 'family_complete', 'family_and_exact', 'section_complete',
            'section_score', 'section_clean', 'inherit', 'cross_part', 'named_relative')
sys.path.insert(0, str(HERE.parent / 'pipeline_section'))
from run_pipeline import identity, matcher
from compare_from_candidates import make_candidates


def section_key(row):
    value = row['section_raw']
    return (str(row['part']), value) if pd.notna(value) and str(value).strip() else None


def link(row):
    return int(row['_row_id']), row['apartment_unit']


def pair_links(first, evidence, source, complete):
    """Find corroborated own-name pairs whose relation explicitly links the two voters."""
    by_unit = defaultdict(list)
    claimed = matcher.corroborated_roster_matches(evidence)
    for row in first.to_dict('records'):
        if row['apartment_status'] == matcher.UNASSIGNED_STATUS or 'voter_name_match' not in row['voter_link_type'].split(';'):
            continue
        row_id, unit = link(row)
        if row_id not in claimed or claimed[row_id][0] != unit:
            continue
        if complete and source.at[row_id, 'parsed_unit'] != unit:
            continue
        by_unit[unit].append(row)

    paired = set()
    for candidates in by_unit.values():
        for a, b in combinations(candidates, 2):
            if claimed[link(a)[0]] == claimed[link(b)[0]]:
                continue
            if (matcher.matcher.relation_identifies_voter(a['relation_name'], b['voter_name'])
                    or matcher.matcher.relation_identifies_voter(b['relation_name'], a['voter_name'])):
                paired.update((link(a), link(b)))
    return paired


def named_relative_anchors(first, evidence, source, explicit_links):
    """Rescue a unique own-name anchor identified by a voter whose address names the building and flat."""
    identified = defaultdict(set)
    independent = defaultdict(list)
    direct = {link(row) for row in first.to_dict('records')
              if row['apartment_status'] != matcher.UNASSIGNED_STATUS
              and 'voter_name_match' in row['voter_link_type'].split(';')}
    for (unit, _), records in evidence.items():
        for row_id, record in records.items():
            if (row_id, unit) not in direct or source.at[row_id, 'parsed_unit'] != unit:
                continue
            for hit in record['person_hits']:
                if 'anchor_voter_row_id' not in hit:
                    independent[unit, hit['roster_row_id']].append((row_id, hit['voter_name']))
    for (unit, _), records in evidence.items():
        for row_id, record in records.items():
            key = row_id, unit
            if key not in explicit_links or key in direct or source.at[row_id, 'parsed_unit'] != unit:
                continue
            for hit in record['relation_hits']:
                identified[key].update(
                    (other_id, unit) for other_id, name in independent[unit, hit['roster_row_id']]
                    if other_id != row_id and matcher.matcher.relation_identifies_voter(hit['relation_name'], name)
                )
    return {next(iter(anchors)) for anchors in identified.values() if len(anchors) == 1}


def select(captured, variant='family_and_exact'):
    voters, roster, config, evidence, address_groups, _ = captured['args']
    first = captured['initial'].copy()
    source = voters.set_index('_row_id')
    named_pattern = matcher.compile_terms_re(config.address_names, allow_joined_words=False)
    named_flats = defaultdict(set)
    named_across_parts = defaultdict(set)
    explicit_links, exact_names = set(), set()
    for row in first.to_dict('records'):
        row_id, unit = key = link(row)
        if not unit:
            continue
        complete = source.at[row_id, 'parsed_unit'] == unit
        section = section_key(row)
        if named_pattern.search(source.at[row_id, 'address_norm']):
            explicit_links.add(key)
            if complete and section is not None:
                named_flats[section].add(unit)
                named_across_parts[section[1]].add(unit)
        if (complete and row['apartment_status'] != matcher.UNASSIGNED_STATUS
                and 'voter_name_match' in row['voter_link_type'].split(';')
                and not source.at[row_id, 'has_long_unexplained_address']
                and row['name_match_pct'] == 100 and matcher.has_multiple_name_words(row['voter_name'])):
            exact_names.add(key)

    paired = pair_links(first, evidence, source, complete=variant != 'family') if variant != 'named' else set()
    keep = set(explicit_links) | paired
    if variant not in {'named', 'family', 'family_complete'}:
        keep |= exact_names
    if variant == 'named_relative':
        keep |= named_relative_anchors(first, evidence, source, explicit_links)
    for row in first.to_dict('records'):
        row_id, unit = key = link(row)
        if not unit:
            continue
        section = section_key(row)
        section_supported = bool(named_flats.get(section, set()) - {unit})
        complete = source.at[row_id, 'parsed_unit'] == unit
        score = row['name_match_pct']
        if variant == 'cross_part' and section is not None and complete:
            section_supported |= bool(named_across_parts[section[1]] - {unit})
        if variant == 'section_complete':
            section_supported = section_supported and complete
        if variant == 'section_score':
            section_supported = section_supported and (complete or score is not None and score >= 95)
        if variant == 'section_clean':
            section_supported = section_supported and complete and not source.at[row_id, 'has_long_unexplained_address']
        confirmed_dependent = (variant == 'inherit' and complete
                               and 'voter_name_match' not in row['voter_link_type'].split(';')
                               and row['apartment_status'] != matcher.UNASSIGNED_STATUS)
        if section_supported or confirmed_dependent:
            keep.add(key)
    outside = {link(row) for row in first.to_dict('records') if row['apartment_unit']} - keep

    # Keep the current comparison for competing matches, then recheck actual dependent anchors.
    booth_units = matcher.matched_units_at_booth(first)
    first['other_hh_matched_booth'] = matcher.other_households_matched_at_booth(first, booth_units)
    discarded = matcher.dominated_voter_links(first)
    output, unmapped = matcher.resolve_voter_links(
        voters, roster, config, evidence, address_groups, discarded,
        original_links=keep, excluded_links=outside,
    )
    tallies = {'named_flats': named_flats, 'paired': paired, 'exact': exact_names, 'explicit': explicit_links}
    return output, unmapped, tallies


def result_row(cfg, output, baseline, labels, trial):
    final = {identity(row) for row in output.to_dict('records')
             if row['apartment_unit'] and row['apartment_status'] != matcher.UNASSIGNED_STATUS}
    label_counts = lambda subset: Counter(labels.get(key, 'Unreviewed') for key in subset)
    result = dict(apartment=cfg.key, variant=trial)
    for field, links in (('', final), ('_gained', final - baseline), ('_lost', baseline - final)):
        counts = label_counts(links)
        result[f'supported{field}'] = counts['Strong'] + counts['Medium']
        result[f'lower{field}'] = counts['Unlikely'] + counts['No Match']
        result[f'unreviewed{field}'] = counts['Unreviewed']
    return result


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('apartments', nargs='*', default=('concorde', 'purnima', 'silicon_oasis', 'tirumala_vintage'))
    parser.add_argument('--variants', nargs='+', choices=VARIANTS, default=VARIANTS)
    parser.add_argument('--output-name', default='fresh_summary.csv')
    args = parser.parse_args()
    review_rows = make_candidates()
    summaries = []
    for apartment in args.apartments:
        capture_path = SNAPSHOTS / f'{apartment}.pickle'
        if not capture_path.exists():
            print(f'Capture not available yet: {apartment}', flush=True)
            continue
        with capture_path.open('rb') as data:
            captured, baseline, _ = pickle.load(data)
        config = captured['args'][2]
        review_name = {'silicon_oasis': 'silicon', 'tirumala_vintage': 'tirumala'}.get(apartment, apartment)
        labels = {(str(row['serial']), str(row['unit']), str(row['status'] or '')): row['manual']
                  for row in review_rows if row['apartment'] == review_name}
        for variant in args.variants:
            output, unmapped, tallies = select(captured, variant)
            result = result_row(config, output, baseline, labels, variant)
            summaries.append(result)
            print(result, flush=True)
        del captured, output, unmapped, tallies
    if summaries:
        with (HERE / Path(args.output_name).name).open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)


if __name__ == '__main__':
    main()
