# microsched
Threaded priority job scheduler. Guarantees G1-G4 are documented in src/scheduler.py.
`python -m pytest` runs the (single-threaded) sanity tests; the concurrency guarantees
are what production users depend on.
