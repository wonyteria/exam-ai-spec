"""RESTORE-10B benchmark harness.

Same-fixture fair comparison of providers. Gold references are reachable
ONLY through eval.bench.gold — the reconstruction path must never read
them (enforced by a regression test).
"""
