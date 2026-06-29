from __future__ import annotations

from datetime import timedelta
from itertools import combinations
from typing import Any
from zoneinfo import ZoneInfo

from .calculations import combo_ev, fractional_kelly_stake_ratio, remove_margin_all_methods, single_ev, validate_decimal_odds
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
    risks = [
        "本工具只输出分析报告，不自动下注、不提交订单、不联系售票系统。",
        "赔率数据高度依赖时间，实际决策必须人工基于最新数据复核。",
        "Shin/指数去水仅作敏感性对比，不自动替代主算法候选判断。",
    ]

    source_validation = _source_validation(normalized)
    if not source_validation["is_usable"]:
        return _blocked_report(normalized, generated_at, {}, parameters, risks, source_validation)

    snapshot_integrity = _snapshot_integrity(normalized)
    if not snapshot_integrity["is_usable"]:
        return _blocked_report(
            normalized,
            generated_at,
            {},
            parameters,
            risks,
            source_validation,
            reason="Pinnacle 快照疑似不完整，可能访问了错误页面或盘口未展开，停止分析并建议人工复核。",
        )

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
            margin_methods = remove_margin_all_methods(market_odds)
            if margin_methods["proportional"]["status"] != "ok":
                raise ValueError(margin_methods["proportional"]["error"])
            fair_probabilities = margin_methods["proportional"]["probabilities"]
        except (KeyError, TypeError, ValueError) as exc:
            warning = _data_quality_warning(match, str(exc))
            skipped.append(warning)
            data_quality_warnings.append(warning)
            continue

        for method_name in ("shin", "power"):
            if margin_methods[method_name]["status"] != "ok":
                data_quality_warnings.append(
                    _data_quality_warning(match, f"{method_name} margin removal failed: {margin_methods[method_name]['error']}")
                )

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
                    "method_comparison": _method_comparison(margin_methods, sporttery_odds, outcome),
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
    conclusion = "存在可复核的正 EV 2 串 1 候选" if combos else "无法配对，建议空仓"

    return {
        "report_status": "ok",
        "generated_at": generated_at,
        "inputs": normalized.get("inputs", {}),
        "source_validation": source_validation,
        "snapshot_integrity": snapshot_integrity,
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
    lines.extend(f"- {error}" for error in source_errors)
    if not source_errors:
        lines.append("- 无数据源错误。")

    integrity = report.get("snapshot_integrity", {})
    integrity_errors = integrity.get("errors", [])
    lines.extend(
        [
            "",
            "## 快照完整性",
            "",
            f"- 是否通过：{integrity.get('is_usable')}",
            f"- Pinnacle 玩法计数：{_format_counts(integrity.get('market_type_counts', {}))}",
        ]
    )
    lines.extend(f"- {error}" for error in integrity_errors)
    if not integrity_errors:
        lines.append("- 无快照完整性错误。")

    freshness = report.get("freshness", {})
    lines.extend(
        [
            "",
            "## 时效性",
            "",
            f"- 竞彩数据抓取时间：{_format_beijing_time(freshness.get('sporttery_fetched_at'))}",
            f"- Pinnacle 数据抓取时间：{_format_beijing_time(freshness.get('market_fetched_at'))}",
            f"- 时间差分钟：{freshness.get('source_delta_minutes')}",
            f"- 竞彩数据年龄分钟：{freshness.get('sporttery_age_minutes')}",
            f"- Pinnacle 数据年龄分钟：{freshness.get('market_age_minutes')}",
            f"- 是否可用于本次分析：{freshness.get('is_usable')}",
            "- Pinnacle 不提供独立发布时间，赔率时间按抓取时间处理；竞彩若有玩法发布时间，只用于数据采集核对，不在明细表逐行展示。",
            "",
            "## 全部 EV 对比明细",
            "",
        ]
    )

    all_items = report.get("single_ev", [])
    if all_items:
        lines.append("| 比赛 | 玩法 | 盘口 | 选项 | 竞彩赔率 | Pinnacle赔率 | 比例概率 | 比例EV |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
        for item in all_items:
            match_name = f"{item['home_team']} vs {item['away_team']}"
            comparison = item.get("method_comparison", {})
            lines.append(
                f"| {match_name} | {item['market_type']} | {item.get('handicap', '')} | {item['outcome']} | "
                f"{item['sporttery_odds']:.3f} | {item['market_odds']:.3f} | "
                f"{_format_method_percent(comparison, 'proportional', 'fair_probability')} | "
                f"{_format_ev_percent(item['single_ev'])} |"
            )

        lines.extend(["", "## 辅助去水方法对比（Shin / 指数）", ""])
        lines.append("| 比赛 | 玩法 | 盘口 | 选项 | Shin概率 | Shin EV | 指数概率 | 指数EV |")
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: |")
        for item in all_items:
            match_name = f"{item['home_team']} vs {item['away_team']}"
            comparison = item.get("method_comparison", {})
            lines.append(
                f"| {match_name} | {item['market_type']} | {item.get('handicap', '')} | {item['outcome']} | "
                f"{_format_method_percent(comparison, 'shin', 'fair_probability')} | "
                f"{_format_method_percent(comparison, 'shin', 'single_ev')} | "
                f"{_format_method_percent(comparison, 'power', 'fair_probability')} | "
                f"{_format_method_percent(comparison, 'power', 'single_ev')} |"
            )
    else:
        lines.append("无可计算 EV 明细。")

    lines.extend(["", "## 正 EV 单项（主算法：比例去水）", ""])
    positives = report.get("positive_single_ev", [])
    if positives:
        lines.append("| 比赛 | 玩法 | 选项 | 竞彩赔率 | 公允概率 | EV |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: |")
        for item in positives:
            match_name = f"{item['home_team']} vs {item['away_team']}"
            lines.append(
                f"| {match_name} | {item['market_type']} | {item['outcome']} | "
                f"{item['sporttery_odds']:.3f} | {_format_percent(item['fair_probability'])} | {_format_percent(item['single_ev'])} |"
            )
    else:
        lines.append("无正 EV 单项。")

    lines.extend(["", "## 2 串 1 候选（主算法：比例去水）", ""])
    combos = report.get("combo_candidates", [])
    if combos:
        lines.append("| 组合 | 组合赔率 | 组合 EV | 分数凯利资金比例 |")
        lines.append("| --- | ---: | ---: | ---: |")
        for combo in combos:
            name = " + ".join(f"{leg['home_team']} vs {leg['away_team']} {leg['outcome']}" for leg in combo["legs"])
            lines.append(
                f"| {name} | {combo['combo_odds']:.3f} | {_format_percent(combo['combo_ev'])} | {_format_percent(combo['stake_ratio'])} |"
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
        "snapshot_integrity": _snapshot_integrity(normalized),
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


def _snapshot_integrity(normalized: dict[str, Any]) -> dict[str, Any]:
    integrity = normalized.get("snapshot_integrity")
    if not isinstance(integrity, dict):
        return {"is_usable": True, "errors": [], "market_type_counts": {}, "sporttery_market_type_counts": {}}
    errors = [str(error) for error in integrity.get("errors", [])]
    return {
        "is_usable": not errors and bool(integrity.get("is_usable", True)),
        "errors": errors,
        "market_type_counts": integrity.get("market_type_counts", {}),
        "sporttery_market_type_counts": integrity.get("sporttery_market_type_counts", {}),
    }


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
    sporttery_age = generated_at_dt - sporttery_dt
    market_age = generated_at_dt - market_dt
    max_future_skew = timedelta(seconds=120)
    sporttery_future_ok = sporttery_age >= -max_future_skew
    market_future_ok = market_age >= -max_future_skew
    sporttery_effective_age = max(sporttery_age, timedelta(0))
    market_effective_age = max(market_age, timedelta(0))
    source_delta_ok = delta <= timedelta(minutes=max_source_delta_minutes)
    sporttery_age_ok = sporttery_effective_age <= timedelta(minutes=max_data_age_minutes)
    market_age_ok = market_effective_age <= timedelta(minutes=max_data_age_minutes)
    is_usable = source_delta_ok and sporttery_age_ok and market_age_ok and sporttery_future_ok and market_future_ok
    reason = None
    if not source_delta_ok:
        reason = "source_time_delta_too_large"
    elif not sporttery_future_ok or not market_future_ok:
        reason = "source_fetched_at_in_future"
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


def _method_comparison(
    margin_methods: dict[str, dict[str, Any]],
    sporttery_odds: dict[str, float],
    outcome: str,
) -> dict[str, dict[str, Any]]:
    comparison: dict[str, dict[str, Any]] = {}
    for method_name, result in margin_methods.items():
        if result["status"] != "ok":
            comparison[method_name] = {"status": "failed", "error": result["error"]}
            continue
        probability = result["probabilities"][outcome]
        comparison[method_name] = {
            "status": "ok",
            "fair_probability": probability,
            "single_ev": single_ev(probability, sporttery_odds[outcome]),
            **result["params"],
        }
    return comparison


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


def _format_percent(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _ev_marker(value: Any) -> str:
    ev = float(value)
    if ev > 0:
        return "🟢"
    if ev >= -0.025:
        return "🟡"
    if ev >= -0.05:
        return "🟠"
    return ""


def _format_ev_percent(value: Any) -> str:
    percent = _format_percent(value)
    if float(value) > 0:
        percent = f"**{percent}**"
    marker = _ev_marker(value)
    return f"{marker} {percent}" if marker else percent


def _format_beijing_time(value: Any) -> str:
    if not value:
        return "无"
    return parse_iso_datetime(str(value)).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S 北京时间")


def _format_method_percent(comparison: dict[str, Any], method_name: str, field: str) -> str:
    method = comparison.get(method_name, {})
    if method.get("status") != "ok" or field not in method:
        return "N/A"
    return _format_percent(method[field])


def _format_counts(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "无"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
