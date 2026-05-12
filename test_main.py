from pathlib import Path

import pytest

from main import (
    INLINE_MULT_RE,
    NUMBER_RE,
    RAW_NUMBER_RE,
    SUFFIX_MULT_RE,
    NumberMatch,
    column_multipliers,
    extract_inline_multiples,
    extract_numbers,
    extract_raw_numbers,
    extract_table_numbers,
    find_declarations,
    fmt_multiplier,
    fmt_number,
    get_context,
    is_code_context,
    is_year,
    multiplier_at,
    parse_number,
    scan_pdf,
)

PDF = Path("sample_pdfs/FY25_Air_Force_Working_Capital_Fund.pdf")
ARMY_PDF = Path("sample_pdfs/Army_Working_Capital_Fund.pdf")


class TestNumberRegex:
    def test_adjusted_number_matches_supported_formats(self):
        text = "500 1,234,567 1234567 30,704.1 .743"
        assert [m.group() for m in NUMBER_RE.finditer(text)] == [
            "500",
            "1,234,567",
            "1234567",
            "30,704.1",
            ".743",
        ]

    def test_adjusted_number_rejects_common_false_positives(self):
        text = "FY2025 F-15 85% Total 1,23 MILCON (3330000)"
        assert [m.group() for m in NUMBER_RE.finditer(text)] == []

    def test_raw_number_keeps_broader_standalone_tokens(self):
        text = "FY 2025 Growth 15% Amount 0.000 MILCON (3330000)"
        assert [m.group() for m in RAW_NUMBER_RE.finditer(text)] == [
            "2025",
            "15",
            "0.000",
            "3330000",
        ]

    def test_raw_number_still_rejects_identifier_digits(self):
        text = "FY2025 F-15 Total 1,23"
        assert [m.group() for m in RAW_NUMBER_RE.finditer(text)] == []

    def test_inline_multiplier_regex(self):
        match = INLINE_MULT_RE.search("USTRANSCOM's 9.6 billion budget")
        assert match is not None
        assert match.group(1) == "9.6"
        assert match.group(2).lower() == "billion"

    def test_suffix_multiplier_regex_requires_dollar_prefix(self):
        assert SUFFIX_MULT_RE.search("$30M") is not None
        assert SUFFIX_MULT_RE.search("F-15B") is None


class TestParseNumber:
    def test_integer(self):
        assert parse_number("12345") == 12345.0

    def test_comma_formatted(self):
        assert parse_number("1,234,567") == 1_234_567.0

    def test_decimal(self):
        assert parse_number("30,704.1") == 30704.1

    def test_leading_dot(self):
        assert parse_number(".743") == 0.743

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_number("abc")


class TestIsYear:
    def test_year_in_range(self):
        assert is_year(2025.0) is True

    def test_lower_bound(self):
        assert is_year(1900.0) is True

    def test_upper_bound(self):
        assert is_year(2099.0) is True

    def test_below_range(self):
        assert is_year(1899.0) is False

    def test_above_range(self):
        assert is_year(2100.0) is False

    def test_non_integer_float(self):
        assert is_year(2025.5) is False

    def test_large_number(self):
        assert is_year(6_000_000.0) is False


class TestIsCodeContext:
    def test_iso_identifier(self):
        assert is_code_context("certified to ISO ", len("certified to ISO ")) is True

    def test_regular_label(self):
        assert is_code_context("Total ", len("Total ")) is False


class TestGetContext:
    def test_returns_surrounding_text(self):
        text = "a" * 100 + "TARGET" + "b" * 100
        ctx = get_context(text, 100, 106)
        assert "TARGET" in ctx

    def test_clamps_at_start(self):
        text = "TARGET" + "b" * 100
        ctx = get_context(text, 0, 6)
        assert ctx.startswith("TARGET")

    def test_clamps_at_end(self):
        text = "a" * 100 + "TARGET"
        ctx = get_context(text, 100, 106)
        assert ctx.endswith("TARGET")

    def test_newlines_replaced_with_spaces(self):
        text = "line1\nTARGET\nline2"
        ctx = get_context(text, 6, 12)
        assert "\n" not in ctx


def _mults(text: str) -> list[int]:
    return [mult for _, mult in find_declarations(text)]


