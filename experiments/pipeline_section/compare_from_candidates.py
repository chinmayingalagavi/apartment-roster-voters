# Test simple section-supported voter-to-flat selection from the saved preliminary candidate workbooks.
# Inputs are the four agent-reviewed candidate workbooks, their originals and existing AC workbooks.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
import csv
import re
import sys

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT.parent / "agents" / "research"
REVIEW = ROOT.parent / "agents" / "drafts"
DESTINATION = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))
import matching

APARTMENTS = {
    "concorde": ("concorde", "Concorde Midway"),
    "purnima": ("purnima", "Purnima Classic"),
    "silicon": ("silicon_oasis", "Silicon Oasis"),
    "tirumala": ("tirumala_vintage", "Tirumala Vintage"),
}
LABELS = ("Strong", "Medium", "Unlikely", "No Match")


def rows(path):
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = iter(book["voters_mapped_tohouse"].values)
    headers = next(sheet)
    output = [dict(zip(headers, row)) for row in sheet]
    book.close()
    return [row for row in output if row.get("voter_name")]


def unassigned_rows(path):
    book = load_workbook(path, read_only=True, data_only=True)
    sheet = iter(book["voters_unmapped"].values)
    headers = next(sheet)
    output = [dict(zip(headers, row)) for row in sheet]
    book.close()
    return [row for row in output if row.get("apartment_unit") and row.get("apartment_status") == "Unassigned"]


def identity(row):
    fields = ("serial_number", "apartment_unit", "apartment_status")
    return tuple(str(row[field] or "") for field in fields)


def review_identity(row):
    fields = ("epic_number", "serial_number", "apartment_unit", "apartment_status",
              "apartment_connection", "voter_link_type")
    return tuple(str(row[field] or "") for field in fields)


def whole_address_has_name(address, apartment):
    text = matching.normalize_address(address)
    name = matching.normalize_address(apartment)
    return bool(name and re.search(r"\b" + re.escape(name) + r"\b", text))


def exact_multiword_name_and_block_unit(row):
    """Test the direct-name plus explicit block/flat fallback without guessing a building."""
    if "voter_name_match" not in str(row["voter_link_type"] or ""):
        return False
    if float(row["name_match_pct"] or 0) != 100:
        return False
    if len(matching.full_word_tokens(matching.tokenize_name(row["voter_name"]))) < 2:
        return False
    unit = re.fullmatch(r"([A-Z]+)0*([0-9]+)", str(row["apartment_unit"]).upper())
    if not unit:
        return False
    block, number = unit.groups()
    pattern = r"\b" + re.escape(block) + r"\s+0*" + str(int(number)) + r"\b"
    return bool(re.search(pattern, matching.normalize_address(row["house_number"])))


def make_candidates():
    output = []
    for source_key, (output_key, apartment_name) in APARTMENTS.items():
        source = RESEARCH / f"{source_key}-first-pass" / f"{source_key}_before_scoring.xlsx"
        initial = rows(source)
        review_path = REVIEW / f"{source_key}_independent_full.xlsx"
        if not review_path.exists():
            review_path = RESEARCH / f"{source_key}-first-pass" / f"{source_key}_AI_review.xlsx"
        reviewed = rows(review_path)
        manual = {review_identity(row): row["strength"] for row in reviewed}
        source_keys = {review_identity(row) for row in initial}
        assert len(source_keys) == len(initial)
        assert len(manual) == len(reviewed) and set(manual).issubset(source_keys)
        assert len(initial) - len(reviewed) == (502 if source_key == "concorde" else 0)
        current = {identity(row) for row in rows(ROOT / "output/ac-no-grey" / f"{output_key}_voters.xlsx")}

        # Section support uses separate flats, never voter rows or human grades.
        section_flats = defaultdict(set)
        seed_flats = defaultdict(set)
        address_flats = defaultdict(set)
        for row in initial:
            flat = row["apartment_unit"]
            if not row["section_raw"] or not flat:
                continue
            section = (str(row["part"]), row["section_raw"])
            section_flats[section].add(flat)
            direct = "voter_name_match" in str(row["voter_link_type"] or "")
            full_words = matching.full_word_tokens(matching.tokenize_name(row["voter_name"]))
            if direct and len(full_words) >= 2 and float(row["name_match_pct"] or 0) >= 95:
                seed_flats[section].add(flat)
            if whole_address_has_name(row["house_number"], apartment_name):
                address_flats[section].add(flat)

        # Address-only voters can identify the building and flat, although they do not have a
        # roster-name link. Include them as possible section evidence, never as a direct anchor.
        for row in unassigned_rows(source):
            if row.get("section_raw") and whole_address_has_name(row["house_number"], apartment_name):
                section = (str(row["part"]), row["section_raw"])
                address_flats[section].add(row["apartment_unit"])

        for row in initial:
            section = (str(row["part"]), row["section_raw"])
            flat = row["apartment_unit"]
            label = manual.get(review_identity(row), "No Match")
            assert label in LABELS
            output.append({
                "apartment": source_key,
                "serial": row["serial_number"],
                "unit": flat,
                "status": row["apartment_status"],
                "voter_name": row["voter_name"],
                "house_number": row["house_number"],
                "part": row["part"],
                "section_raw": row["section_raw"],
                "link_type": row["voter_link_type"],
                "connection": row["apartment_connection"],
                "relation_name": row["relation_name"],
                "score": float(row["name_match_pct"] or 0),
                "manual": label,
                "current": identity(row) in current,
                "exact_apartment": whole_address_has_name(row["house_number"], apartment_name),
                "exact_multiword_block_unit": exact_multiword_name_and_block_unit(row),
                "section_other_flats": len(section_flats[section] - {flat}),
                "section_other_seed_flats": len(seed_flats[section] - {flat}),
                "section_other_named_flats": len(address_flats[section] - {flat}),
            })
    return output


