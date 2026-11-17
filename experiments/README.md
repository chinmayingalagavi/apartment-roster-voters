# Grading experiments

This folder preserves the experiments that led to the final matcher. The approved named-section algorithm with the guarded 95% fallback is now implemented in `code/build_apartment_matches.py` and documented in the [main README](../README.md#matching-algorithm). Historical scripts depending on the old matcher should be run with source from commit `d13b699`; their references to the current algorithm describe that earlier baseline.

These experiments compare simple grading rules with the four independent agent reviews of the Bangalore South pre-scoring candidate workbooks. They do not change the matcher, its output, or the desktop app.

## Benchmark

The reviewed cohort contains 2,013 candidate voter-to-flat links. Reviewers classified 727 as Strong or Medium and 1,286 as Unlikely or No Match. These are agent judgments using the available records, not verified residence. Candidates can include multiple links involving the same voter or household. Unassigned and unmapped rows are outside this comparison.

For Concorde, the reviewed workbook contains 226 labeled candidates and the reported 502 No Match candidates are absent. Those 502 labels were inferred by matching all other row fields to the original candidate workbook and identifying the omitted rows. The same omission pattern was confirmed against complete independent review workbooks for the other three apartments.

The historical candidates are from an earlier, broader matching stage. Of the 727 manually Strong or Medium links, 695 survive in the current first sheet: Concorde 191 of 199, Purnima 3 of 7, Silicon Oasis 461 of 478, and Tirumala 40 of 43. A change to grading alone cannot restore the other 32. These results are based on existing saved outputs and have not been validated as changes to the matching pipeline.

## Recommended trial

Count **other distinct candidate flats** with the same nonblank section text and the same polling part. Count each other flat once, regardless of how many voters match it. Calculate these counts on the first candidate set before pruning.

1. **Strong:** the address has the configured apartment name, or at least five other flats share the section within the part.
2. **Medium:** at least two other flats share the section within the part and the Strong rule did not apply.
3. **Weak:** all remaining candidates.

Alternate configured apartment names should also count as the apartment name in a future implementation. The experiment used the primary names present in the historical workbooks.

On the 1,016 reviewed candidate links that appear on the current first sheet, the trial puts 685 of 695 manually Strong/Medium links in Strong or Medium. It also puts 37 of 321 Unlikely/No Match links in those grades. Existing grades put 690 of 695 manually Strong/Medium links, and 84 of 321 Unlikely/No Match links, in Strong or Medium. Under the trial, 672 manually Strong/Medium links and 9 lower-rated links are Strong, versus 670 and 24 with existing grades.

| Apartment | Manually Strong/Medium visible | Current graded Strong/Medium | Trial graded Strong/Medium | Lower-rated visible | Current graded Strong/Medium | Trial graded Strong/Medium |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Concorde | 191 | 191 | 190 | 136 | 41 | 21 |
| Purnima | 3 | 2 | 2 | 52 | 15 | 1 |
| Silicon Oasis | 461 | 457 | 453 | 60 | 13 | 4 |
| Tirumala | 40 | 40 | 40 | 73 | 15 | 11 |
| Total | 695 | 690 | 685 | 321 | 84 | 37 |

The trial keeps the other ten manually Strong/Medium links as Weak in the simulation. The numbers describe grading existing first-sheet rows only. The candidate flat counts used to simulate the trial were rebuilt from the historical pre-scoring files, not captured from the actual current matcher run. A complete temporary rerun is required to verify the counts and interactions with the dominance and grey-row rules.

For the 32 reviewed Strong/Medium candidates absent from the current first sheet, applying the trial offline labels 29 Strong/Medium. It would also label 56 of the 965 absent lower-rated candidates Strong/Medium. This is not a recovery test: restoring candidates may change support counts, dominance, household links and grey-row suppression.

## Other schemes

- Counting the same section text across all polling parts, with Strong at five other flats and Medium at two, grades 690 of the 695 visible manual Strong/Medium links Strong or Medium but also promotes 107 of 321 visible lower-rated links. This is weaker than the within-part rule for this sample.
- A stricter scheme across parts, Strong at ten other flats and Medium at three with a 95% name score, grades 708 of all 727 historical Strong/Medium candidates Strong or Medium and promotes 26 of 1,286 lower-rated candidates. Five of seven Purnima positives remain Weak. This scheme was evaluated on the historical candidate set, not as a current first-sheet rerun.
- Requiring high name scores for all candidates can lose real household links, whose supporting name scores can be low. The alternative schemes and complete confusion counts are in `agent_schemes/confusion_counts.csv`.

## Limitations

This is exploratory evaluation on the same apartments used to choose the cutoffs. The reviewers considered section and geographic context when grading, so the section result is not independent of the evidence it predicts. Nearly two thirds of manually Strong/Medium candidates come from Silicon Oasis. Related voter rows can repeat evidence from one household. Exact section text can be reused across parts or for a wide area, and support can include bad candidate links. The current baseline uses saved post-filter results while trial scores use historical pre-pruning candidate counts. Validate on new apartments, inspect families as well as rows, and rerun the full pipeline before relying on these numbers as expected production performance.

## Reproduce

Run from `final/` with Python and `openpyxl` installed:

```sh
python3 experiments/coverage/coverage.py
python3 experiments/section/section_thresholds.py
python3 experiments/agent_schemes/evaluate_sections.py
```

The scripts read local source and review workbooks in `agents/` and `output/`. CSV results are local and ignored by Git because some include voter names and identifiers. The experimental scripts and this summary do not contain those records.
