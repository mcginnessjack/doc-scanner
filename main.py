"""
Extract the largest raw and context-adjusted numbers from a government budget PDF.

Usage:
    uv run main.py FY25_Air_Force_Working_Capital_Fund.pdf
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

# class structure to hold number matches, their context, and multipliers for adjusted values.
@dataclass
class NumberMatch:
    value: float
    page: int
    raw_text: str
    context: str
    multiplier: int = 1

    @property
    def adjusted_value(self) -> float:
        return self.value * self.multiplier


# Lookbehind/lookahead prevent matching inside codes like FY2025, F-15, malformed
# comma groups, or percentages like 85%.
NUMBER_TOKEN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
NUMBER_RE = re.compile(
    rf"(?<![A-Za-z\d/,\-\(])({NUMBER_TOKEN})(?![\d%,A-Za-z/\-])"
)
RAW_NUMBER_RE = re.compile(
    # Raw still means standalone numeric tokens, not digit runs inside identifiers like FY2025.
    rf"(?<![A-Za-z\d/,\-])({NUMBER_TOKEN})(?![\d,A-Za-z/\-])"
)

INLINE_MULT_RE = re.compile(
    rf"(?<![\w,])({NUMBER_TOKEN})\s*(trillion|billion|million|thousand)",
    re.IGNORECASE,
)

# Dollar-prefixed single-letter suffix: $9.6B, $30M, $450K, $1.2T
# Requires $ to avoid false positives on model numbers (F-15B, C-17A).
# As far as I can tell, the single-letter suffix convention is traditionally used in dollar amounts.
# In the future, could extend if other examples are found 
SUFFIX_MULT_RE = re.compile(
    rf"\$({NUMBER_TOKEN})\s*([KMBT])(?![A-Za-z\d])",
    re.IGNORECASE,
)

MULTIPLIER_MAP = {
    "trillion": 1_000_000_000_000,
    "billion": 1_000_000_000,
    "million": 1_000_000,
    "thousand": 1_000,
}

SUFFIX_MULT_MAP = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "t": 1_000_000_000_000}

MULTIPLIER_LABELS = {v: k + "s" for k, v in MULTIPLIER_MAP.items()}

# Detects scale unit declarations. Context indicators disambiguate unit modifiers
# ("in millions", "$ millions") from prose mentions ("cost millions", "$2.3 million deal").
# Currency prefix without a number: "$ millions" matches, "$2.3 million" does not.
_SCALE_RE = re.compile(
    r"""(?:
        \bin\s+                         # "in millions", "amounts in thousands"
        | [\$€£¥]\s*                    # "$ millions", "€ billions"
        | \b(?:USD|EUR|GBP|CAD|AUD)\s+ # "USD millions", "EUR thousands"
        | \(\s*[\$€£¥]?\s*             # "(millions)", "($ thousands)"
    )(trillions?|billions?|millions?|thousands?)""",
    re.IGNORECASE | re.VERBOSE,
)

# Row labels that indicate non-dollar units (headcount, labor hours, etc.).
# Prevents applying a "Dollars in Millions" page multiplier to headcount figures.
# ...
# This is not an exhaustive list, but for an initial solution worked for a specific document it sufficies.
# Looking for open source packages or dictionaries of common non-financial units to expand this in the future.
NON_FINANCIAL_KEYWORDS = re.compile(
    r"\b(end\s+strength|workyears?|manhours?|ftes?|headcount|users?|acres?|locations?|sites?)\b",
    re.IGNORECASE,
)

# Common document/catalog/standards prefixes whose following digits are identifiers,
# not quantities. This is intentionally narrow so ordinary labels like "Total 1234567"
# still count as numeric values.
# ...
# These prefixes are standard in US government documents, but may need to be expanded for other contexts. Looking for open source packages or dictionaries of common codes to expand this in the future.
CODE_PREFIX_RE = re.compile(r"\b(?:ISO|OMB|CAGE|NSN|FSC|NAICS|PSC)\s*$", re.IGNORECASE)


def find_declarations(text: str) -> list[tuple[int, int]]:
    """Return (position, multiplier) for each scale declaration in text, sorted by position."""
    # r strip plural 's' to unify "million" and "millions" declarations
    return [
        (m.start(), MULTIPLIER_MAP[m.group(1).lower().rstrip("s")])
        for m in _SCALE_RE.finditer(text)
    ]


def multiplier_at(pos: int, declarations: list[tuple[int, int]]) -> int:
    """Return the multiplier from the nearest declaration at or before pos, defaulting to 1."""
    best = 1
    for decl_pos, mult in declarations:
        if decl_pos <= pos:
            best = mult
        else:
            break  # sorted; no later entry can be closer
    return best


def parse_number(s: str) -> float:
    # remove commas before parsing to simplify math
    return float(s.replace(",", ""))

# Check for years to avoid false positives on date codes like "FY2025" or "est. 2024".
# This is a common suggestion from LLMs about this problem, but the directions dont explicitly say to exclude them.
# Keeping the exclusion for the initial implementation, but in reality would ask for clarity on whether to exclude them or not, and if so, whether to exclude other common numeric categories that aren't financial amounts (e.g. model numbers like "F-15", "C-17", etc.)
def is_year(val: float) -> bool:
    return val.is_integer() and 1900 <= val <= 2099


def _try_parse(raw: str) -> float | None:
    """Parse a regex-matched token; return None if invalid, zero, or a calendar year."""
    try:
        val = parse_number(raw)
    except ValueError:
        return None
    return None if (val == 0.0 or is_year(val)) else val


def is_code_context(text: str, start: int) -> bool:
    """Return True when a number is immediately preceded by a known government identifier prefix."""
    prefix = text[max(0, start - 20) : start]
    return bool(CODE_PREFIX_RE.search(prefix))

# Window defaults to 60 chars on either side
# In a longer implementation, would want to experiment with different window sizes and possibly
# other context extraction strategies.
def get_context(text: str, start: int, end: int, window: int = 60) -> str:
    return text[max(0, start - window) : min(len(text), end + window)].replace("\n", " ").strip()


def extract_raw_numbers(text: str, page_num: int) -> list[NumberMatch]:
    """Extract literal numeric values with minimal filtering for the raw-number answer."""
    results = []
    for match in RAW_NUMBER_RE.finditer(text):
        raw = match.group()
        try:
            val = parse_number(raw)
        except ValueError:
            continue

        ctx = get_context(text, match.start(), match.end())
        results.append(NumberMatch(value=val, page=page_num, raw_text=raw, context=ctx))

    return results


def extract_numbers(text: str, page_num: int, declarations: list[tuple[int, int]]) -> list[NumberMatch]:
    """Extract numbers from a page; each number inherits the nearest preceding scale declaration."""
    page_has_non_financial = bool(NON_FINANCIAL_KEYWORDS.search(text))
    results = []
    for match in NUMBER_RE.finditer(text):
        raw = match.group()
        val = _try_parse(raw)
        if val is None:
            continue
        if is_code_context(text, match.start()):
            continue

        effective_mult = multiplier_at(match.start(), declarations)
        ctx = get_context(text, match.start(), match.end())
        multiplier = (
            1 if (page_has_non_financial and effective_mult > 1 and NON_FINANCIAL_KEYWORDS.search(ctx))
            else effective_mult
        )
        results.append(NumberMatch(value=val, page=page_num, raw_text=raw, context=ctx, multiplier=multiplier))

    return results

# Also investigated using the quantulum3 package for this implementation, which is designed to extract quantities with units from text. 
# Opted against including it in the first pass, for the sake of simplicity.
# In future work would like to experiment more with this package or similar ones to leverage pre-existing open source tools
def extract_inline_multiples(text: str, page_num: int) -> list[NumberMatch]:
    """Extract prose patterns like '$9.6 billion' that carry their own unit declaration."""
    results = []
    for match in INLINE_MULT_RE.finditer(text):
        val = _try_parse(match.group(1))
        if val is None:
            continue

        unit = match.group(2).lower()
        ctx = get_context(text, match.start(), match.end())
        results.append(
            NumberMatch(
                value=val,
                page=page_num,
                raw_text=f"{match.group(1)} {unit}",
                context=ctx,
                multiplier=MULTIPLIER_MAP[unit],
            )
        )

    return results


def extract_suffix_multiples(text: str, page_num: int) -> list[NumberMatch]:
    """Extract dollar-prefixed single-letter suffix amounts: $9.6B, $30M, $450K, $1.2T."""
    results = []
    for match in SUFFIX_MULT_RE.finditer(text):
        val = _try_parse(match.group(1))
        if val is None:
            continue
        multiplier = SUFFIX_MULT_MAP[match.group(2).lower()]
        ctx = get_context(text, match.start(), match.end())
        results.append(NumberMatch(value=val, page=page_num, raw_text=match.group(), context=ctx, multiplier=multiplier))
    return results


_HEADER_ROW_LIMIT = 3  # footnotes below this depth can't overwrite header-derived multipliers


def column_multipliers(table: list[list[str | None]], page_decls: list[tuple[int, int]]) -> list[int]:
    """Return per-column scale multiplier inferred from column header cells.

    Falls back to the earliest page-level declaration (the page header, not footnotes) when
    a column header has no explicit scale. This covers the common case where budget tables
    declare scale in the page title ("Dollars in Millions") rather than in individual
    column headers ("$M").
    """
    if not table:
        return []
    num_cols = max((len(row) for row in table if row), default=0)
    default_mult = page_decls[0][1] if page_decls else 1
    mults = [default_mult] * num_cols

    # Header row limit is a heuristic to prevent footnotes from overwriting column multipliers
    # This was an interesting suggestion from LLMs, and in practice seemed logical.
    # In a real world setting would want to experiment with different limits and different table formats
    # to find out how usefull this is, and other strategies for working with tables in large PDF documents.
    for row in table[:_HEADER_ROW_LIMIT]:
        if not row:
            continue
        for col_idx, cell in enumerate(row):
            if cell and col_idx < num_cols and (decls := find_declarations(cell)):
                mults[col_idx] = decls[-1][1]

    return mults

# From reading through and jumping around the provided document, this one seemed like a highly important common pattern
# In practice, as mentioned above, I would love to experiment with different forms of table extraction over a large set of just test tables.
def extract_table_numbers(
    table: list[list[str | None]], page_num: int, col_mults: list[int]
) -> list[NumberMatch]:
    """Extract numbers from a structured table with per-column multiplier.

    Row label (first non-empty cell) identifies non-financial rows so that headcount
    columns beside dollar columns aren't incorrectly scaled.
    """
    results = []
    for row in table:
        if not row:
            continue
        row_label = next((c for c in row if c and c.strip()), "")
        is_non_financial = bool(NON_FINANCIAL_KEYWORDS.search(row_label))

        for col_idx, cell in enumerate(row):
            if not cell or col_idx >= len(col_mults):
                continue
            col_mult = 1 if is_non_financial else col_mults[col_idx]

            cell_stripped = cell.strip()
            for match in NUMBER_RE.finditer(cell):
                raw = match.group()
                val = _try_parse(raw)
                if val is None:
                    continue
                if is_code_context(cell, match.start()):
                    continue

                context = f"{row_label}: {cell_stripped}"[:120] if row_label else cell_stripped[:120]
                results.append(
                    NumberMatch(value=val, page=page_num, raw_text=raw, context=context, multiplier=col_mult)
                )

    return results


def scan_pdf(pdf_path: Path) -> tuple[NumberMatch, NumberMatch]:
    """Scan PDF for the largest raw and largest adjusted number.

    Two separate extraction passes:
    - Raw: flat text, no multiplier. Finds the greatest literal value in the document.
    - Adjusted: structured table extraction so each column inherits the scale declared
      in its header cell rather than a single page-level multiplier. Inline prose amounts
      (e.g. "$9.6 billion") are added from flat text as a supplement.
    """
    raw_matches: list[NumberMatch] = []
    adj_matches: list[NumberMatch] = []
    inherited_mult: int = 1  # carry forward scale across continuation pages

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if not text.strip():
                print(f"Warning: page {i + 1} has no text layer — may be scanned image", file=sys.stderr)
                continue
            page_num = i + 1
            # find a declaration like "all values on this page are in millions"
            page_decls = find_declarations(text)
            if page_decls:
                inherited_mult = page_decls[-1][1]
            # Continuation pages of a multi-page table may omit the scale header;
            # synthesize it at position 0 so all numbers inherit the last seen scale.
            effective_decls = page_decls or ([(0, inherited_mult)] if inherited_mult != 1 else [])

            raw_matches.extend(extract_raw_numbers(text, page_num))

            tables = page.extract_tables() or []
            for table in tables:
                col_mults = column_multipliers(table, page_decls)
                adj_matches.extend(extract_table_numbers(table, page_num, col_mults))
            adj_matches.extend(extract_inline_multiples(text, page_num))
            adj_matches.extend(extract_suffix_multiples(text, page_num))
            # Use inherited scale only on pages with no parseable tables; on table pages
            # page_decls prevents false positives from non-financial narrative numbers.
            text_decls = page_decls if tables else effective_decls
            adj_matches.extend(extract_numbers(text, page_num, text_decls))

    if not raw_matches:
        raise ValueError("No numbers found in PDF.")
    if not adj_matches:
        raise ValueError("No adjusted number candidates found in PDF.")

    best_raw = max(raw_matches, key=lambda m: m.value)
    best_adjusted = max(adj_matches, key=lambda m: m.adjusted_value)
    return best_raw, best_adjusted


def fmt_number(val: float) -> str:
    if val.is_integer():
        return f"{int(val):,}"
    return f"{val:,.2f}"


def fmt_multiplier(mult: int) -> str:
    label = MULTIPLIER_LABELS.get(mult)
    if label:
        return f"x{mult:,} ({label})"
    return "x1 (no scaling)" if mult == 1 else f"x{mult:,} (unknown scale)"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run main.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Expected a PDF file, got: {pdf_path.suffix or '(no extension)'}")
        sys.exit(1)
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"Scanning {pdf_path.name} ...")
    best_raw, best_adj = scan_pdf(pdf_path)

    print()
    print(f"Largest raw number:      {fmt_number(best_raw.value)}")
    print(f"  Context: page {best_raw.page}: ...{best_raw.context}...")
    print()
    print(f"Largest adjusted number: {fmt_number(best_adj.adjusted_value)}")
    print(f"  Context: page {best_adj.page} ({fmt_multiplier(best_adj.multiplier)}): ...{best_adj.context}...")


if __name__ == "__main__":
    main()
