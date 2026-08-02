"""集計結果を Markdown と CSV に書き出す。"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from .aggregate import Extreme, MonthlySummary, PrefectureSummary
from .models import FIELD_LABELS, VALUE_FIELDS, DailyRecord, Station
from .narrative import describe_day, notable_days
from .prefectures import Prefecture

SOURCE_NAME = "気象庁「過去の気象データ検索」"
SOURCE_URL = "https://www.data.jma.go.jp/obd/stats/etrn/index.php"

_WEEKDAY = ("月", "火", "水", "木", "金", "土", "日")


def _num(value: float | None, *, digits: int = 1) -> str:
    """表のセル。欠測は「--」。"""
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def _text(value: str | None) -> str:
    return value if value else "--"


def _extreme_cell(extreme: Extreme | None, unit: str, *, digits: int = 1) -> str:
    """「35.4℃（佐賀・7月20日）」形式のセル。"""
    if extreme is None:
        return "--"
    return f"{extreme.value:.{digits}f}{unit}（{extreme.label}）"


def _extreme_cell_same_day(extreme: Extreme | None, unit: str, *, digits: int = 1) -> str:
    """行が既に日付を示している表で使う、地点名だけのセル。"""
    if extreme is None:
        return "--"
    return f"{extreme.value:.{digits}f}{unit}（{extreme.station.name}）"


def _table(header: list[str], rows: list[list[str]]) -> str:
    """Markdown の表を組み立てる。"""
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _daily_rows_official(records: list[DailyRecord]) -> list[list[str]]:
    """官署向けの日別行。湿度と天気概況を含む。"""
    return [
        [
            str(r.day.day),
            r.weekday_ja,
            _text(r.weather_day),
            _num(r.precip_total),
            _num(r.precip_max_1h),
            _num(r.temp_mean),
            _num(r.temp_max),
            _num(r.temp_min),
            _num(r.humidity_mean, digits=0),
            _num(r.humidity_min, digits=0),
            _num(r.wind_mean),
            f"{_num(r.wind_max)}（{_text(r.wind_max_dir)}）",
            f"{_num(r.wind_gust)}（{_text(r.wind_gust_dir)}）",
            _num(r.sunshine),
        ]
        for r in records
    ]


HEADER_OFFICIAL = [
    "日",
    "曜",
    "天気概況(昼)",
    "降水量計<br>(mm)",
    "最大1h<br>(mm)",
    "平均気温<br>(℃)",
    "最高<br>(℃)",
    "最低<br>(℃)",
    "平均湿度<br>(%)",
    "最小湿度<br>(%)",
    "平均風速<br>(m/s)",
    "最大風速<br>(m/s)",
    "最大瞬間<br>(m/s)",
    "日照<br>(h)",
]


def _daily_rows_amedas(records: list[DailyRecord]) -> list[list[str]]:
    """アメダス向けの日別行。湿度と天気概況は観測がないため除く。"""
    return [
        [
            str(r.day.day),
            r.weekday_ja,
            _num(r.precip_total),
            _num(r.precip_max_1h),
            _num(r.temp_mean),
            _num(r.temp_max),
            _num(r.temp_min),
            _num(r.wind_mean),
            f"{_num(r.wind_max)}（{_text(r.wind_max_dir)}）",
            f"{_num(r.wind_gust)}（{_text(r.wind_gust_dir)}）",
            _num(r.sunshine),
        ]
        for r in records
    ]


HEADER_AMEDAS = [
    "日",
    "曜",
    "降水量計<br>(mm)",
    "最大1h<br>(mm)",
    "平均気温<br>(℃)",
    "最高<br>(℃)",
    "最低<br>(℃)",
    "平均風速<br>(m/s)",
    "最大風速<br>(m/s)",
    "最大瞬間<br>(m/s)",
    "日照<br>(h)",
]


def _summary_section(summary: MonthlySummary) -> str:
    """代表地点の月間統計。"""
    station = summary.station
    rows = [
        ["月平均気温", f"{_num(summary.temp_mean)} ℃"],
        ["月間最高気温", f"{_num(summary.temp_max)} ℃"],
        ["月間最低気温", f"{_num(summary.temp_min)} ℃"],
        ["月降水量", f"{_num(summary.precip_total)} mm"],
        ["日降水量の最大", f"{_num(summary.precip_max_daily)} mm"],
        ["月平均湿度", f"{_num(summary.humidity_mean, digits=0)} %"],
        ["最大風速", f"{_num(summary.wind_max)} m/s"],
        ["最大瞬間風速", f"{_num(summary.wind_gust_max)} m/s"],
        ["月間日照時間", f"{_num(summary.sunshine_total)} 時間"],
    ]
    counts = [
        ["真夏日（最高 30℃ 以上）", f"{summary.midsummer_days} 日"],
        ["猛暑日（最高 35℃ 以上）", f"{summary.extremely_hot_days} 日"],
        ["熱帯夜（最低 25℃ 以上）", f"{summary.tropical_nights} 日"],
        ["降水日（1mm 以上）", f"{summary.rainy_days} 日"],
        ["大雨日（50mm 以上）", f"{summary.heavy_rain_days} 日"],
    ]
    return "\n\n".join(
        [
            f"### 代表地点（{station.name}）の月間値",
            _table(["項目", "値"], rows),
            "### 日数の集計",
            _table(["区分", "日数"], counts),
        ]
    )


def _prefecture_extremes_section(result: PrefectureSummary) -> str:
    """県内で最も顕著だった値。"""
    rows = [
        ["最高気温", _extreme_cell(result.hottest, "℃")],
        ["最低気温", _extreme_cell(result.coldest, "℃")],
        ["日降水量", _extreme_cell(result.wettest, "mm")],
        ["最大瞬間風速", _extreme_cell(result.windiest, "m/s")],
    ]
    return _table(["項目", "県内で最も大きい（小さい）値"], rows)


def _notable_section(records: list[DailyRecord]) -> str:
    """特筆すべき日の抜粋。"""
    days = notable_days(records)
    if not days:
        return "大雨・猛暑・強風のいずれの基準にも達した日はありませんでした。"
    return "\n".join(
        f"- **{r.day.month}月{r.day.day}日（{r.weekday_ja}）** {describe_day(r)}"
        for r in days
    )


def _daily_narrative_section(records: list[DailyRecord]) -> str:
    """全日分の概況コメント。"""
    return "\n".join(
        f"- **{r.day.day}日（{r.weekday_ja}）** {describe_day(r)}" for r in records
    )


def _cross_section(result: PrefectureSummary) -> str:
    """日ごとに県内で最も顕著だった地点。"""
    rows = [
        [
            f"{d.day.day}",
            _WEEKDAY[d.day.weekday()],
            _extreme_cell_same_day(d.precip, "mm"),
            _extreme_cell_same_day(d.temp_max, "℃"),
            _extreme_cell_same_day(d.temp_min, "℃"),
            _extreme_cell_same_day(d.wind_gust, "m/s"),
        ]
        for d in result.daily_extremes
    ]
    return _table(
        [
            "日",
            "曜",
            "県内最大の日降水量",
            "県内最高気温",
            "県内最低気温",
            "県内最大瞬間風速",
        ],
        rows,
    )


def _notes_section(result: PrefectureSummary) -> str:
    """データの読み方と制約。"""
    amedas_count = sum(1 for s in result.by_station if not s.is_official)
    return f"""\
