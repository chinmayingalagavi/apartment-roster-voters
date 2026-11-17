# End-to-end tests for recovering reviewed candidates

These are temporary full matcher runs. They use the same constituency voter file, four rosters, own-name and household checks, dominance ranking, and final grey-row suppression as the current matcher. The only experimental change is the eligibility exception described below. They do not alter the main code or published outputs.

## Section support exception

Freeze, from the first resolved candidate set, the number of **other distinct candidate flats** with the same nonblank `section_raw` and polling part. During normal confidence calculation, upgrade candidates that would otherwise fall below the review cutoff to Medium if that section count is at least five. Existing Strong, Medium, and Needs review grades remain calculated normally. All matching, direct-anchor checks, dominance, and the final grey-row filter are still applied. The candidates and their supporting people must have first passed the existing matching rules. A higher section count can include incorrect provisional candidates.

The full runs gave these changes relative to the existing first sheets:

| Apartment | Reviewer Strong/Medium, before | Reviewed Strong/Medium gained | Reviewer Unlikely/No Match gained | Existing links lost | Unreviewed links gained |
| --- | ---: | ---: | ---: | ---: | ---: |
| Concorde | 191 | 8 | 1 | 0 | 0 |
| Purnima | 3 | 0 | 0 | 0 | 0 |
| Silicon Oasis | 461 | 15 | 1 | 0 | 0 |
| Tirumala | 40 | 2 | 0 | 0 | 0 |
| Total | 695 | 25 | 2 | 0 | 0 |

These are candidate links, not independently verified people or residences. They are compared by voter serial number, flat, and roster status. The eight Concorde supported gains are eight voters in five flats, including one name-linked voter and three relation-linked voters at one flat. All five relation-linked gains across the four apartments have the named supporting own-name voter visible at their flat in the experimental output.

The Concorde lower-rated gain has a complete flat but an address naming a likely misspelling of a different development. The Silicon lower-rated gain has a bare house number, with no block. Both are documented in the ignored row-level results. For Concorde, No Match labels were reconstructed from omitted rows; the same omission pattern was verified against complete review files for the other apartments.

The Concorde and Purnima baselines were rerun fresh and their first sheets matched the saved current outputs exactly. For Silicon and Tirumala, the comparison uses the saved current first sheets. The input and code currently have no alternate apartment names configured for these four apartments.

## Simple 50% cutoff, partial run

A separate full-pipeline test relaxed the linked voter's name score to above 50% for the Needs review tier and kept other existing rules. Concorde gained five reviewed-supported and 101 reviewer-lower-rated links. Purnima gained four reviewed-supported and 31 reviewer-lower-rated links. Neither lost baseline links and neither added unreviewed links. The test was stopped after these two apartments because it was highly permissive. Those two fresh baselines matched the saved output.

## Complete-flat guard: full pipeline rerun

A second full run adds a universal condition to the section-support exception: the existing address parser must identify one unique unit and it must equal the proposed flat. This condition applies only to the new below-cutoff exception, so the existing baseline matching rules can still accept other addresses. It does not add new routes for relative or household attachment.

| Apartment | Reviewer-supported links gained | Reviewer-lower-rated links gained | Baseline links lost | Unreviewed links gained |
| --- | ---: | ---: | ---: | ---: |
| Concorde | 8 | 1 | 0 | 0 |
| Purnima | 0 | 0 | 0 | 0 |
| Silicon Oasis | 15 | 0 | 0 | 0 |
| Tirumala | 2 | 0 | 0 | 0 |
| Total | 25 | 1 | 0 | 0 |

The guard removed the Silicon bare-number error while preserving all 25 reviewed-supported gains through an actual full-pipeline rerun. The one remaining lower-rated Concorde candidate provides a complete unit but names a likely misspelling of a different development. In the unguarded run, all five new relative-linked rows had their own-name supporting voter visible on the same flat; the guarded rerun removed only the Silicon bare-number false candidate, an own-name link.

Of the seven historical reviewer-supported links still absent from the first sheet, four are Purnima, two are Silicon, and one is Tirumala. One Silicon voter already appears on the second sheet as an Unassigned, address-supported row. The other six are not visible by name on either voter sheet.

## Long-address guard analysis

The `inspect_gained_addresses.py` script evaluates current address-parser flags on the actual new rows. The existing long-unexplained-address flag marks the Concorde lower-rated gain, but also marks two supported Silicon gains whose voter addresses truncate the apartment name. Adding this guard could lose those two matches and is not recommended based on that observation alone. This is a row-level analysis; it does not simulate cascading anchor dependencies.

## Reproduction

Run with pandas and openpyxl installed, from `final/`:

```sh
python3 experiments/pipeline_recall/test_section5.py
python3 experiments/pipeline_recall/test_section5.py --guard
python3 experiments/pipeline_recall/diff_outputs.py
python3 experiments/pipeline_recall/inspect_gained_addresses.py
```

`test_cutoff.py` reruns the partial 50% comparison from scratch, then proceeds to Silicon and Tirumala. Runs read local voter files and can take several minutes per apartment. The workbooks, CSVs and row-level details are ignored by Git, because they contain personal data.

The benchmark reviews are subjective, include related voters and candidates from a historical matcher, and used the same geographic evidence in making their judgments. The section thresholds were chosen on these same four apartments, so these are not held-out estimates of future accuracy. New apartments and independently verified matches are needed to assess generalization.
