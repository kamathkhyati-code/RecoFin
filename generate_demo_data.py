import csv
from datetime import date, timedelta

COUNTERPARTIES = [
    "ACME", "GLOBEX", "INITECH", "WAYNE ENTERPRISES", "STARK INDUSTRIES",
    "HOOLI", "WONKA INC", "UMBRELLA", "PIED PIPER", "CYBERDYNE",
    "SOYLENT", "OSCORP", "DUFF BEER", "MASSIVE DYNAMIC", "GRINGOTTS",
]

START = date(2026, 3, 1)

book_rows = []
bank_rows = []


def amt(cents):
    return f"{cents / 100:.2f}"


for i in range(1, 61):
    cat = i % 5
    cp = COUNTERPARTIES[i % len(COUNTERPARTIES)]
    d = START + timedelta(days=i)
    base_cents = 50000 + i * 733
    ref = f"INV-{4000 + i}"
    book_id = f"B{i:03d}"
    bank_id = f"S{i:03d}"

    if cat == 2:  # EXACT
        currency = "USD"
        if i % 12 == 0:
            currency = "GBP"
        elif i % 12 == 6:
            currency = "EUR"
        book_rows.append([book_id, d.isoformat(), amt(base_cents), currency, cp, ref])
        bank_rows.append([bank_id, d.isoformat(), amt(base_cents), currency, cp, ref])

    elif cat == 0:  # TOLERANCE: 3 cents off, 1 day off, different reference text
        book_rows.append([book_id, d.isoformat(), amt(base_cents), "USD", cp, ref])
        bank_rows.append([
            bank_id, (d + timedelta(days=1)).isoformat(),
            amt(base_cents + 3), "USD", cp, f"PAY-{4000 + i}",
        ])

    elif cat == 1:  # FUZZY: same amount, 4 days apart, near-identical reference
        book_ref = f"INV-{4000 + i}"
        bank_ref = f"INV{4000 + i}"
        book_rows.append([book_id, d.isoformat(), amt(base_cents), "USD", cp, book_ref])
        bank_rows.append([
            bank_id, (d + timedelta(days=4)).isoformat(),
            amt(base_cents), "USD", cp, bank_ref,
        ])

    elif cat == 3:  # book-only, unmatched
        book_rows.append([book_id, d.isoformat(), amt(base_cents), "USD", cp, ref])

    else:  # cat == 4, bank-only, unmatched
        bank_rows.append([bank_id, d.isoformat(), amt(base_cents), "USD", cp, f"UNM-{4000 + i}"])

# deliberately bad rows, rejected at ingestion
book_rows.append(["B901", "2026-04-10", "not_a_number", "USD", "BADCO", "INV-9001"])
book_rows.append(["B902", "2026-04-11", "500.00", "ZZZ", "BADCO", "INV-9002"])

bank_rows.append(["S901", "2026-04-10", "not_a_number", "USD", "BADCO", "INV-9001"])
bank_rows.append(["S902", "2026-04-11", "500.00", "ZZZ", "BADCO", "INV-9002"])
bank_rows.append(["S903", "2026-04-12", "bad-amount", "USD", "BADCO", "INV-9003"])

with open("sample_data/demo_book.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["txn_id", "date", "amount", "currency", "counterparty", "reference"])
    w.writerows(book_rows)

with open("sample_data/demo_bank.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["transaction_id", "value_date", "amount", "ccy", "counterparty", "reference"])
    w.writerows(bank_rows)

print(f"book rows: {len(book_rows)}, bank rows: {len(bank_rows)}")
