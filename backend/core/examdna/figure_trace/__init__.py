"""FigureDNA — pixel → FigureScene extraction (RESTORE-14).

The extractor turns figure-region ink into a typed scene candidate:
Hough segments become `segment` primitives with shared `point` nodes,
circles become `circle` primitives, and geometric relations
(intersection / parallel / perpendicular / equal_length) are derived
from measured geometry — never asserted from model output. The result
is always a *candidate* for review and semantic checks, not a verdict.
"""
