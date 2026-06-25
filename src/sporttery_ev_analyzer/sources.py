from __future__ import annotations

SPORTTERY_SOURCES = {"sporttery", "sporttery_browser"}
PINNACLE_SOURCES = {"pinnacle", "pinnacle_browser"}


def validate_source_names(sporttery_source: str, market_source: str) -> list[str]:
    errors: list[str] = []
    if sporttery_source not in SPORTTERY_SOURCES:
        errors.append(f"sporttery source must be one of {sorted(SPORTTERY_SOURCES)}: {sporttery_source}")
    if market_source not in PINNACLE_SOURCES:
        errors.append(f"market source must be one of {sorted(PINNACLE_SOURCES)}: {market_source}")
    return errors
