"""Standalone fixture for exercising PR review comments; not production code."""


def mean_chunk_score(scores: list[float]) -> float:
    """Return the arithmetic mean; an empty list should produce 0.0."""
    return sum(scores) / len(scores)
