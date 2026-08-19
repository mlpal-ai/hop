from src.ledger import balances

def test_balances_basic():
    lines = ["2026-01-01,cash,100.00", "2026-01-02,cash,-40.00", "2026-01-02,bank,10.00"]
    assert balances(lines) == {"cash": 60.0, "bank": 10.0}