class TestFindDeclarations:
    # "in X" family
    def test_in_millions(self):
        assert 1_000_000 in _mults("Amounts in millions")

    def test_in_thousands(self):
        assert 1_000 in _mults("Figures stated in thousands")

    def test_in_billions(self):
        assert 1_000_000_000 in _mults("€ in billions")

    def test_legacy_dollars_in_millions(self):
        assert 1_000_000 in _mults("( Dollars in Millions) Budget Summary")

    def test_legacy_dollars_in_thousands(self):
        assert 1_000 in _mults("( Dollars in Thousands) Capital Investment")

    def test_in_thousands_with_except_clause(self):
        assert 1_000 in _mults("In thousands, except percentages")

    def test_all_values_in_millions(self):
        assert 1_000_000 in _mults("All values in millions except share data")

    # Currency-symbol prefix family
    def test_dollar_millions(self):
        assert 1_000_000 in _mults("($ millions)")

    def test_dollar_sign_no_space(self):
        assert 1_000_000 in _mults("($millions)")

    def test_dollar_sign_upper(self):
        assert 1_000_000 in _mults("($ IN MILLIONS)")

    def test_euro_billions(self):
        assert 1_000_000_000 in _mults("€ billions")

    # Currency-code prefix family
    def test_usd_millions(self):
        assert 1_000_000 in _mults("USD millions")

    def test_eur_thousands(self):
        assert 1_000 in _mults("EUR thousands")

    # Parenthetical family
    def test_paren_millions(self):
        assert 1_000_000 in _mults("(millions)")

    def test_paren_dollar_thousands(self):
        assert 1_000 in _mults("($ thousands)")

    # Multiple declarations — both returned
    def test_multiple_declarations(self):
        mults = _mults("in millions, footnotes in thousands")
        assert 1_000_000 in mults
        assert 1_000 in mults

    # Case insensitivity
    def test_case_insensitive_upper(self):
        assert 1_000_000 in _mults("IN MILLIONS")

    def test_case_insensitive_lower(self):
        assert 1_000_000 in _mults("in millions")

    # No match
    def test_no_multiplier(self):
        assert _mults("This page has no scale declaration.") == []

    def test_narrative_text(self):
        assert _mults("The Air Force Working Capital Fund supports depot maintenance.") == []

    # Must NOT match inline "$2.3 million" (digit between $ and scale word)
    def test_no_match_inline_dollar_amount(self):
        assert _mults("awarded a $2.3 million contract") == []

    def test_no_match_prose_millions(self):
        assert _mults("we invested millions in infrastructure") == []


class TestMultiplierAt:
    def test_no_declarations_returns_1(self):
        assert multiplier_at(100, []) == 1

    def test_declaration_before_pos(self):
        assert multiplier_at(100, [(0, 1_000_000)]) == 1_000_000

    def test_declaration_after_pos_returns_1(self):
        assert multiplier_at(0, [(50, 1_000_000)]) == 1

    def test_nearest_preceding_wins(self):
        assert multiplier_at(100, [(0, 1_000_000), (50, 1_000)]) == 1_000

    def test_earlier_declaration_when_no_later(self):
        assert multiplier_at(100, [(0, 1_000_000), (200, 1_000)]) == 1_000_000


