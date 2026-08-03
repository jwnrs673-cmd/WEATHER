"""取得 → 解析 → 集計 → 出力 の一連の流れ。"""

from __future__ import annotations

import logging
from pathlib import Path

from . import aggregate, compare, render, render_compare, stations as stations_mod
from .fetch_jma import fetch_daily_page
from .models import DailyRecord, Station
from .parse_jma import parse_daily_page
from .prefectures import Prefecture

logger = logging.getLogger(__name__)


class Paths:
    """出力先のディレクトリ構成。

    ``data/raw`` に取得した HTML、``reports`` に成果物を置く。
    県と対象月ごとにディレクトリを分け、上書き事故を避ける。
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = root / "config"
        self.raw = root / "data" / "raw"
        self.reports = root / "reports"

    def raw_dir(self, pref: Prefecture, year: int, month: int) -> Path:
        return self.raw / pref.slug / f"{year}-{month:02d}"

    def report_dir(self, pref: Prefecture, year: int, month: int) -> Path:
        return self.reports / f"{year}-{month:02d}" / pref.slug

    def index_path(self, year: int, month: int) -> Path:
        return self.reports / f"{year}-{month:02d}" / "README.md"


def collect_prefecture(
    pref: Prefecture,
    year: int,
    month: int,
    paths: Paths,
    *,
    refresh: bool = False,
    max_stations: int | None = None,
) -> aggregate.PrefectureSummary:
    """1 県分のデータを集めて集計する。

    1 地点の取得に失敗しても、その地点を飛ばして残りで続行する。
    県全体が落ちるより、欠けた地点を注記して出す方が有用なため。
    """
    raw_dir = paths.raw_dir(pref, year, month)
    found = stations_mod.load_stations(
        pref, config_dir=paths.config, cache_dir=raw_dir, refresh=refresh
    )
    representative = stations_mod.representative(found, pref)

    # 代表地点は必ず含めたうえで、必要なら地点数を絞る。
    targets = found if max_stations is None else found[:max_stations]
    if representative not in targets:
        targets = [representative, *targets]

    by_station: dict[Station, list[DailyRecord]] = {}
    for station in targets:
        try:
            html = fetch_daily_page(station, year, month, raw_dir, refresh=refresh)
            records = parse_daily_page(html, station, year, month)
        except Exception as exc:
            logger.warning(
                "%s / %s(%s) を取得できませんでした: %s",
                pref.name,
                station.name,
                station.block_no,
                exc,
            )
            continue
        if records:
            by_station[station] = records

    if not by_station:
        raise RuntimeError(
            f"{pref.name} {year}年{month}月: どの地点からもデータを取得できませんでした"
        )
    if representative not in by_station:
        # 代表地点が落ちた場合は、取得できた中から選び直す。
        representative = next(
            (s for s in by_station if s.is_official), next(iter(by_station))
        )
        logger.warning("%s: 代表地点を %s に変更しました", pref.name, representative.name)

    return aggregate.build(year, month, representative, by_station)


def _write_comparison(
    pref: Prefecture,
    current: aggregate.PrefectureSummary,
    compare_with: tuple[int, int],
    paths: Paths,
    output_dir: Path,
    *,
    refresh: bool = False,
    max_stations: int | None = None,
) -> None:
    """比較対象月を取得して前年同月比レポートを書き出す。

    比較は付加的な出力なので、失敗しても当年のレポートは残す。
    """
    prev_year, prev_month = compare_with
    logger.info("--- %s %d年%d月（比較対象）---", pref.name, prev_year, prev_month)
    try:
        previous = collect_prefecture(
            pref,
            prev_year,
            prev_month,
            paths,
            refresh=refresh,
            max_stations=max_stations,
        )
    except Exception as exc:
        logger.error(
            "%s の比較をスキップします（%d年%d月を取得できませんでした）: %s",
            pref.name,
            prev_year,
            prev_month,
            exc,
        )
        return

    comparison = compare.build(current, previous)
    markdown_path, csv_path = render_compare.write_report(output_dir, pref, comparison)
    logger.info("比較出力: %s / %s", markdown_path, csv_path)


def run(
    prefectures: list[Prefecture],
    year: int,
    month: int,
    paths: Paths,
    *,
    refresh: bool = False,
    max_stations: int | None = None,
    compare_with: tuple[int, int] | None = None,
) -> list[tuple[Prefecture, aggregate.PrefectureSummary]]:
    """複数県のレポートを作る。県ごとに Markdown と CSV を書き出す。

    ``compare_with`` に ``(年, 月)`` を渡すと、その月も取得して前年同月比の
    レポートを追加で書き出す。比較対象の取得に失敗した県は、通常のレポート
    だけを残して比較を飛ばす。
    """
    results: list[tuple[Prefecture, aggregate.PrefectureSummary]] = []
    for pref in prefectures:
        logger.info("=== %s %d年%d月 ===", pref.name, year, month)
        try:
            result = collect_prefecture(
                pref, year, month, paths, refresh=refresh, max_stations=max_stations
            )
        except Exception as exc:
            logger.error("%s をスキップします: %s", pref.name, exc)
            continue
        output_dir = paths.report_dir(pref, year, month)
        markdown_path, csv_path = render.write_report(output_dir, pref, result)
        logger.info("出力: %s / %s", markdown_path, csv_path)

        if compare_with is not None:
            _write_comparison(
                pref,
                result,
                compare_with,
                paths,
                output_dir,
                refresh=refresh,
                max_stations=max_stations,
            )

        results.append((pref, result))

    if len(results) > 1:
        index_path = paths.index_path(year, month)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(render.render_index(year, month, results), encoding="utf-8")
        logger.info("一覧: %s", index_path)

    return results
