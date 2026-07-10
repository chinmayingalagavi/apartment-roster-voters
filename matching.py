#!/usr/bin/env python3
"""Shared address, household, and name matching helpers."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd


HONORIFICS = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "miss",
    "shri",
    "smt",
    "late",
    "kumari",
}

WHOLE_NAME_RATIO_THRESHOLD = 0.92
WHOLE_NAME_CONTAINMENT_MIN_LENGTH = 10
SHORT_NAME_CONTAINMENT_MIN_LENGTH = 5
UNEXPLAINED_ADDRESS_MAX_LETTERS = 10

UNEXPLAINED_ADDRESS_FILLER_RE = re.compile(
    r"\b(?:H|HOUSE|FLAT|F|NO|NUMBER|NUM|DOOR|BLOCK|"
    r"ROAD|RD|MAIN|ROOM|FLOOR|FLR|TH|ST|ND|SOUTH|NORTH|EAST|WEST)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NameToken:
    text: str
    index: int
    is_initial: bool
    bundle_letters: tuple[str, ...]


@dataclass(frozen=True)
class NameMatch:
    matched: bool
    kind: str
    detail: str


def normalize_space(value: object) -> str:
    return " ".join(str(value).strip().split())


def normalize_address(value: object) -> str:
    text = str(value) if pd.notna(value) else ""
    text = text.replace("'", " ")
    text = text.replace(".", " ")
    text = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).upper()
    return normalize_space(text)


def unit_parts_for_address_filter(parsed_unit: object, number_only_flat: object) -> tuple[str | None, int | None]:
    block: str | None = None
    flat_number: int | None = None
    if pd.notna(parsed_unit) and parsed_unit:
        unit = str(parsed_unit).strip().upper()
        match = re.fullmatch(r"([A-Z]+)?(\d+)", unit)
        if match:
            block = match.group(1)
            flat_number = int(match.group(2))
    elif pd.notna(number_only_flat):
        flat_number = int(number_only_flat)
    return block, flat_number


def unexplained_address_text(
    address: object,
    parsed_unit: object = None,
    number_only_flat: object = None,
    target_label_re: re.Pattern[str] | None = None,
) -> str:
    text = normalize_address(address)
    if not text:
        return ""

    block, flat_number = unit_parts_for_address_filter(parsed_unit, number_only_flat)
    if target_label_re is not None:
        text = target_label_re.sub(" ", text)
    text = UNEXPLAINED_ADDRESS_FILLER_RE.sub(" ", text)
    tokens: list[str] = []
    for token in normalize_space(text).split():
        if block and token == block:
            continue
        if flat_number is not None and token.isdigit() and int(token) == flat_number:
            continue
        tokens.append(token)
    return normalize_space(" ".join(tokens))


def unexplained_address_letter_count(value: object) -> int:
    return len(re.sub(r"[^A-Z]+", "", normalize_address(value)))


def strip_honorifics(tokens: Iterable[str]) -> list[str]:
    return [token for token in tokens if token not in HONORIFICS]


def is_initial_bundle(raw_token: str) -> bool:
    if not raw_token.isalpha() or len(raw_token) < 2 or len(raw_token) > 6:
        return False
    if not raw_token.isupper():
        return False
    token = raw_token.lower()
    if len(token) == 2:
        return True
    vowels = sum(1 for ch in token if ch in "aeiou")
    return vowels == 0


def tokenize_name(value: object) -> list[NameToken]:
    raw = str(value) if pd.notna(value) else ""
    pieces_raw = re.sub(r"[^A-Za-z0-9]+", " ", raw).split()
    pieces = [(piece, piece.lower()) for piece in pieces_raw if piece.lower() not in HONORIFICS]
    tokens: list[NameToken] = []
    for index, (raw_piece, piece) in enumerate(pieces):
        if not piece:
            continue
        is_initial = len(piece) == 1 and piece.isalpha()
        bundle_letters = tuple(piece) if is_initial_bundle(raw_piece) else ()
        tokens.append(NameToken(piece, index, is_initial, bundle_letters))
    return tokens


def full_token_match(left: str, right: str) -> str | None:
    if len(left) <= 1 or len(right) <= 1:
        return None
    if left == right:
        return "exact"
    if min(len(left), len(right)) >= 5:
        ratio = difflib.SequenceMatcher(None, left, right).ratio()
        if ratio >= 0.88:
            return f"variant:{ratio:.2f}"
    return None


def short_name_containment_match(left: str, right: str) -> str | None:
    if len(left) <= 1 or len(right) <= 1 or left == right:
        return None
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= SHORT_NAME_CONTAINMENT_MIN_LENGTH and longer.startswith(shorter):
        return f"short_name_prefix:{shorter}->{longer}"
    return None


def explicit_initial_letters(token: NameToken) -> tuple[str, ...]:
    if token.is_initial:
        return (token.text,)
    return token.bundle_letters


def is_full_word_candidate(token: NameToken) -> bool:
    return len(token.text) > 1 and not token.bundle_letters


def is_mononym(tokens: list[NameToken]) -> bool:
    return len(tokens) == 1 and is_full_word_candidate(tokens[0])


def full_word_tokens(tokens: list[NameToken]) -> list[NameToken]:
    return [token for token in tokens if is_full_word_candidate(token)]


def has_single_full_word(tokens: list[NameToken]) -> bool:
    return len(full_word_tokens(tokens)) == 1


def single_side_short_name_containment_pair(
    left_tokens: list[NameToken],
    right_tokens: list[NameToken],
) -> tuple[int, int, str, str, str] | None:
    left_single = has_single_full_word(left_tokens)
    right_single = has_single_full_word(right_tokens)
    for lt in full_word_tokens(left_tokens):
        for rt in full_word_tokens(right_tokens):
            kind = short_name_containment_match(lt.text, rt.text)
            if not kind:
                continue
            if len(lt.text) < len(rt.text) and not left_single:
                continue
            if len(rt.text) < len(lt.text) and not right_single:
                continue
            return (lt.index, rt.index, lt.text, rt.text, kind)
    return None


def whole_name_words(value: object) -> list[str]:
    return [token.text for token in full_word_tokens(tokenize_name(value))]


def whole_name_normalized(value: object) -> str:
    return " ".join(whole_name_words(value))


def whole_name_compact(value: object) -> str:
    return "".join(whole_name_words(value))


def whole_name_rule_match(left: object, right: object) -> NameMatch:
    left_norm = whole_name_normalized(left)
    right_norm = whole_name_normalized(right)
    if not left_norm or not right_norm:
        return NameMatch(False, "empty", "")

    left_compact = whole_name_compact(left)
    right_compact = whole_name_compact(right)
    if min(len(left_compact), len(right_compact)) < 8:
        return NameMatch(False, "too_short", "")

    spaced_ratio = difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
    compact_ratio = difflib.SequenceMatcher(None, left_compact, right_compact).ratio()
    if max(spaced_ratio, compact_ratio) >= WHOLE_NAME_RATIO_THRESHOLD:
        return NameMatch(
            True,
            "whole_name_high_ratio",
            f"{left_norm}~{right_norm}; spaced={spaced_ratio:.2f}; compact={compact_ratio:.2f}",
        )

    shorter, longer = sorted((left_compact, right_compact), key=len)
    if len(shorter) >= WHOLE_NAME_CONTAINMENT_MIN_LENGTH and shorter in longer:
        return NameMatch(
            True,
            "whole_name_compact_contains",
            f"{left_norm}~{right_norm}; compact_contains={shorter}",
        )

    return NameMatch(False, "no_match", "")


def normalized_name_words(value: object) -> str:
    return " ".join(token.text for token in tokenize_name(value) if token.text)


def single_word_name_matches(left: object, right: object) -> list[tuple[str, str, str]]:
    left_tokens = tokenize_name(left)
    right_tokens = tokenize_name(right)
    matches: list[tuple[str, str, str]] = []
    for lt in left_tokens:
        if not is_full_word_candidate(lt):
            continue
        for rt in right_tokens:
            if not is_full_word_candidate(rt):
                continue
            kind = full_token_match(lt.text, rt.text)
            if kind:
                matches.append((lt.text, rt.text, kind))
    return matches


def compare_names(left: object, right: object) -> NameMatch:
    left_tokens = tokenize_name(left)
    right_tokens = tokenize_name(right)
    if not left_tokens or not right_tokens:
        return NameMatch(False, "empty", "")

    full_pairs: list[tuple[int, int, str, str, str]] = []
    for lt in left_tokens:
        for rt in right_tokens:
            kind = full_token_match(lt.text, rt.text)
            if kind:
                full_pairs.append((lt.index, rt.index, lt.text, rt.text, kind))

    unique_full_pairs = {(li, ri) for li, ri, *_ in full_pairs}
    if len(unique_full_pairs) >= 2:
        detail = "; ".join(f"{lt}~{rt}({kind})" for _, _, lt, rt, kind in full_pairs[:4])
        return NameMatch(True, "two_full_tokens", detail)

    if len(unique_full_pairs) == 1:
        full_li, full_ri = next(iter(unique_full_pairs))
        full_pair = next(pair for pair in full_pairs if pair[0] == full_li and pair[1] == full_ri)
        if (
            full_pair[4] == "exact"
            and (
                (is_mononym(left_tokens) and full_li == left_tokens[0].index)
                or (is_mononym(right_tokens) and full_ri == right_tokens[0].index)
            )
        ):
            return NameMatch(True, "mononym_exact", f"{full_pair[2]}~{full_pair[3]}(exact)")

        initial_details: list[str] = []
        for lt in left_tokens:
            for letter in explicit_initial_letters(lt):
                for rt in right_tokens:
                    if lt.index != full_li and rt.index != full_ri and is_full_word_candidate(rt) and rt.text[0] == letter:
                        initial_details.append(f"{letter}->{rt.text}")
        for rt in right_tokens:
            for letter in explicit_initial_letters(rt):
                for lt in left_tokens:
                    if rt.index != full_ri and lt.index != full_li and is_full_word_candidate(lt) and lt.text[0] == letter:
                        initial_details.append(f"{letter}->{lt.text}")
        for lt in left_tokens:
            for left_letter in explicit_initial_letters(lt):
                for rt in right_tokens:
                    if lt.index == full_li or rt.index == full_ri:
                        continue
                    if left_letter in explicit_initial_letters(rt):
                        initial_details.append(f"{left_letter}~{left_letter}")
        if initial_details:
            detail = "; ".join(f"{lt}~{rt}({kind})" for _, _, lt, rt, kind in full_pairs[:2])
            detail += "; initials " + "; ".join(sorted(set(initial_details))[:4])
            return NameMatch(True, "full_plus_explicit_initial", detail)

    whole_match = whole_name_rule_match(left, right)
    if whole_match.matched:
        return whole_match

    short_pair = single_side_short_name_containment_pair(left_tokens, right_tokens)
    if short_pair:
        return NameMatch(
            True,
            "single_side_short_name_containment",
            f"{short_pair[2]}~{short_pair[3]}({short_pair[4]})",
        )

    return NameMatch(False, "no_match", "")


STRICT_RELATION_TO_ROSTER_MATCH_KINDS = {
    "two_full_tokens",
    "mononym_exact",
    "full_plus_explicit_initial",
}


def match_allowed_for_source(source_kind: str, match: NameMatch) -> bool:
    if not match.matched:
        return False
    if source_kind == "relation_name":
        return match.kind in STRICT_RELATION_TO_ROSTER_MATCH_KINDS
    return True


def leading_initial_letters(tokens: list[NameToken]) -> tuple[str, ...]:
    letters: list[str] = []
    for token in tokens:
        if is_full_word_candidate(token):
            break
        letters.extend(explicit_initial_letters(token))
    return tuple(letters)


def first_identity_anchor_matches(left: object, right: object) -> bool:
    left_tokens = tokenize_name(left)
    right_tokens = tokenize_name(right)
    left_words = full_word_tokens(left_tokens)
    right_words = full_word_tokens(right_tokens)
    if not left_words or not right_words:
        return False

    if full_token_match(left_words[0].text, right_words[0].text):
        return True
    if single_side_short_name_containment_pair(left_tokens, right_tokens):
        return True

    left_initials = leading_initial_letters(left_tokens)
    right_initials = leading_initial_letters(right_tokens)
    if left_initials and right_words[0].text[0] in left_initials:
        return True
    if right_initials and left_words[0].text[0] in right_initials:
        return True
    return whole_name_rule_match(left, right).matched


def name_word_set(value: object) -> set[str]:
    return {token.text for token in full_word_tokens(tokenize_name(value))}


def proper_anchor_hit(
    voter: pd.Series,
    source_kind: str,
    source_name: object,
    person: dict[str, object],
    match: NameMatch,
) -> dict[str, object]:
    return {
        "voter_row_id": int(voter["_row_id"]),
        "serial_number": int(voter["serial_number"]),
        "source_kind": source_kind,
        "source_name": source_name,
        "source_name_norm": normalized_name_words(source_name),
        "source_words": name_word_set(source_name),
        "roster_row_id": int(person["roster_row_id"]),
        "roster_name": person["name"],
        "roster_name_norm": person["name_norm"],
        "roster_words": name_word_set(person["name"]),
        "match_kind": match.kind,
        "match_detail": match.detail,
    }


def proper_anchor_hits_for_rows(rows: pd.DataFrame, roster: list[dict[str, object]]) -> list[dict[str, object]]:
    anchors: list[dict[str, object]] = []
    for _, voter in rows.iterrows():
        for person in roster:
            for source_kind, source_name in (
                ("voter_name", voter["name"]),
                ("relation_name", voter["relation_name"]),
            ):
                match = compare_names(source_name, person["name"])
                if (
                    match_allowed_for_source(source_kind, match)
                    and first_identity_anchor_matches(source_name, person["name"])
                ):
                    anchors.append(proper_anchor_hit(voter, source_kind, source_name, person, match))
    return anchors


def contextual_anchor_word_hit(
    voter: pd.Series,
    source_kind: str,
    source_name: object,
    person: dict[str, object],
    anchors: list[dict[str, object]],
) -> dict[str, object] | None:
    source_norm = normalized_name_words(source_name)
    if not source_norm:
        return None
    if any(
        anchor["source_kind"] == source_kind and anchor["source_name_norm"] == source_norm
        for anchor in anchors
    ):
        return None

    for source_word, roster_word, match_kind in single_word_name_matches(source_name, person["name"]):
        for anchor in anchors:
            if source_norm == anchor["source_name_norm"]:
                continue
            if person["name_norm"] == anchor["roster_name_norm"]:
                continue
            anchor_words = set(anchor["source_words"]) | set(anchor["roster_words"])
            if source_word in anchor_words or roster_word in anchor_words:
                continue
            return {
                "voter_row_id": int(voter["_row_id"]),
                "serial_number": int(voter["serial_number"]),
                "source_kind": source_kind,
                "source_name": source_name,
                "source_name_norm": source_norm,
                "source_word": source_word,
                "roster_row_id": int(person["roster_row_id"]),
                "roster_name": person["name"],
                "roster_name_norm": person["name_norm"],
                "roster_word": roster_word,
                "match_kind": "anchor_contextual_one_word",
                "match_detail": f"{source_word}~{roster_word}({match_kind})",
                "anchor_source_name": anchor["source_name"],
                "anchor_roster_name": anchor["roster_name"],
                "anchor_match_kind": anchor["match_kind"],
            }
    return None


def voter_person_match_hits(
    voter: pd.Series,
    roster: list[dict[str, object]],
    anchors: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    person_hits: list[dict[str, object]] = []
    relation_hits: list[dict[str, object]] = []

    for person in roster:
        strict_match = compare_names(voter["name"], person["name"])
        if strict_match.matched and first_identity_anchor_matches(voter["name"], person["name"]):
            person_hits.append(
                {
                    "voter_row_id": int(voter["_row_id"]),
                    "serial_number": int(voter["serial_number"]),
                    "voter_name": voter["name"],
                    "roster_row_id": int(person["roster_row_id"]),
                    "roster_name": person["name"],
                    "roster_name_norm": person["name_norm"],
                    "match_source": "voter_name",
                    "match_kind": strict_match.kind,
                    "match_detail": strict_match.detail,
                }
            )
        else:
            contextual_hit = contextual_anchor_word_hit(voter, "voter_name", voter["name"], person, anchors)
            if contextual_hit:
                person_hits.append(
                    {
                        "voter_row_id": int(voter["_row_id"]),
                        "serial_number": int(voter["serial_number"]),
                        "voter_name": voter["name"],
                        "roster_row_id": int(person["roster_row_id"]),
                        "roster_name": person["name"],
                        "roster_name_norm": person["name_norm"],
                        "match_source": "voter_name",
                        "match_kind": contextual_hit["match_kind"],
                        "match_detail": (
                            f"{contextual_hit['match_detail']}; "
                            f"anchor {contextual_hit['anchor_source_name']} -> "
                            f"{contextual_hit['anchor_roster_name']}"
                        ),
                    }
                )

        relation_match = compare_names(voter["relation_name"], person["name"])
        if (
            match_allowed_for_source("relation_name", relation_match)
            and first_identity_anchor_matches(voter["relation_name"], person["name"])
        ):
            relation_hits.append(
                {
                    "voter_row_id": int(voter["_row_id"]),
                    "serial_number": int(voter["serial_number"]),
                    "relation_type": voter["relation_type"],
                    "relation_name": voter["relation_name"],
                    "roster_row_id": int(person["roster_row_id"]),
                    "roster_name": person["name"],
                    "roster_name_norm": person["name_norm"],
                    "match_source": "relation_name",
                    "match_kind": relation_match.kind,
                    "match_detail": relation_match.detail,
                }
            )

    return (
        dedupe_hits(
            person_hits,
            ("voter_row_id", "roster_name_norm", "match_source", "match_kind", "match_detail"),
        ),
        dedupe_hits(
            relation_hits,
            ("voter_row_id", "roster_name_norm", "match_source", "match_kind", "match_detail"),
        ),
    )


def make_household_key(row: pd.Series) -> str | None:
    if pd.notna(row["parsed_unit"]) and row["parsed_unit"]:
        return f"UNIT:{row['parsed_unit']}"
    if pd.notna(row["number_only_flat"]):
        return f"NUM:{int(row['number_only_flat']):03d}"
    if row["has_target_label"]:
        return f"LABEL_NO_UNIT:{row['address_norm']}"
    return None


def assign_households(voters: pd.DataFrame) -> pd.DataFrame:
    voters = voters.copy()
    voters["household_base_key"] = voters.apply(make_household_key, axis=1)
    voters = voters.sort_values(["part", "section_raw", "serial_number", "_row_id"]).reset_index(drop=True)

    household_ids: list[str | None] = []
    current_id: str | None = None
    last_part: object | None = None
    last_section: object | None = None
    last_key: str | None = None
    last_serial: int | None = None
    group_counter = 0

    for _, row in voters.iterrows():
        key = row["household_base_key"]
        serial = int(row["serial_number"])
        same_run = (
            key is not None
            and key == last_key
            and row["part"] == last_part
            and row["section_raw"] == last_section
            and last_serial is not None
            and serial - last_serial <= 5
        )
        if key is None:
            household_ids.append(None)
            current_id = None
        elif same_run and current_id:
            household_ids.append(current_id)
        else:
            group_counter += 1
            current_id = f"H{group_counter:05d}"
            household_ids.append(current_id)

        last_part = row["part"]
        last_section = row["section_raw"]
        last_key = key
        last_serial = serial

    voters["household_id"] = household_ids
    return voters.sort_values("_row_id").reset_index(drop=True)


def voter_candidate_units(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    if pd.isna(value):
        return []
    text = str(value)
    if not text:
        return []
    return [item for item in text.split(";") if item]


def dedupe_hits(hits: list[dict[str, object]], keys: tuple[str, ...]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    out: list[dict[str, object]] = []
    for hit in hits:
        key = tuple(hit.get(item, "") for item in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def evaluate_voter_rows_against_unit(
    rows: pd.DataFrame,
    unit_roster: list[dict[str, object]],
) -> dict[str, object]:
    anchors = proper_anchor_hits_for_rows(rows, unit_roster)
    row_details: list[dict[str, object]] = []
    person_hits_all: list[dict[str, object]] = []
    relation_hits_all: list[dict[str, object]] = []

    for _, voter in rows.iterrows():
        person_hits, relation_hits = voter_person_match_hits(voter, unit_roster, anchors)
        if not person_hits and not relation_hits:
            continue
        row_details.append(
            {
                "voter": voter,
                "person_hits": person_hits,
                "relation_hits": relation_hits,
            }
        )
        person_hits_all.extend(person_hits)
        relation_hits_all.extend(relation_hits)

    return {
        "row_details": row_details,
        "person_hits": person_hits_all,
        "relation_hits": relation_hits_all,
    }
