from __future__ import annotations

from jp_business_signals.dataset import load_dataset, sample_dataset_path
from jp_business_signals.repository import Repository


def test_activity_refresh_counts_dated_signals(tmp_path) -> None:
    repository = Repository(tmp_path / "repository.db")
    repository.initialize()
    dataset = load_dataset(sample_dataset_path())
    company = dataset.companies[0]
    procurement_signal = next(
        signal
        for signal in dataset.signals
        if signal.corporate_number == company.corporate_number
        and signal.signal_type == "procurement"
    )
    repository.upsert_companies([company])
    repository.insert_signals([procurement_signal])

    refreshed = repository.refresh_activity_metrics([company.corporate_number])
    result = repository.get_company(company.corporate_number)

    assert refreshed == 1
    assert result is not None
    assert result.procurement_count == 1
    assert result.subsidy_count == 0
    assert result.patent_count == 0
    assert result.activity_score == 14


def test_insert_companies_if_missing_preserves_existing_profile(tmp_path) -> None:
    repository = Repository(tmp_path / "repository.db")
    repository.initialize()
    company = load_dataset(sample_dataset_path()).companies[0]
    repository.upsert_companies([company])
    activity_only_company = company.model_copy(
        update={"name": "Activity endpoint partial name", "industry": None}
    )

    inserted = repository.insert_companies_if_missing([activity_only_company])
    result = repository.get_company(company.corporate_number)

    assert inserted == 0
    assert result is not None
    assert result.name == company.name
    assert result.industry == company.industry
