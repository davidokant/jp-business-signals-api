from __future__ import annotations

import pytest

from jp_business_signals.query_expansion import MAX_QUERY_VARIANTS, expand_capability_query


@pytest.mark.parametrize(
    ("query", "expected_terms"),
    [
        ("cloud", ("クラウド", "クラウドコンピューティング", "SaaS", "システム基盤")),
        ("cybersecurity", ("サイバーセキュリティ", "情報セキュリティ", "セキュリティ対策")),
        ("AI", ("人工知能", "生成AI", "機械学習")),
        ("software", ("ソフトウェア", "システム開発", "アプリケーション開発")),
        ("data analytics", ("データ分析", "データ解析", "ビッグデータ")),
        ("robotics", ("ロボット", "ロボティクス", "自動化")),
        ("medical", ("医療", "ヘルスケア", "医療機器")),
        ("consulting", ("コンサルティング", "調査業務", "業務支援")),
    ],
)
def test_expands_supported_english_capabilities(
    query: str,
    expected_terms: tuple[str, ...],
) -> None:
    expanded = expand_capability_query(query)

    assert expanded[0] == query
    assert expanded[1:] == expected_terms


def test_preserves_unknown_and_whitespace_trimmed_query() -> None:
    assert expand_capability_query("  quantum sensing  ") == ("quantum sensing",)


def test_alias_matching_is_case_insensitive_and_respects_word_boundaries() -> None:
    assert expand_capability_query("Generative AI")[1:] == ("人工知能", "生成AI", "機械学習")
    assert expand_capability_query("email delivery") == ("email delivery",)


def test_multiple_capabilities_follow_their_order_in_the_query() -> None:
    assert expand_capability_query("robotics and cloud", max_queries=5) == (
        "robotics and cloud",
        "ロボット",
        "ロボティクス",
        "自動化",
        "クラウド",
    )


def test_deduplicates_original_from_generated_aliases() -> None:
    assert expand_capability_query("SaaS") == (
        "SaaS",
        "クラウド",
        "クラウドコンピューティング",
        "システム基盤",
    )


def test_requested_and_absolute_limits_are_enforced() -> None:
    assert len(expand_capability_query("cloud cybersecurity AI", max_queries=3)) == 3
    assert (
        len(
            expand_capability_query(
                "cloud cybersecurity AI software data analytics robotics medical consulting",
                max_queries=10_000,
            )
        )
        == MAX_QUERY_VARIANTS
    )


@pytest.mark.parametrize(("query", "max_queries"), [("  ", 8), ("cloud", 0), ("cloud", -1)])
def test_rejects_invalid_inputs(query: str, max_queries: int) -> None:
    with pytest.raises(ValueError):
        expand_capability_query(query, max_queries=max_queries)
