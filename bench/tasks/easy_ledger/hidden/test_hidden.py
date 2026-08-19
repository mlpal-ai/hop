from src.ledger import balances, statement, monthly_totals

L = [
    "2026-03-05,cash,-25.50",
    "# opening",
    "2026-01-01,cash,100.00",
    "2026-02-11,cash,7.25",
    "",
    "2026-01-15,cash,-10.00",
    "2026-02-01,bank,500.00",
]

def test_statement_sorted_by_date():
    assert statement(L, "cash") == [
        ("2026-01-01", 100.0), ("2026-01-15", 90.0),
        ("2026-02-11", 97.25), ("2026-03-05", 71.75),
    ]

def test_statement_empty_account():
    assert statement(L, "nope") == []

def test_monthly_totals_chronological():
    assert monthly_totals(L, "cash") == [
        ("2026-01", 90.0), ("2026-02", 7.25), ("2026-03", -25.5),
    ]

def test_balances_unchanged():
    assert balances(L) == {"cash": 71.75, "bank": 500.0}

def test_same_day_preserves_file_order_within_date():
    lines = ["2026-01-01,cash,10.00", "2026-01-01,cash,-3.00"]
    assert statement(lines, "cash") == [("2026-01-01", 10.0), ("2026-01-01", 7.0)]