- 値の「--」は**欠測**または**その項目を観測していない**ことを示します。
- **湿度と天気概況は官署（地方気象台）でのみ観測**されています。本レポートの
  アメダス {amedas_count} 地点にはこれらの列がありません。
- 「熱帯夜」は本来「夜間の最低気温が 25℃ 以上」ですが、日別値からは
  日最低気温で近似しています。
- 月合計・月平均は欠測日を除いて算出しています。欠測がある地点では
  月降水量や月間日照時間が実際より小さくなることがあります。
- 気象庁の品質記号（`)` 準正常値、`]` 資料不足値、`#` 疑わしい値）が付いた値も
  数値として採用しています。記号は `daily.csv` の `flags` 列に残しています。
- 統計値は後日修正されることがあります。取得時点の値である点にご留意ください。
"""


def render_markdown(pref: Prefecture, result: PrefectureSummary) -> str:
    """1 県分のレポートを Markdown で組み立てる。"""
    year, month = result.year, result.month
    stations = list(result.by_station)
    official = [s for s in stations if s.is_official]
    amedas = [s for s in stations if not s.is_official]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    station_list = "、".join(
        f"{s.name}{'（官署）' if s.is_official else ''}" for s in stations
    )

    sections: list[str] = [
        f"# {pref.name} {year}年{month}月 気象概況",
        "\n".join(
            [
                f"- **対象**: {pref.name}",
                f"- **期間**: {year}年{month}月",
                f"- **代表地点**: {result.representative.name}"
                f"（観測所番号 {result.representative.block_no}）",
                f"- **対象地点数**: {len(stations)} 地点"
                f"（官署 {len(official)}、アメダス {len(amedas)}）",
                f"- **出典**: [{SOURCE_NAME}]({SOURCE_URL})",
                f"- **作成日時**: {generated_at}",
            ]
        ),
        "## 1. 月間サマリ",
        _summary_section(result.representative_summary),
        "### 県内で最も顕著だった値",
        _prefecture_extremes_section(result),
        "## 2. 特筆すべき日",
        _notable_section(result.representative_records),
        f"## 3. 日別一覧（{result.representative.name}）",
        _table(HEADER_OFFICIAL, _daily_rows_official(result.representative_records))
        if result.representative.is_official
        else _table(HEADER_AMEDAS, _daily_rows_amedas(result.representative_records)),
        f"## 4. 日別の概況（{result.representative.name}）",
        _daily_narrative_section(result.representative_records),
        "## 5. 県内各地点の日別値",
        f"対象地点: {station_list}",
    ]

    for station in stations:
        if station is result.representative:
            continue
        records = result.by_station[station]
        if not records:
            continue
        heading = f"### {station.name}"
        if station.is_official:
            sections += [heading, _table(HEADER_OFFICIAL, _daily_rows_official(records))]
        else:
            sections += [
                heading,
                "※ アメダスのため湿度・天気概況の観測はありません。",
                _table(HEADER_AMEDAS, _daily_rows_amedas(records)),
            ]

    sections += [
        "## 6. 県内クロス集計（日ごとの県内最大・最小）",
        _cross_section(result),
        "## 7. 注記",
        _notes_section(result),
    ]

    return "\n\n".join(sections) + "\n"


def write_csv(path: Path, result: PrefectureSummary) -> None:
    """全地点・全日の値を 1 枚の CSV にまとめる。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["地点", "観測所番号", "種別", "日付", "曜日"]
    header += [FIELD_LABELS.get(f, f) for f in VALUE_FIELDS]
    header += ["flags"]

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for station, records in result.by_station.items():
            for record in records:
                row: list[object] = [
                    station.name,
                    station.block_no,
                    "官署" if station.is_official else "アメダス",
                    record.day.isoformat(),
                    record.weekday_ja,
                ]
                row += [getattr(record, f) for f in VALUE_FIELDS]
                row.append(
                    ";".join(f"{k}={v}" for k, v in sorted(record.flags.items()))
                )
                writer.writerow(["" if v is None else v for v in row])


