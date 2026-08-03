# A20: Demo Segment A -- Captured Data Metrics

Captured from a live run of `scripts_demo_segment_a.py` against `sample_data/book.csv` and `sample_data/bank_source.csv`.

```
=== A20 Demo Segment A: Data Side ===

Book transactions ingested:   4
Bank transactions ingested:   3
Issues (bad rows rejected):   2

-- Ingestion metrics per source --
  book   type=csv  rows_in= 4 rows_out= 4 issues_out=0 retries=1 duration_ms=0.29 status=ok
  bank   type=csv  rows_in= 5 rows_out= 3 issues_out=2 retries=1 duration_ms=0.23 status=ok

Matched:                      3
Unmatched:                    1
Match rate:                   75%
Close ready:                  False

Issues detail:
  [error] bank: Row 4 rejected: [<class 'decimal.ConversionSyntax'>]
  [error] bank: Row 5 rejected: 1 validation error for Transaction
currency
  Input should be 'USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD', 'AUD' or 'INR' [type=enum, input_value='ZZZ', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/enum
```