class TestExtractNumbers:
    def test_basic_integer(self):
        matches = extract_numbers("Revenue 500", 1, [])
        assert any(m.value == 500.0 for m in matches)

    def test_comma_formatted(self):
        matches = extract_numbers("Total 1,234,567", 1, [])
        assert any(m.value == 1_234_567.0 for m in matches)

    def test_uncommaed_large_integer(self):
        matches = extract_numbers("Total 1234567", 1, [])
        assert any(m.value == 1_234_567.0 for m in matches)

    def test_uncommaed_large_decimal(self):
        matches = extract_numbers("Total 1234567.89", 1, [])
        assert any(m.value == pytest.approx(1_234_567.89) for m in matches)

    def test_rejects_malformed_comma_groups(self):
        matches = extract_numbers("Total 1,23", 1, [])
        assert matches == []

    def test_rejects_parenthesized_code_fragments(self):
        matches = extract_numbers("MILCON (3330000)", 1, [(0, 1_000_000)])
        assert matches == []

    def test_rejects_known_identifier_prefixes(self):
        matches = extract_numbers("certified to ISO 45001", 1, [(0, 1_000_000)])
        assert matches == []

    def test_skips_years(self):
        matches = extract_numbers("FY 2025 Budget", 1, [])
        assert all(m.value != 2025.0 for m in matches)

    def test_skips_zero(self):
        matches = extract_numbers("Amount 0.000", 1, [])
        assert all(m.value != 0.0 for m in matches)

    def test_applies_declaration_multiplier(self):
        # Declaration at position 0 covers numbers that follow it
        matches = extract_numbers("Total Revenue 30,704.1", 1, [(0, 1_000_000)])
        m = next(m for m in matches if m.value == 30704.1)
        assert m.multiplier == 1_000_000
        assert m.adjusted_value == pytest.approx(30_704_100_000.0)

    def test_suppresses_multiplier_for_workyears(self):
        text = "in millions Civilian Workyears 33,579"
        matches = extract_numbers(text, 1, find_declarations(text))
        m = next(m for m in matches if m.value == 33579.0)
        assert m.multiplier == 1

    def test_suppresses_multiplier_for_end_strength(self):
        text = "in millions Military End Strength 15,000"
        matches = extract_numbers(text, 1, find_declarations(text))
        m = next(m for m in matches if m.value == 15_000.0)
        assert m.multiplier == 1

    def test_no_suppression_when_no_declaration(self):
        matches = extract_numbers("Civilian Workyears 33,579", 1, [])
        m = next(m for m in matches if m.value == 33579.0)
        assert m.multiplier == 1

    def test_position_based_two_sections(self):
        # Numbers before the second declaration use the first; numbers after use the second
        text = "in millions\n100\nin thousands\n200"
        decls = find_declarations(text)
        matches = extract_numbers(text, 1, decls)
        m100 = next(m for m in matches if m.value == 100.0)
        m200 = next(m for m in matches if m.value == 200.0)
        assert m100.multiplier == 1_000_000
        assert m200.multiplier == 1_000

    def test_rejects_fy_code(self):
        matches = extract_numbers("FY2025 Budget", 1, [])
        assert all(m.value != 2025.0 for m in matches)

    def test_rejects_percentage(self):
        matches = extract_numbers("Growth rate 15% annually", 1, [])
        assert all(m.value != 15.0 for m in matches)

    def test_page_number_stored(self):
        matches = extract_numbers("Revenue 500", 7, [])
        assert all(m.page == 7 for m in matches)


class TestExtractRawNumbers:
    def test_keeps_years(self):
        matches = extract_raw_numbers("FY 2025 Budget", 1)
        assert any(m.value == 2025.0 for m in matches)

    def test_keeps_percentages(self):
        matches = extract_raw_numbers("Growth rate 15% annually", 1)
        assert any(m.value == 15.0 for m in matches)

    def test_keeps_zero(self):
        matches = extract_raw_numbers("Amount 0.000", 1)
        assert any(m.value == 0.0 for m in matches)

    def test_keeps_parenthesized_code_fragments_for_raw(self):
        matches = extract_raw_numbers("MILCON (3330000)", 1)
        assert any(m.value == 3_330_000.0 for m in matches)

    def test_rejects_malformed_comma_groups(self):
        matches = extract_raw_numbers("Total 1,23", 1)
        assert matches == []


class TestExtractInlineMultiples:
    def test_billion(self):
        matches = extract_inline_multiples("USTRANSCOM's 9.6 billion budget", 1)
        m = next(m for m in matches if m.value == pytest.approx(9.6))
        assert m.multiplier == 1_000_000_000
        assert m.adjusted_value == pytest.approx(9_600_000_000.0)

    def test_uncommaed_large_inline_value(self):
        matches = extract_inline_multiples("allocated 1234567 million", 1)
        m = next(m for m in matches if m.value == 1_234_567.0)
        assert m.multiplier == 1_000_000

    def test_million(self):
        matches = extract_inline_multiples("allocated 1,449 million for operations", 1)
        m = next(m for m in matches if m.value == 1449.0)
        assert m.multiplier == 1_000_000

    def test_thousand(self):
        matches = extract_inline_multiples("saving 500 thousand per year", 1)
        m = next(m for m in matches if m.value == 500.0)
        assert m.multiplier == 1_000

    def test_case_insensitive(self):
        matches = extract_inline_multiples("5 BILLION allocated", 1)
        assert any(m.value == 5.0 and m.multiplier == 1_000_000_000 for m in matches)

    def test_no_match_returns_empty(self):
        matches = extract_inline_multiples("Revenue 30,704.1", 1)
        assert matches == []


