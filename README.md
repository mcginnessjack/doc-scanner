# doc-scanner

Extracts the largest raw and context-adjusted numbers from a government budget PDF.

**Raw number**: the greatest numeric value as written in the document, regardless of unit.

**Adjusted number**: the greatest value after applying natural language scale context (e.g., a table labeled "Dollars in Millions" means 30,704.1 represents 30,704,100,000).

## Requirements

[uv](https://docs.astral.sh/uv/) — Python package manager.

## Run tests

```bash
uv run --group dev pytest
```

## Run

```bash
uv run main.py sample_pdfs/FY25_Air_Force_Working_Capital_Fund.pdf
```

Expected runtime: under 15 seconds for a 114-page, 12MB PDF.

## Example output

```
Scanning FY25_Air_Force_Working_Capital_Fund.pdf ...

Largest raw number:      6,000,000
  Context: page 93: ...rojects are smaller in scale (costing between $250,000 and $6,000,000) and are designed...

Largest adjusted number: 30,704,100,000
  Context: page 13 (x1,000,000 (millions)): ...Total Revenue Total Revenue 28,239.2 29,176.6 30,704.1 Cost of Goods Sold...
```

## How it works

1. **PDF extraction**: Uses `pdfplumber` to extract text page by page.
2. **Number parsing**: Regex matches comma-formatted values, uncommaed long integers, and decimals. The raw pass keeps literal numeric values broadly, while the adjusted pass filters years, zero-fill values, percentages, and obvious code fragments before applying scale multipliers.
3. **Multiplier detection**: Scans for scale declarations like `(Dollars in Millions)`, `in thousands`, or `USD billions`.
4. **Table-aware scaling**: Structured table extraction lets each column inherit the right scale from table/page headers.
5. **Context filtering**: Rows labeled with non-monetary units (e.g. Workyears, End Strength, users, acres) are not scaled as dollars.
6. **Inline prose**: A supplemental pass catches self-contained phrases like `$9.6 billion`, `500 thousand`, or `$30M`.

The code favors explainable heuristics over a black-box parser because the hardest part of this task is unit attribution: deciding when a visible number should inherit a nearby scale declaration, and when it is just a count, year, model number, or code.
