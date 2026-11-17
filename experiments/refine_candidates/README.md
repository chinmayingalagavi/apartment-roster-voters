# Recovering candidates at named apartments and complete flats

The normal candidate generator can omit a voter whose name is reversed or has extra words, even when the voter address gives the apartment name and a uniquely parsed flat. This experiment tests a single rule for all apartments.

1. Require the voter address to name the apartment explicitly and the current parser to identify a unique roster flat.
2. Compare the voter's own name with roster names for that flat. Accept identical normalized name words in any order, or, in the containment variant, require that all full words on one side occur on the other side, with at least two distinct full words on both sides.
3. Reject a proposed roster name if the voter's relation name also meets that name comparison. Require a unique roster match for the voter and a unique eligible voter for that roster entry. Leave alone voters already mapped in the preliminary output and roster entries already matched by own name.
4. Pass the resulting own-name candidate evidence through the existing resolver, together with the section-two experiment's candidate selection. This can restore a relation link only if the named voter is actually mapped to the same flat.

| Apartment | Exact reordered names: new mapped links | Full-word containment: new mapped links | Mapped links lost |
| --- | ---: | ---: | ---: |
| Concorde | 0 | 0 | 0 |
| Purnima | 0 | 0 | 0 |
| Silicon Oasis | 1 | 4 | 0 |
| Tirumala | 0 | 0 | 0 |

The four containment additions were outside the original reviewer benchmark. Three are own-name links with explicit matching apartment and flat addresses. The first has both name words in reverse order and corroborating reciprocal spouse names. The second uses two matching full words plus an initial that agrees with a full middle name, and the third has two matching full words with additional names on one side. The fourth is a dependent who names the second voter as their relation and lists the same complete apartment address. Record inspection supports these four assignments, but independent confirmation is unavailable.

The initial screen found a counterexample to reordering alone: the reordered own name agreed with the roster name, but that roster name was also explicitly entered as the voter's relation name. The guard excludes that proposal. Another plausible own-name match lacked a flat number in the voter address and is also excluded.

The separate raw-roll family screen found three reviewer-supported Silicon links lost by section-two selection and already present in the current workbook. They have a complete matching flat and an exact multiword relation name identifying a selected own-name voter in a different polling part. This screen did not rerun the resolver for the family exception. It discarded apparent gains that simply assigned an already mapped voter to the same flat with the anchor's different roster status.

From `final/`, create local captures with `python3 experiments/refine_scores/capture.py` and run `python3 experiments/refine_candidates/resolve_expansion.py`. The optional `screen.py` uses the source roll and the existing complete section-two workbooks. Its output and the resolver differences include row-level information and are ignored by Git.