class TestColumnMultipliers:
    def test_page_level_fallback(self):
        table = [["Description", "FY2023", "FY2024"], ["Revenue", "100", "200"]]
        mults = column_multipliers(table, [(0, 1_000_000)])
        assert mults == [1_000_000, 1_000_000, 1_000_000]

    def test_column_header_overrides_page_default(self):
        # Column 1 header declares millions, page declares thousands
        table = [["Description", "in millions", "Headcount"], ["Revenue", "100", "50"]]
        mults = column_multipliers(table, [(0, 1_000)])
        assert mults[1] == 1_000_000  # column 1 header wins
        assert mults[2] == 1_000      # column 2 falls back to page

    def test_no_page_decls_defaults_to_1(self):
        table = [["A", "B"], ["1", "2"]]
        assert column_multipliers(table, []) == [1, 1]

    def test_empty_table(self):
        assert column_multipliers([], []) == []

    def test_uses_earliest_page_decl_as_default(self):
        # First declaration is treated as the page-level default.
        table = [["A", "B"], ["1", "2"]]
        mults = column_multipliers(table, [(0, 1_000_000), (500, 1_000)])
        assert mults == [1_000_000, 1_000_000]


class TestExtractTableNumbers:
    def test_applies_column_multiplier(self):
        table = [["Revenue", "30,704.1"]]
        results = extract_table_numbers(table, 1, [1, 1_000_000])
        m = next(m for m in results if m.value == 30704.1)
        assert m.multiplier == 1_000_000
        assert m.adjusted_value == pytest.approx(30_704_100_000.0)

    def test_non_financial_row_suppressed(self):
        table = [["Civilian Workyears", "33,579"]]
        results = extract_table_numbers(table, 1, [1, 1_000_000])
        m = next(m for m in results if m.value == 33579.0)
        assert m.multiplier == 1

    def test_end_strength_row_suppressed(self):
        table = [["Military End Strength", "15,000"]]
        results = extract_table_numbers(table, 1, [1, 1_000_000])
        m = next(m for m in results if m.value == 15_000.0)
        assert m.multiplier == 1

    def test_context_includes_row_label(self):
        table = [["Revenue", "30,704.1"]]
        results = extract_table_numbers(table, 1, [1, 1_000_000])
        m = next(m for m in results if m.value == 30704.1)
        assert "Revenue" in m.context

    def test_skips_zeros_and_years(self):
        table = [["FY", "2025", "0.000"]]
        results = extract_table_numbers(table, 1, [1, 1, 1])
        values = {m.value for m in results}
        assert 2025.0 not in values
        assert 0.0 not in values

    def test_none_cells_skipped(self):
        table = [[None, "100", None], ["Label", None, "200"]]
        results = extract_table_numbers(table, 1, [1, 1, 1])
        values = {m.value for m in results}
        assert 100.0 in values
        assert 200.0 in values

    def test_empty_row_skipped(self):
        table = [[], ["Revenue", "500"]]
        results = extract_table_numbers(table, 1, [1, 1_000_000])
        assert any(m.value == 500.0 for m in results)

    def test_page_number_stored(self):
        table = [["Revenue", "500"]]
        results = extract_table_numbers(table, 7, [1, 1])
        assert all(m.page == 7 for m in results)


class TestFmtNumber:
    def test_whole_float(self):
        assert fmt_number(6_000_000.0) == "6,000,000"

    def test_decimal(self):
        assert fmt_number(30_704.1) == "30,704.10"

    def test_large_whole(self):
        assert fmt_number(30_704_100_000.0) == "30,704,100,000"


class TestFmtMultiplier:
    def test_millions(self):
        assert fmt_multiplier(1_000_000) == "x1,000,000 (millions)"

    def test_thousands(self):
        assert fmt_multiplier(1_000) == "x1,000 (thousands)"

    def test_billions(self):
        assert fmt_multiplier(1_000_000_000) == "x1,000,000,000 (billions)"

    def test_no_scaling(self):
        assert fmt_multiplier(1) == "x1 (no scaling)"


@pytest.mark.skipif(not PDF.exists(), reason="PDF not present")
class TestScanPdf:
    def test_raw_result(self):
        best_raw, _ = scan_pdf(PDF)
        assert best_raw.value == pytest.approx(6_000_000.0)
        assert best_raw.page == 93

    def test_adjusted_result(self):
        _, best_adj = scan_pdf(PDF)
        assert best_adj.adjusted_value == pytest.approx(30_704_100_000.0)
        assert best_adj.multiplier == 1_000_000


@pytest.mark.skipif(not ARMY_PDF.exists(), reason="Army PDF not present")
class TestScanArmyPdf:
    def test_raw_result(self):
        best_raw, _ = scan_pdf(ARMY_PDF)
        assert best_raw.value == pytest.approx(14_327_331.0)
        assert best_raw.page == 5

    def test_adjusted_result(self):
        _, best_adj = scan_pdf(ARMY_PDF)
        assert best_adj.adjusted_value == pytest.approx(20_253_800_000.0)
        assert best_adj.multiplier == 1_000_000
