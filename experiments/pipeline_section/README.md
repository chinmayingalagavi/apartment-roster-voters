# Named-address section evidence: candidate-only experiment

These are offline comparisons of historical preliminary candidates, **not a full pipeline rerun**. They do not change the matcher, workbook output, or application. Run `python3 experiments/pipeline_section/compare_from_candidates.py` from `final/` to reproduce `summary.csv` and `changed_candidates.csv`. The latter contains voter information and is ignored by Git.

The benchmark is the 2,013 mapped preliminary candidate links in the four earlier first-pass workbooks. The reviewers labeled 727 Strong/Medium and 1,286 Unlikely/No Match. The 502 Concorde No Match labels are inferred from source rows omitted from its reviewed workbook and the reviewer's stated count. The same omission pattern was checked against the complete independent reviews of the other three buildings. These are agent judgments based on records, not independently verified residence. Household rows are not independent observations, and reviewers used geographic evidence.

## Selection rule tested

Take a candidate if its own address explicitly names the apartment, or if **another distinct flat** has a preliminary candidate whose address names the apartment in the **same polling part and exact `section_raw`**. A named apartment address with a readable flat on the first-pass Unassigned sheet is also permitted as a source of section evidence. It is not treated as an own-name anchor for a dependent relation.

This is a single rule for all apartments. Exact names use the configured primary apartment name after address normalization. Section evidence uses candidates, not human grades, but can still include incorrect candidates and their locations. Section names must be nonblank and match exactly. The focal flat is excluded from the section support count.

| Rule applied to historical candidates | Reviewers' Strong/Medium retained | Reviewers' Unlikely/No Match retained |
| --- | ---: | ---: |
| Existing first sheets | 695 / 727 | 321 / 1,286 |
| Named-address section rule only | 712 / 727 | 14 / 1,286 |
| Named-address section rule, requiring candidate score >50 when its own address doesn't name apartment | 697 / 727 | 13 / 1,286 |

The rule-only counts per apartment are Concorde 198/199 supported and 4/529 lower-rated, Purnima 0/7 and 0/148, Silicon Oasis 471/478 and 5/164, and Tirumala 43/43 and 5/445. Despite including Unassigned named-address seed rows, Purnima's reviewed candidates lacked a *different* named flat in the same part and section. The matched sections differ from that of the seed and cannot benefit from this rule.

## Union with the existing first sheet

Keeping every currently visible candidate and adding candidates selected by the named-address section rule yields these **offline** additions within the 2,013 reviewed candidates:

| Apartment | Additional Strong/Medium per reviewers | Additional Unlikely/No Match per reviewers |
| --- | ---: | ---: |
| Concorde | 8 | 4 |
| Purnima | 0 | 0 |
| Silicon Oasis | 17 | 1 |
| Tirumala | 3 | 0 |
| Total | 28 | 5 |

Requiring `name_match_pct > 50` for non-explicit candidates changes the offline additions to 25 supported and 4 lower-rated; `>60` gives 17 and 1. The score in a household candidate can be inherited. A score gate can lose plausible family members as well as poor candidates.

## Interpretation and limitations

The union is a set operation on saved candidate keys. It does not verify that a selected relation or household row has a surviving eligible directly matched voter. One visible preliminary check found a named-address-selected Strong Tirumala relation with no corresponding selected direct-name anchor in the candidate snapshot. This candidate must be treated as address-only, or retain an independently eligible anchor, before it can appear as a household match. Therefore the offline gains are upper bounds, not confirmed recoveries.

An additional candidate-only fallback keeps a direct own-name match with a 100% score, at least two full words in the voter's name, and an explicitly matching block and flat. Combined with the named-address rule, it adds one reviewer-Medium Concorde candidate and zero lower-rated candidates within these historical snapshots. This only establishes the observed result on this benchmark. A different building can reuse a block and flat, and even an exact name needs location evidence.

