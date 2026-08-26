from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from .adapters.gbiz import GBIZ_TERMS_URL, GbizClient, transform_gbiz_company
from .config import Settings
from .dataset import load_dataset, sample_dataset_path
from .repository import Repository


def _yyyymmdd(value: str):
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a date in YYYYMMDD format") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import licensed data into JP Business Signals")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="Import the bundled synthetic dataset")
    sample.add_argument("--reset", action="store_true", help="Delete existing records first")

    json_parser = subparsers.add_parser("json", help="Import a validated JSON dataset")
    json_parser.add_argument("path", type=Path)
    json_parser.add_argument("--reset", action="store_true", help="Delete existing records first")

    gbiz = subparsers.add_parser("gbiz", help="Synchronize company updates from gBizINFO v2")
    gbiz.add_argument("--from", dest="from_date", type=_yyyymmdd, required=True)
    gbiz.add_argument("--to", dest="to_date", type=_yyyymmdd, required=True)
    gbiz.add_argument(
        "--max-pages",
        type=int,
        default=5,
        choices=range(1, 101),
        metavar="1..100",
        help="Safety cap for this run; default: 5",
    )
    gbiz.add_argument("--reset", action="store_true", help="Delete existing records first")
    gbiz.add_argument(
        "--skip-procurement",
        action="store_true",
        help="Skip the separate procurement update endpoint",
    )
    gbiz.add_argument(
        "--terms-confirmed",
        action="store_true",
        help="Confirm that the current gBizINFO terms and declared token purpose permit this run",
    )
    return parser


def _import_dataset(args, settings: Settings, repository: Repository) -> None:
    path = sample_dataset_path() if args.command == "sample" else args.path
    dataset = load_dataset(path)
    if args.reset:
        repository.reset()
    companies = repository.upsert_companies(dataset.companies)
    signals = repository.insert_signals(dataset.signals)
    print(f"Imported {companies} companies and {signals} new signals from {path}")


def _sync_gbiz(args, settings: Settings, repository: Repository, parser) -> None:
    if not args.terms_confirmed:
        parser.error(f"Review {GBIZ_TERMS_URL} and pass --terms-confirmed")
    if not settings.gbiz_api_token:
        parser.error("GBIZ_API_TOKEN is required for the gbiz command")
    if args.from_date > args.to_date:
        parser.error("--from must be on or before --to")

    company_count = 0
    signal_count = 0
    procurement_company_count = 0
    procurement_signal_count = 0
    skipped_count = 0
    reset_pending = args.reset
    with GbizClient(
        token=settings.gbiz_api_token,
        base_url=settings.gbiz_base_url,
        timeout_seconds=settings.gbiz_timeout_seconds,
        request_interval_seconds=settings.gbiz_request_interval_seconds,
    ) as client:
        pages = client.iter_updated_company_pages(
            from_date=args.from_date,
            to_date=args.to_date,
            max_pages=args.max_pages,
        )
        for raw_records in pages:
            companies = []
            signals = []
            for raw in raw_records:
                try:
                    company, company_signals = transform_gbiz_company(raw)
                except ValueError:
                    skipped_count += 1
                    continue
                companies.append(company)
                signals.extend(company_signals)
            if reset_pending:
                repository.reset()
                reset_pending = False
            company_count += repository.upsert_companies(companies)
            signal_count += repository.insert_signals(signals)

        if not args.skip_procurement:
            procurement_pages = client.iter_updated_procurement_pages(
                from_date=args.from_date,
                to_date=args.to_date,
                max_pages=args.max_pages,
            )
            for raw_records in procurement_pages:
                companies = []
                signals = []
                corporate_numbers = []
                for raw in raw_records:
                    try:
                        company, company_signals = transform_gbiz_company(raw)
                    except ValueError:
                        skipped_count += 1
                        continue
                    companies.append(company)
                    signals.extend(company_signals)
                    corporate_numbers.append(company.corporate_number)
                procurement_company_count += repository.insert_companies_if_missing(companies)
                procurement_signal_count += repository.insert_signals(signals)
                repository.refresh_activity_metrics(corporate_numbers)

    print(
        f"Synchronized {company_count} company profiles and "
        f"{procurement_company_count} procurement-only companies; "
        f"added {signal_count} profile signals and "
        f"{procurement_signal_count} procurement signals; "
        f"skipped {skipped_count} invalid records"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.from_env()
    repository = Repository(settings.database_path)
    repository.initialize()
    if args.command in {"sample", "json"}:
        _import_dataset(args, settings, repository)
    else:
        _sync_gbiz(args, settings, repository, parser)


if __name__ == "__main__":
    main()
