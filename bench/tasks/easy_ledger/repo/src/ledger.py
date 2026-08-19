"""Tiny double-entry ledger: parse transaction lines, compute per-account balances
and a running statement. Line format: DATE,ACCOUNT,AMOUNT (amount +credit/-debit)."""
from collections import OrderedDict


def parse_line(line: str):
    date, account, amount = [p.strip() for p in line.split(",")]
    return date, account, float(amount)


def balances(lines):
    out = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        _, account, amount = parse_line(line)
        out[account] = round(out.get(account, 0.0) + amount, 2)
    return out


def statement(lines, account):
    """Chronological running balance for one account: list of (date, balance-after).
    Lines are not guaranteed to be sorted by date (ISO YYYY-MM-DD)."""
    rows = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        date, acct, amount = parse_line(line)
        if acct == account:
            rows.append((date, amount))
    running = 0.0
    out = []
    for date, amount in rows:  # BUG: not sorted by date before accumulating
        running = round(running + amount, 2)
        out.append((date, running))
    return out


def monthly_totals(lines, account):
    """Sum per YYYY-MM for one account, months in chronological order."""
    months = OrderedDict()
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        date, acct, amount = parse_line(line)
        if acct != account:
            continue
        key = date[:7]
        months[key] = round(months.get(key, 0.0) + amount, 2)
    return list(months.items())  # BUG: insertion order, not chronological