The current first sheet already applies dominance, the 70% review cutoff, and grey suppression. The experiment does not recompute any of those decisions, candidate competition, matching features, or scores. In an actual run the newly retained candidates can alter the output and introduce links not in the reviewed snapshot. The snapshot excludes previously ungenerated candidates and its benchmark labels are not a holdout. New false positives outside that snapshot are unknown. A full pipeline experiment must preserve the rule requiring the identified voter to be attached to the flat, rerun from raw records, account for newly introduced unreviewed candidates, and compare complete outputs.

## Fresh resolver trial

`run_pipeline.py` reruns the current matcher from the configured full AC file and all four rosters, captures its first resolved candidate set, applies experimental selection, and calls the existing resolver to enforce own-name anchors again. Strong and Medium output grades and the final grey suppression are not applied to the experimental candidates. Its result is a **post-resolver candidate set**, not a final Excel first sheet and not a full replacement matcher. `pipeline_summary.csv` and `pipeline_changes.csv` are updated after each apartment. They are incomplete while a run is active.

Fresh run results:

| Apartment | Selection | Links retained | Reviewers' Strong/Medium | Reviewers' Unlikely/No Match | Gained vs current | Lost vs current |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Concorde | Current first sheet | 327 | 191 | 136 | – | – |
| Concorde | Same-part section ≥2 other flats, or own explicit apartment address | 256 | 198 | 58 | 46 | 117 |
| Concorde | Other distinct flat with explicit apartment name in same part and section, or own explicit apartment address | 202 | 198 | 4 | 12 | 137 |
| Purnima | Current first sheet | 55 | 3 | 52 | – | – |
| Purnima | Same-part section ≥2 other flats, or own explicit apartment address | 5 | 4 | 1 | 2 | 52 |
| Purnima | Other distinct flat with explicit apartment name in same part and section, or own explicit apartment address | 0 | 0 | 0 | 0 | 55 |
| Silicon Oasis | Current first sheet | 521 | 461 | 60 | – | – |
| Silicon Oasis | Same-part section ≥2 other flats, or own explicit apartment address | 473 | 468 | 5 | 16 | 64 |
| Silicon Oasis | Other distinct flat with explicit apartment name in same part and section, or own explicit apartment address | 475 | 470 | 5 | 17 | 63 |
| Tirumala | Current first sheet | 113 | 40 | 73 | – | – |
| Tirumala | Same-part section ≥2 other flats, or own explicit apartment address | 59 | 42 | 17 | 9 | 63 |
| Tirumala | Other distinct flat with explicit apartment name in same part and section, or own explicit apartment address | 47 | 42 | 5 | 3 | 69 |
| Total | Current first sheet | 1,016 | 695 | 321 | – | – |
| Total | Same-part section ≥2 other flats, or own explicit apartment address | 793 | 712 | 81 | 73 | 296 |
| Total | Other distinct flat with explicit apartment name in same part and section, or own explicit apartment address | 724 | 710 | 14 | 32 | 324 |

The current dominance step was retained in each trial above. Counts of other flats in the section are computed before pruning from the newly generated initial candidate list, including address-only Unassigned rows with parsed flats. They exclude the candidate's own flat. Purnima's explicitly named address-only voter is an Unassigned row, so it can supply section evidence and is omitted from the mapped-link counts in the table.

Concorde section ≥2 gains eight reviewer-Strong, 37 No Match and one Unlikely candidate; it loses one Medium, 101 No Match and 15 Unlikely links. The named-address rule gains eight reviewer-Strong and four No Match candidates; it loses one Medium, 119 No Match and 17 Unlikely. These are link counts, not independent people or households. Concorde's No Match judgments are inferred as explained above.

Across all four apartments, section ≥2 gains 28 reviewer-Strong/Medium and 45 lower-rated links, and loses 11 reviewer-Strong/Medium and 285 lower-rated links compared with the current first sheets. The named-address rule gains 27 reviewer-Strong/Medium and 5 lower-rated links, and loses 12 reviewer-Strong/Medium and 312 lower-rated links. No returned keys in this run were outside the reviewed first-pass candidate set. This does not imply that other input data could not generate unreviewed links.

