from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_QUERIES = 8
MAX_QUERY_VARIANTS = 12


@dataclass(frozen=True, slots=True)
class CapabilityVocabulary:
    """English capability aliases and their useful Japanese search terms."""

    name: str
    aliases: tuple[str, ...]
    related_queries: tuple[str, ...]


CAPABILITY_VOCABULARY: tuple[CapabilityVocabulary, ...] = (
    CapabilityVocabulary(
        name="cloud",
        aliases=("cloud computing", "cloud", "saas", "paas", "iaas"),
        related_queries=(
            "クラウド",
            "クラウドコンピューティング",
            "SaaS",
            "システム基盤",
        ),
    ),
    CapabilityVocabulary(
        name="cybersecurity",
        aliases=("cybersecurity", "cyber security", "information security", "infosec"),
        related_queries=(
            "サイバーセキュリティ",
            "情報セキュリティ",
            "セキュリティ対策",
        ),
    ),
    CapabilityVocabulary(
        name="artificial-intelligence",
        aliases=(
            "artificial intelligence",
            "generative ai",
            "machine learning",
            "genai",
            "ai",
        ),
        related_queries=("人工知能", "生成AI", "機械学習"),
    ),
    CapabilityVocabulary(
        name="software",
        aliases=("application development", "system development", "software"),
        related_queries=("ソフトウェア", "システム開発", "アプリケーション開発"),
    ),
    CapabilityVocabulary(
        name="data-analytics",
        aliases=("data analytics", "data analysis", "business intelligence", "analytics"),
        related_queries=("データ分析", "データ解析", "ビッグデータ"),
    ),
    CapabilityVocabulary(
        name="robotics",
        aliases=("robotic process automation", "robotics", "automation", "robot"),
        related_queries=("ロボット", "ロボティクス", "自動化"),
    ),
    CapabilityVocabulary(
        name="medical",
        aliases=("medical technology", "health technology", "healthcare", "medtech", "medical"),
        related_queries=("医療", "ヘルスケア", "医療機器"),
    ),
    CapabilityVocabulary(
        name="consulting",
        aliases=("management consulting", "consultancy", "consulting", "advisory"),
        related_queries=("コンサルティング", "調査業務", "業務支援"),
    ),
)


def expand_capability_query(
    query: str,
    *,
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> tuple[str, ...]:
    """Expand an English capability query into deterministic Japanese search terms.

    The stripped original query is always the first result. Related terms are added
    for every recognized capability, ordered by the capability's first appearance in
    the input. Results are deduplicated and capped at ``MAX_QUERY_VARIANTS`` even if a
    caller requests a larger value, keeping downstream source calls bounded.
    """

    original = query.strip()
    if not original:
        raise ValueError("query must not be empty")
    if max_queries < 1:
        raise ValueError("max_queries must be at least 1")

    effective_limit = min(max_queries, MAX_QUERY_VARIANTS)
    matched = _matched_vocabularies(original)
    candidates = (
        original,
        *(term for vocabulary in matched for term in vocabulary.related_queries),
    )

    expanded: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        dedupe_key = candidate.casefold()
        if dedupe_key in seen:
            continue
        expanded.append(candidate)
        seen.add(dedupe_key)
        if len(expanded) == effective_limit:
            break

    return tuple(expanded)


def _matched_vocabularies(query: str) -> tuple[CapabilityVocabulary, ...]:
    matches: list[tuple[int, int, CapabilityVocabulary]] = []
    for vocabulary_index, vocabulary in enumerate(CAPABILITY_VOCABULARY):
        positions = [
            position
            for alias in vocabulary.aliases
            if (position := _alias_position(query, alias)) is not None
        ]
        if positions:
            matches.append((min(positions), vocabulary_index, vocabulary))

    matches.sort(key=lambda item: (item[0], item[1]))
    return tuple(item[2] for item in matches)


def _alias_position(query: str, alias: str) -> int | None:
    words = re.split(r"\s+", alias)
    alias_pattern = r"\s+".join(re.escape(word) for word in words)
    pattern = rf"(?<![0-9A-Za-z]){alias_pattern}(?![0-9A-Za-z])"
    match = re.search(pattern, query, flags=re.IGNORECASE)
    return match.start() if match else None
