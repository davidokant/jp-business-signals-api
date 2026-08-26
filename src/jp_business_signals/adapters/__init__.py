"""Adapters for explicitly permitted upstream data sources."""

from .gbiz import GbizClient, GbizError, transform_gbiz_company

__all__ = ["GbizClient", "GbizError", "transform_gbiz_company"]
