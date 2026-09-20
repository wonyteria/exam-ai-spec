"""MathDNA — deterministic math checking (RESTORE-13).

The checker is rule-based (SymPy), never a learned model: it parses
expressions, proves or refutes symbolic equivalence, and reports
UNKNOWN when it cannot decide — it never fabricates a verdict.
"""
