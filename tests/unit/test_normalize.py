"""Normalisation of matching keys and values (specification sections 30, 57, 58)."""

from __future__ import annotations

import math

import pytest

from app.utils.normalize import (
    is_null_like,
    make_lookup_key,
    normalize_key,
    normalize_number,
    normalize_text,
)


class TestKeyNormalisation:
    @pytest.mark.parametrize(
        "value",
        ["ABC123", " ABC123 ", "abc123", "\tABC123\n", "  abc123  "],
    )
    def test_variants_of_the_same_part_collapse(self, value):
        assert normalize_key(value) == "ABC123"

    def test_internal_whitespace_is_collapsed(self):
        assert normalize_key("ABC  123") == "ABC 123"

    def test_lookup_key_normalises_every_part(self):
        assert make_lookup_key(" pn001 ", "sn001", "eo-1001") == (
            "PN001",
            "SN001",
            "EO-1001",
        )

    def test_padded_and_clean_values_match(self):
        assert make_lookup_key("ABC123", "SN1", "EO1") == make_lookup_key(
            " ABC123 ", " sn1", "eo1 "
        )

    @pytest.mark.parametrize("value", [None, "", "  ", "N/A", "n/a", "-", "NULL", "nan"])
    def test_missing_markers_become_none(self, value):
        assert normalize_key(value) is None

    def test_text_normalisation_keeps_case(self):
        assert normalize_text("  Some Text  ") == "Some Text"


class TestNullDetection:
    @pytest.mark.parametrize("value", [None, float("nan"), "", "N/A", "-", "none"])
    def test_null_like(self, value):
        assert is_null_like(value)

    @pytest.mark.parametrize("value", [0, 0.0, "0", "ABC", False])
    def test_not_null_like(self, value):
        assert not is_null_like(value)

    def test_zero_is_not_missing(self):
        """0 and NULL are different business states (section 15)."""

        assert normalize_number("0") == 0
        assert normalize_number("") is None


class TestNumberNormalisation:
    def test_whole_numbers_stay_integers(self):
        value = normalize_number("12000")
        assert value == 12000
        assert isinstance(value, int)

    def test_fractional_values_keep_precision(self):
        value = normalize_number("9000.5")
        assert value == 9000.5
        assert isinstance(value, float)

    def test_thousands_separators_are_understood(self):
        assert normalize_number("12,450") == 12450
        assert normalize_number("12 450") == 12450

    def test_invalid_text_raises(self):
        with pytest.raises(ValueError):
            normalize_number("twelve")

    def test_booleans_are_rejected(self):
        with pytest.raises(ValueError):
            normalize_number(True)

    def test_infinity_and_nan_are_missing(self):
        assert normalize_number(float("inf")) is None
        assert normalize_number(math.nan) is None

    def test_prefer_int_can_be_disabled(self):
        value = normalize_number("12000", prefer_int=False)
        assert isinstance(value, float)
