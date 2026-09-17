from __future__ import annotations


def get_guide(subject: str):
    """Subject guides plug in here. ExamDNA core stays subject-agnostic."""
    from . import mathematics

    if subject == "mathematics":
        return mathematics
    raise KeyError(f"no guide registered for subject={subject!r}")
