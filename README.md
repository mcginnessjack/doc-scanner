# doc-scanner

Extracts the largest raw and context-adjusted numbers from a PDF.

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

## Example output

```
Scanning FY25_Air_Force_Working_Capital_Fund.pdf ...

Largest raw number:      6,000,000
  Page: 93

Largest adjusted number: 30,704,100,000
  Page: 13
  Multiplier: x1,000,000 (millions)
  Context: ...Total Revenue Total Revenue 28,239.2 29,176.6 30,704.1
Cost of Goods Sold Cost of Goods Sold 27,950.4 29,494.7 30,083.2
```

## How it works

1. **PDF extraction**: Uses [pdfplumber](https://github.com/jsvine/pdfplumber) to extract text page by page.
2. **Number parsing**: Regex matches comma-formatted values, uncommaed long integers, and decimals. The raw pass keeps literal numeric values broadly, while the adjusted pass filters years, zero-fill values, percentages, and obvious code fragments before applying scale multipliers.
3. **Multiplier detection**: Scans for scale declarations like `(Dollars in Millions)`, `in thousands`, or `USD billions`.
4. **Table-aware scaling**: Structured table extraction lets each column inherit the right scale from table/page headers.
5. **Context filtering**: Rows labeled with non-monetary units (e.g. Workyears, End Strength, users, acres) are not scaled as dollars.
6. **Inline prose**: A supplemental pass catches self-contained phrases like `$9.6 billion`, `500 thousand`, or `$30M`.

The code favors explainable heuristics over a black-box parser because the hardest part of this task is unit attribution: deciding when a visible number should inherit a nearby scale declaration, and when it is just a count, year, model number, or code.

## Developing Notes
Initially built based on a few example government budget PDFs. Research was done for potential packages to use, such as pdfplumber (used), PyMuPDF, quantulum3. A plan was made, fed into an LLM for initial scaffolding. Refined, tested, reviewed by human in the loop verification.