The named-address rule with a >50 name-score requirement returned 24 additional reviewer-Strong/Medium and four lower-rated links, while losing 25 reviewer-Strong/Medium and 312 lower-rated links. In Silicon Oasis especially, this name gate lost reviewed matches with inherited household scores.

The candidate-based fallback tested above was not present in this already-running fresh trial. A previously attempted raw run was interrupted during candidate processing and produced no completed results.

## Complete experimental workbooks: section ≥2

`run_final_workbooks.py` applies one rule uniformly to fresh candidates from all four apartments: retain a voter–flat candidate if the address explicitly names that apartment **or** at least two *other distinct flats* have preliminary candidates in the same polling part and exact, nonblank `section_raw`. Support is counted from the preliminary candidate pool, including address-only Unassigned candidates with a parsed flat; it is not a count of independently confirmed households. The existing dominance rule is applied, and the existing resolver rebuilds direct-name, relation and household links. The candidate's own flat does not count toward its support.

For this experimental workbook only, the candidate is graded Strong if its address explicitly names the apartment or there are at least five other candidate flats in its part and section. Otherwise it is Medium if there are at least two. The current first-sheet rule that removes Needs review rows when a flat has a Strong row is then applied. In these experiments the selection conditions ensure no selected mapped row is Needs review, so the suppression step removes no first-sheet rows. This is a replacement selection and grading scheme, not a union with the current output. The outputs include all three sheets.

| Apartment | Current links | Experimental links | Experimental Strong / Medium | Reviewers supported / lower-rated | Supported gained / lost | Lower-rated gained / lost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Concorde | 327 | 256 | 199 / 57 | 198 / 58 | 8 / 1 | 38 / 116 |
| Purnima | 55 | 5 | 0 / 5 | 4 / 1 | 2 / 1 | 0 / 51 |
| Silicon Oasis | 521 | 473 | 472 / 1 | 468 / 5 | 15 / 8 | 1 / 56 |
| Tirumala | 113 | 59 | 43 / 16 | 42 / 17 | 3 / 1 | 6 / 62 |
| Total | 1,016 | 793 | 714 / 79 | 712 / 81 | 28 / 11 | 45 / 285 |

No first-sheet link was outside the available reviewer-labeled candidate set for these runs. This does not mean the result generalizes to other inputs. The fresh current baseline reproduced the saved current first-sheet links for each apartment.

The new grades also need scrutiny: across the four apartments the reviewers supported 703 of the 714 Strong links and 9 of the 79 Medium links. The 11 lower-rated Strong links and 70 lower-rated Medium links break down as follows:

| Apartment | Lower-rated Strong | Lower-rated Medium |
| --- | ---: | ---: |
| Concorde | 1 | 57 |
| Purnima | 0 | 1 |
| Silicon Oasis | 5 | 0 |
| Tirumala | 5 | 12 |

`audit_visible_anchors.py` independently inspects each completed workbook. Every relation or same-address household row has a compatible own-name match for the same flat visible on the first sheet in these four outputs. This checks existence of a compatible visible anchor; it does not prove that the resolver selected that particular voter when multiple anchors were compatible. It does not establish the match is correct. Some explicitly named-address voters whose relation anchor is removed appear as Unassigned on sheet 2 instead of as a mapped household match.

To reproduce from `final/`, run `python3 experiments/pipeline_section/run_final_workbooks.py`, then `python3 experiments/pipeline_section/audit_visible_anchors.py`. Results and voter-containing workbooks are stored in `experiments/pipeline_section/final_workbooks/` and ignored by Git. The review scores are judgments rather than confirmed ground truth and were used while designing these rules; a genuinely independent review is needed. The trial begins from the current generated preliminary candidates and does not search for voters the current preliminary generator never produces.