def write_report(
    output_dir: Path, pref: Prefecture, result: PrefectureSummary
) -> tuple[Path, Path]:
    """Markdown と CSV を書き出し、そのパスを返す。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    csv_path = output_dir / "daily.csv"
    markdown_path.write_text(render_markdown(pref, result), encoding="utf-8")
    write_csv(csv_path, result)
    return markdown_path, csv_path


def render_index(
    year: int, month: int, entries: list[tuple[Prefecture, PrefectureSummary]]
) -> str:
    """複数県をまとめた一覧ページ。九州全体を俯瞰するための表。"""
    rows = []
    for pref, result in entries:
        summary = result.representative_summary
        rows.append(
            [
                f"[{pref.name}]({pref.slug}/report.md)",
                result.representative.name,
                _num(summary.temp_mean),
                _num(summary.temp_max),
                _num(summary.precip_total),
                str(summary.extremely_hot_days),
                str(summary.tropical_nights),
                str(summary.rainy_days),
                _extreme_cell(result.wettest, "mm"),
            ]
        )
    header = [
        "県",
        "代表地点",
        "月平均気温<br>(℃)",
        "月間最高<br>(℃)",
        "月降水量<br>(mm)",
        "猛暑日",
        "熱帯夜",
        "降水日",
        "県内最大の日降水量",
    ]
    return "\n\n".join(
        [
            f"# {year}年{month}月 気象概況（{len(entries)} 県）",
            f"出典: [{SOURCE_NAME}]({SOURCE_URL})",
            "各県の詳細は県名のリンクから参照してください。",
            _table(header, rows),
        ]
    ) + "\n"
