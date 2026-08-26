from __future__ import annotations


def calculate_activity_score(
    *,
    procurement_count: int,
    subsidy_count: int,
    patent_count: int,
    certification_count: int,
) -> int:
    score = 10
    score += min(max(procurement_count, 0) * 4, 35)
    score += min(max(subsidy_count, 0) * 3, 20)
    score += min(max(patent_count, 0) * 2, 25)
    score += min(max(certification_count, 0), 10)
    return min(score, 100)
