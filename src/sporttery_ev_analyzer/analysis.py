from __future__ import annotations

from datetime import timedelta
from itertools import combinations
from typing import Any

from .calculations import combo_ev, fractional_kelly_stake_ratio, remove_margin_proportional, single_ev, validate_decimal_odds
from .io_utils import parse_iso_datetime, utc_now_iso
from .sources import validate_source_names


def analyze(
    normalized: dict[str, Any],
    *,
    ev_threshold: float = 0.0,
    combo_ev_threshold: float = 0.08,
    kelly_fraction: float = 0.1,
    max_source_delta_minutes: int = 180,
    max_data_age_minutes: int = 240,
) -> dict[str, Any]:
    generated_at = utc_now_iso()
    parameters = {
        "ev_threshold": ev_threshold,
        "combo_ev_threshold": combo_ev_threshold,
        "kelly_fraction": kelly_fraction,
        "max_source_delta_minutes": max_source_delta_minutes,
        "max_data_age_minutes": max_data_age_minutes,
    }
    risks: list[str] = [
        "本工具只输出分析报告，不自动下注、不提交订单、不联系售票系统。",
        "赔率数据高度依赖时间，实际决策必须人工基于最新数据复核。",
    ]

    source_validation = _source_validation(normalized)
    if not source_validation["is_usable"]:
        return _blocked_report(normalized, generated_at, {}, parameters, risks, source_validation)

    freshness = _freshness(normalized, generated_at, max_source_delta_minutes, max_data_age_minutes)
    if not freshness["is_usable"]:
        return _blocked_report(normalized, generated_at, freshness, parameters, risks, source_validation)

    if not normalized.get("matches"):
        return _blocked_report(
            normalized,
            generated_at,
            freshness,
            parameters,
            risks,
            source_validation,
            reason="没有可计算的匹配赛事，停止分析，建议空仓并人工复核。",
        )

    singles: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    data_quality_warnings: list[dict[str, Any]] = []
    for match in normalized.get("matches", []):
        try:
            sporttery_odds = _float_odds(match["sporttery"]["odds"])
            market_odds = _float_odds(match["market"]["odds"])
            _validate_same_outcomes(sporttery_odds, market_odds)
            fair_probabilities = remove_margin_proportional(market_odds)
        except (KeyError, TypeError, ValueError) as exc:
            warning = _data_quality_warning(match, str(exc))
            skipped.append(warning)
            data_quality_warnings.append(warning)
            continue

        for outcome, probability in fair_probabilities.items():
            ev = single_ev(probability, sporttery_odds[outcome])
            singles.append(
                {
                    "match_id": match["match_id"],
                    "home_team": match.get("home_team"),
                    "away_team": match.get("away_team"),
                    "start_time": match.get("start_time"),
                    "market_type": match.get("market_type"),
                    "handicap": match.get("handicap"),
                    "outcome": outcome,
                    "sporttery_odds": sporttery_odds[outcome],
                    "market_odds": market_odds[outcome],
                    "sporttery_updated_at": match.get("sporttery", {}).get("updated_at"),
                    "market_updated_at": match.get("market", {}).get("updated_at"),
                    "fair_probability": probability,
                    "single_ev": ev,
                }
            )

    if not singles:
        return _blocked_report(
            normalized,
            generated_at,
            freshness,
            parameters,
            risks,
            source_validation,
            reason="没有可计算的 EV 明细，停止分析，建议空仓并人工复核。",
            skipped=skipped,
            data_quality_warnings=data_quality_warnings,
        )

    positive_singles = [item for item in singles if item["single_ev"] > ev_threshold and item["single_ev"] > 0.0]
    combos = _build_combos(positive_singles, combo_ev_threshold, kelly_fraction)
    conclusion = "存在可复核的正 EV 2串1候选" if combos else "无法配对，建议空仓"

    return {
        "report_status": "ok",
        "generated_at": generated_at,
        "inputs": normalized.get("inputs", {}),
        "source_validation": source_validation,
        "freshness": freshness,
        "parameters": parameters,
        "conclusion": conclusion,
        "single_ev": singles,
        "positive_single_ev": positive_singles,
        "combo_candidates": combos,
        "unmatched": normalized.get("unmatched", []),
        "skipped": skipped,
        "data_quality_warnings": data_quality_warnings,
        "risks": risks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 竞彩 +EV 分析报告",
        "",
        f"- 报告状态：{report['report_status']}",
        f"- 生成时间：{report['generated_at']}",
        f"- 结论：{report['conclusion']}",
        "",
        "## 数据源校验",
        "",
        f"- 是否通过：{report.get('source_validation', {}).get('is_usable')}",
    ]
    source_errors = report.get("source_validation", {}).get("errors", [])
    if source_errors:
        lines.extend(f"- {error}" for error in source_errors)
    else:
        lines.append("- 无数据源错误。")
    lines.extend(
        [
        "",
        "## 时效性",
        "",
        ]
    )
    freshness = report.get("freshness", {})
    lines.extend(
        [
            f"- 竞彩数据时间：{freshness.get('sporttery_fetched_at')}",
            f"- 国际赔率数据时间：{freshness.get('market_fetched_at')}",
            f"- 时间差分钟：{freshness.get('source_delta_minutes')}",
            f"- 竞彩数据年龄分钟：{freshness.get('sporttery_age_minutes')}",
            f"- 国际赔率数据年龄分钟：{freshness.get('market_age_minutes')}",
            f"- 是否可用于本次分析：{freshness.get('is_usable')}",
        "",
            "## 全部 EV 对比明细",
            "",
        ]
    )
    all_items = report.get("single_ev", [])
    if all_items:
        lines.append("| 比赛 | 玩法 | 盘口 | 选项 | 竞彩赔率 | 竞彩赔率时间 | Pinnacle赔率 | Pinnacle时间 | 公允概率 | EV |")
        lines.append("| --- | --- | --- | --- | ---: | --- | ---: | --- | ---: | ---: |")
        for item in all_items:
            match_name = f"{item['home_team']} vs {item['away_team']}"
            lines.append(
                f"| {match_name} | {item['market_type']} | {item.get('handicap', '')} | {item['outcome']} | "
                f"{item['sporttery_odds']:.3f} | {item.get('sporttery_updated_at')} | "
                f"{item['market_odds']:.3f} | {item.get('market_updated_at')} | "
                f"{item['fair_probability']:.4f} | {item['single_ev']:.4f} |"
            )
    else:
        lines.append("无可计算 EV 明细。")

    lines.extend(["", "## 正 EV 单项", ""])
    positives = report.get("positive_single_ev", [])
    if positives:
        lines.append("| 比赛 | 玩法 | 选项 | 竞彩赔率 | 公允概率 | EV |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: |")
        for item in positives:
            match_name = f"{item['home_team']} vs {item['away_team']}"
            lines.append(
                f"| {match_name} | {item['market_type']} | {item['outcome']} | "
                f"{item['sporttery_odds']:.3f} | {item['fair_probability']:.4f} | {item['single_ev']:.4f} |"
            )
    else:
        lines.append("无正 EV 单项。")

    lines.extend(["", "## 2串1候选", ""])
    combos = report.get("combo_candidates", [])
    if combos:
        lines.append("| 组合 | 组合赔率 | 组合 EV | 分数凯利资金比例 |")
        lines.append("| --- | ---: | ---: | ---: |")
        for combo in combos:
            name = " + ".join(f"{leg['home_team']} vs {leg['away_team']} {leg['outcome']}" for leg in combo["legs"])
            lines.append(
                f"| {name} | {combo['combo_odds']:.3f} | {combo['combo_ev']:.4f} | {combo['stake_ratio']:.4f} |"
            )
    else:
        lines.append("无法配对，建议空仓。")

    lines.extend(["", "## 人工复核", ""])
    lines.append(f"- 无法匹配项：{len(report.get('unmatched', []))}")
    lines.append(f"- 跳过项：{len(report.get('skipped', []))}")
    lines.extend(["", "## 数据质量警告", ""])
    warnings = report.get("data_quality_warnings", [])
    if warnings:
        lines.append("| 比赛 | 玩法 | 盘口 | 来源 | 原因 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for warning in warnings:
            match_name = f"{warning.get('home_team')} vs {warning.get('away_team')}"
            lines.append(
                f"| {match_name} | {warning.get('market_type')} | {warning.get('handicap')} | "
                f"{warning.get('source')} | {warning.get('reason')} |"
            )
    else:
        lines.append("无。")
    lines.extend(["", "## 风险提示", ""])
    lines.extend(f"- {risk}" for risk in report.get("risks", []))
    lines.append("")
    return "\n".join(lines)


def _blocked_report(
    normalized: dict[str, Any],
    generated_at: str,
    freshness: dict[str, Any],
    parameters: dict[str, Any],
    risks: list[str],
    source_validation: dict[str, Any] | None = None,
    reason: str | None = None,
    skipped: list[dict[str, Any]] | None = None,
    data_quality_warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocked_reason = reason or "数据时间差过大或时间戳缺失，停止分析，建议空仓并人工复核。"
    if source_validation and not source_validation.get("is_usable", True):
        blocked_reason = "数据源不符合要求，必须使用官方竞彩与 Pinnacle，停止分析。"
    return {
        "report_status": "blocked",
        "generated_at": generated_at,
        "inputs": normalized.get("inputs", {}),
        "source_validation": source_validation or _source_validation(normalized),
        "freshness": freshness,
        "parameters": parameters,
        "conclusion": blocked_reason,
        "single_ev": [],
        "positive_single_ev": [],
        "combo_candidates": [],
        "unmatched": normalized.get("unmatched", []),
        "skipped": skipped or [],
        "data_quality_warnings": data_quality_warnings or [],
        "risks": risks,
    }


def _source_validation(normalized: dict[str, Any]) -> dict[str, Any]:
    inputs = normalized.get("inputs", {})
    sporttery_source = str(inputs.get("sporttery", {}).get("source", "unknown"))
    market_source = str(inputs.get("market", {}).get("source", "unknown"))
    errors = validate_source_names(sporttery_source, market_source)

    if "source_validation" in normalized:
        validation = normalized["source_validation"]
        errors.extend(str(error) for error in validation.get("errors", []))
        errors = list(dict.fromkeys(errors))
        return {
            "is_usable": not errors and bool(validation.get("is_usable")),
            "errors": errors,
        }
    return {"is_usable": not errors, "errors": errors}


def _data_quality_warning(match: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "match_id": match.get("match_id"),
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
        "market_type": match.get("market_type"),
        "handicap": match.get("handicap"),
        "source": "sporttery,market",
        "reason": reason,
    }


def _freshness(
    normalized: dict[str, Any],
    generated_at: str,
    max_source_delta_minutes: int,
    max_data_age_minutes: int,
) -> dict[str, Any]:
    inputs = normalized.get("inputs", {})
    sporttery_time = inputs.get("sporttery", {}).get("fetched_at")
    market_time = inputs.get("market", {}).get("fetched_at")
    if not sporttery_time or not market_time:
        return {
            "sporttery_fetched_at": sporttery_time,
            "market_fetched_at": market_time,
            "source_delta_minutes": None,
            "sporttery_age_minutes": None,
            "market_age_minutes": None,
            "max_data_age_minutes": max_data_age_minutes,
            "is_usable": False,
            "reason": "missing_fetched_at",
        }
    generated_at_dt = parse_iso_datetime(generated_at)
    sporttery_dt = parse_iso_datetime(sporttery_time)
    market_dt = parse_iso_datetime(market_time)
    delta = abs(sporttery_dt - market_dt)
    sporttery_age = abs(generated_at_dt - sporttery_dt)
    market_age = abs(generated_at_dt - market_dt)
    source_delta_ok = delta <= timedelta(minutes=max_source_delta_minutes)
    sporttery_age_ok = sporttery_age <= timedelta(minutes=max_data_age_minutes)
    market_age_ok = market_age <= timedelta(minutes=max_data_age_minutes)
    is_usable = source_delta_ok and sporttery_age_ok and market_age_ok
    reason = None
    if not source_delta_ok:
        reason = "source_time_delta_too_large"
    elif not sporttery_age_ok or not market_age_ok:
        reason = "data_age_too_large"
    return {
        "sporttery_fetched_at": sporttery_time,
        "market_fetched_at": market_time,
        "source_delta_minutes": round(delta.total_seconds() / 60, 2),
        "sporttery_age_minutes": round(sporttery_age.total_seconds() / 60, 2),
        "market_age_minutes": round(market_age.total_seconds() / 60, 2),
        "max_data_age_minutes": max_data_age_minutes,
        "is_usable": is_usable,
        "reason": reason,
    }


def _float_odds(odds: dict[str, Any]) -> dict[str, float]:
    converted = {str(name): float(value) for name, value in odds.items()}
    validate_decimal_odds(converted)
    return converted


def _validate_same_outcomes(first: dict[str, float], second: dict[str, float]) -> None:
    if set(first) != set(second):
        raise ValueError(f"outcome mismatch: sporttery={sorted(first)} market={sorted(second)}")


def _build_combos(
    positive_singles: list[dict[str, Any]],
    combo_ev_threshold: float,
    kelly_fraction: float,
) -> list[dict[str, Any]]:
    combos: list[dict[str, Any]] = []
    for first, second in combinations(positive_singles, 2):
        if first["match_id"] == second["match_id"]:
            continue
        expected_value = combo_ev(first["single_ev"], second["single_ev"])
        if expected_value < combo_ev_threshold:
            continue
        combo_odds = first["sporttery_odds"] * second["sporttery_odds"]
        combos.append(
            {
                "legs": [first, second],
                "combo_odds": combo_odds,
                "combo_ev": expected_value,
                "stake_ratio": fractional_kelly_stake_ratio(expected_value, combo_odds, kelly_fraction),
            }
        )
    return sorted(combos, key=lambda item: item["combo_ev"], reverse=True)