def predicted(row, variant):
    if variant == "current":
        return row["current"]
    if row["exact_apartment"]:
        return True
    n = row["section_other_flats"]
    seed = row["section_other_seed_flats"]
    named = row["section_other_named_flats"]
    score = row["score"]
    if variant == "section2":
        return n >= 2
    if variant == "section3":
        return n >= 3
    if variant == "section5":
        return n >= 5
    if variant == "section2_score60":
        return n >= 2 and score > 60
    if variant == "section2_score70":
        return n >= 2 and score > 70
    if variant == "section2_score80":
        return n >= 2 and score > 80
    if variant == "seed1":
        return seed >= 1
    if variant == "seed2":
        return seed >= 2
    if variant == "seed3":
        return seed >= 3
    if variant == "seed2_score60":
        return seed >= 2 and score > 60
    if variant == "seed2_score70":
        return seed >= 2 and score > 70
    if variant == "named1":
        return named >= 1
    if variant == "named1_or_exact_multiword_block_unit":
        return named >= 1 or row["exact_multiword_block_unit"]
    if variant == "named2":
        return named >= 2
    if variant == "named1_score60":
        return named >= 1 and score > 60
    if variant == "named1_score50":
        return named >= 1 and score > 50
    raise ValueError(variant)


def main():
    candidates = make_candidates()
    variants = ("current", "section2", "section3", "section5", "section2_score60", "section2_score70",
                "section2_score80", "seed1", "seed2", "seed3", "seed2_score60", "seed2_score70",
                "named1", "named1_or_exact_multiword_block_unit", "named2", "named1_score50", "named1_score60")
    summaries = []
    changes = []
    for variant in variants:
        for apartment in (*APARTMENTS, "ALL"):
            subset = [row for row in candidates if apartment == "ALL" or row["apartment"] == apartment]
            counts = Counter((row["manual"], predicted(row, variant)) for row in subset)
            value = {
                "variant": variant,
                "apartment": apartment,
                "strong_retained": counts[("Strong", True)],
                "medium_retained": counts[("Medium", True)],
                "unlikely_retained": counts[("Unlikely", True)],
                "no_match_retained": counts[("No Match", True)],
                "positive_total": sum(counts[(label, selected)] for label in ("Strong", "Medium") for selected in (True, False)),
                "negative_total": sum(counts[(label, selected)] for label in ("Unlikely", "No Match") for selected in (True, False)),
            }
            summaries.append(value)
            print(value)
        if variant != "current":
            for row in candidates:
                proposed = predicted(row, variant)
                if row["current"] != proposed:
                    changes.append({**row, "variant": variant, "proposed": proposed})

    for name, records in (("summary.csv", summaries), ("changed_candidates.csv", changes)):
        with (DESTINATION / name).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)


if __name__ == "__main__":
    main()
