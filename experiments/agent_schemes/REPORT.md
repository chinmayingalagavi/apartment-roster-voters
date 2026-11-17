# Section-count grading experiments

These are offline reclassifications of pre-scoring candidate rows, not full matcher reruns. A row represents a voter-to-flat candidate, and a voter can appear against more than one flat. The baseline joins the current AC workbook to those candidates by serial number, flat, and roster status. Current rows missing from the displayed first sheet are grouped with Weak in aggregate comparisons, including rows removed by earlier pruning or the final grey-row filter.

The benchmark contains 2,013 candidate rows across four apartments. Purnima, Silicon Oasis, and Tirumala use the full independent agent-reviewed workbooks in agents/drafts. For Concorde, 226 populated reviewed rows use full row keys and the other 502 initial candidates are inferred as No Match from the agent review report. Full keys are unique and all 226 reviewed keys appear in the initial source. Judgments use the same available records and are not independently verified ground truth. They are not a random or independent test sample. Section concentration was among the evidence reviewers could consider.

Section counts use the first resolved candidate set, before dominance, confidence, and the Strong-removes-Needs-review filters. They count distinct other flats with a candidate row in the exact same section_raw value. The same-part variant additionally requires the same voter-roll part. Missing sections get count zero. Counted candidates include those later judged No Match. Human labels are not used in the predictor, but misparsed and weak candidates can inflate the counts.

For name-based schemes, name_match_pct comes directly from the first-pass snapshot for every link type, including household links. Exact apartment names use normalized whole-phrase word boundaries and the originally configured primary name. The voter name determines whether a direct match has multiple full words. Predictions use no manual labels.

The script and confusion_counts.csv provide exact rules and confusion counts per apartment and grade. row_predictions.csv gives voter-flat candidate predictions and flags the candidates visible in the current first sheet.

## Exact apartment name or five other flats in the same part and section

- Strong if the exact apartment name occurs in the address OR at least 5 other candidate flats have a row in the same part and section_raw.
- Otherwise Medium if at least 2 other candidate flats have a row in the same part and section.
- Otherwise Weak. This is a grade, not an instructed deletion, and does not include people the matcher never proposed as candidates.

| Agent grade | Strong | Medium | Weak |
|---|---:|---:|---:|
| Strong (650) | 632 | 12 | 6 |
| Medium (77) | 66 | 4 | 7 |
| Unlikely (68) | 5 | 4 | 59 |
| No Match (1,218) | 6 | 78 | 1,134 |

Using agent Strong and Medium judgments together as supported, 714/727 are graded Strong or Medium. There are 93 Unlikely or No Match candidates graded Strong or Medium. Strong agrees with the agent in 698/709 cases and Medium in 16/98 cases. Medium therefore acts as a broad review queue in this sample, rather than a high-precision prediction.

| Apartment | Agent Strong or Medium given Strong or Medium | Agent Unlikely or No Match given Strong or Medium |
|---|---:|---:|
| Concorde | 198/199 | 69/529 |
| Purnima | 4/7 | 1/148 |
| Silicon Oasis | 469/478 | 5/164 |
| Tirumala | 43/43 | 18/445 |

Among 1,016 candidate rows that appear in the current first sheet, 695 were graded Strong or Medium by agents. This proposal grades 685 of them Strong or Medium, compared with 690 under current grades. Of 321 agent Unlikely or No Match rows in the same visible group, this proposal grades 37 Strong or Medium, versus 84 under current grades.

The remaining 997 candidates are absent from the current first sheet. Agents supported 32, and the proposed offline grading assigns 29 Strong or Medium. Among 965 agent Unlikely or No Match candidates absent from the current sheet, 56 also receive Strong or Medium offline. Making any of the 29 visible requires revisiting the earlier pruning or final grey filter and an end-to-end run. Changing grades of already visible rows cannot recover them.

## Same section across all parts

The same 5/2 rule using identical section text across parts gives Strong/Medium/Weak counts of 640/8/2 for agent Strong, 67/6/4 for agent Medium, 6/34/28 for agent Unlikely, and 46/234/938 for agent No Match. The combined Strong/Medium group captures 721/727 supported rows, but also includes 320/1,286 Unlikely or No Match rows. It is less selective than restricting the section count to the same part on this sample.

Raising the cross-part Strong cutoff to 10 moves many poor matches from Strong to Medium while retaining the same overall Strong+Medium candidates. It does not fix Medium's low precision.

A hard name-score requirement reduces recall on this sample. The exact-name-or-section>=5-with-score>80 variant gives 544/650 agent Strong and 46/77 agent Medium in Strong or Medium, compared with 644/650 and 70/77 for the same-part section rule with no score requirement. Some supported rows use inherited household scores.

## Limitations

- The 13 supported rows graded Weak by the same-part section scheme include three of Purnima's seven manually supported rows. Users should review the Weak tier before treating it as a removal rule.
- Candidate flat counts can be inflated by weak or erroneous candidates. Using them during actual ranking may change the candidate set and which rows survive.
- Exact section_raw text can include typos and its scope can differ across parts. A section label alone does not establish residence.
- Agent review and evaluation inspect overlapping evidence. These comparisons measure agreement with these reviews, not error rates on a new apartment.
- First-pass and current stages may handle ambiguous status, paired matches, or household links differently. The baseline key compares voter serial, flat, and status, not every original roster connection.
