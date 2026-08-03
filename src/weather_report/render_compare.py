"""前年同月比レポートの Markdown / CSV 出力。

平年値ではなく**特定の 1 年との比較**である点に注意。1 年だけの差は
年々変動の範囲に収まることが多く、傾向を示すものではない。その旨は
注記セクションに常に出す。
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from . import summary_text
from .compare import Delta, Metric, YearComparison, compare_extremes
from .models import FIELD_LABELS, VALUE_FIELDS
from .prefectures import Prefecture
from .render import SOURCE_NAME, SOURCE_URL, _num, _table, _text

_WEEKDAY = ("月", "火", "水", "木", "金", "土", "日")

#: 差がこの値未満なら「ほぼ同じ」として概況文から省く。項目の単位ごとに定める。
NEGLIGIBLE = {"℃": 0.3, "mm": 5.0, "%": 1.0, "時間": 5.0, "m/s": 0.5, "日": 1.0}


def _signed(value: float | None, *, digits: int = 1) -> str:
    """差分のセル。プラスには ``+`` を付け、符号を一目で分かるようにする。

    差がないときに ``+0.0`` と出ると増加のように読めるため ``±`` を使う。
    """
    if value is None:
        return "--"
    if value == 0:
        return f"±{0:.{digits}f}"
    return f"{value:+.{digits}f}"


def _ratio(delta: Delta) -> str:
    """「1.8 倍」形式のセル。前年が 0 なら比を出さない。"""
    if delta.ratio is None:
        if delta.previous == 0 and delta.current not in (None, 0):
            return "前年 0"
        return "--"
    return f"{delta.ratio:.2f} 倍"


def _metric_rows(metrics: list[Metric], *, with_ratio: bool) -> list[list[str]]:
    rows = []
    for metric in metrics:
        row = [
            metric.label + ("〔要注意〕" if metric.delta.is_sparse else ""),
            _num(metric.delta.current, digits=metric.digits),
            _num(metric.delta.previous, digits=metric.digits),
            _signed(metric.delta.diff, digits=metric.digits),
        ]
        if with_ratio:
            row.append(_ratio(metric.delta) if metric.show_ratio else "--")
        rows.append(row)
    return rows


def _overview_section(comparison: YearComparison) -> str:
    header = ["項目", comparison.label_current, comparison.label_previous, "差", "比"]
    return _table(header, _metric_rows(comparison.metrics, with_ratio=True))


def _day_count_section(comparison: YearComparison) -> str:
    header = ["区分", comparison.label_current, comparison.label_previous, "差"]
    return _table(header, _metric_rows(comparison.day_counts, with_ratio=False))


def _segment_section(comparison: YearComparison) -> str:
    """旬ごとの比較表。月合計だけでは見えない月内の偏りを示す。"""
    rows: list[list[str]] = []
    for segment in comparison.segments:
        rows.append(
            [
                segment.name,
                _num(segment.temp_mean.current),
                _num(segment.temp_mean.previous),
                _signed(segment.temp_mean.diff),
                _num(segment.precip_total.current),
                _num(segment.precip_total.previous),
                _signed(segment.precip_total.diff),
                _num(segment.sunshine.current),
                _num(segment.sunshine.previous),
                _signed(segment.sunshine.diff),
            ]
        )
    header = [
        "旬",
        f"平均気温<br>{comparison.current.year}",
        f"平均気温<br>{comparison.previous.year}",
        "差<br>(℃)",
        f"降水量<br>{comparison.current.year}",
        f"降水量<br>{comparison.previous.year}",
        "差<br>(mm)",
        f"日照<br>{comparison.current.year}",
        f"日照<br>{comparison.previous.year}",
        "差<br>(h)",
    ]
    return _table(header, rows)


def _daily_section(comparison: YearComparison) -> str:
    """暦日をそろえた日別対照表。"""
    rows: list[list[str]] = []
    for pair in comparison.daily_pairs:
        cur, prev = pair.current, pair.previous
        temp_diff = (
            round(cur.temp_max - prev.temp_max, 1)
            if cur and prev and cur.temp_max is not None and prev.temp_max is not None
            else None
        )
        precip_diff = (
            round(cur.precip_total - prev.precip_total, 1)
            if cur
            and prev
            and cur.precip_total is not None
            and prev.precip_total is not None
            else None
        )
        rows.append(
            [
                str(pair.day_of_month),
                _num(cur.temp_max if cur else None),
                _num(prev.temp_max if prev else None),
                _signed(temp_diff),
                _num(cur.temp_min if cur else None),
                _num(prev.temp_min if prev else None),
                _num(cur.precip_total if cur else None),
                _num(prev.precip_total if prev else None),
                _signed(precip_diff),
            ]
        )
    header = [
        "日",
        f"最高<br>{comparison.current.year}",
        f"最高<br>{comparison.previous.year}",
        "差<br>(℃)",
        f"最低<br>{comparison.current.year}",
        f"最低<br>{comparison.previous.year}",
        f"降水<br>{comparison.current.year}",
        f"降水<br>{comparison.previous.year}",
        "差<br>(mm)",
    ]
    return _table(header, rows)


def _climate_summary_section(comparison: YearComparison) -> str:
    """両年について「どんな月だったか」を文章で述べる。

    数値表とは別に、月内のどこで天気が切り替わったかを追えるようにする。
    """
    station = comparison.current.representative
    blocks: list[str] = []

    for label, result, spells in (
        (comparison.label_current, comparison.current, comparison.current_spells),
        (comparison.label_previous, comparison.previous, comparison.previous_spells),
    ):
        overview = summary_text.overview(
            station, result.representative_summary, spells, result.year, result.month
        )
        spell_lines = "\n".join(
            f"- {summary_text.describe_spell(spell)}" for spell in spells
        )
        blocks.append(
            "\n\n".join([f"### {label}", overview, spell_lines])
            if spell_lines
            else "\n\n".join([f"### {label}", overview])
        )

    blocks.append(
        "\n\n".join(
            [
                "### 二つの月の違い",
                summary_text.contrast(
                    comparison.current_spells,
                    comparison.previous_spells,
                    comparison.current.representative_summary,
                    comparison.previous.representative_summary,
                    comparison.current.year,
                    comparison.previous.year,
                ),
            ]
        )
    )
    return "\n\n".join(blocks)


def _weather_text_section(comparison: YearComparison) -> str:
    """日別の天気概況を 2 年分並べる。

    天気概況は**官署でのみ観測**しているため、代表地点がアメダスのときは
    表の代わりに理由を出す。
    """
    if not comparison.current.representative.is_official:
        return (
            "代表地点がアメダスのため、天気概況の観測がありません。"
            "（天気概況は官署でのみ観測しています。）"
        )

    rows = [
        [
            str(pair.day_of_month),
            _text(pair.current.weather_day if pair.current else None),
            _text(pair.current.weather_night if pair.current else None),
            _text(pair.previous.weather_day if pair.previous else None),
            _text(pair.previous.weather_night if pair.previous else None),
        ]
        for pair in comparison.daily_pairs
    ]
    header = [
        "日",
        f"{comparison.current.year} 昼",
        f"{comparison.current.year} 夜",
        f"{comparison.previous.year} 昼",
        f"{comparison.previous.year} 夜",
    ]
    return _table(header, rows)


def _station_section(comparison: YearComparison) -> str:
    """両年に共通する地点の月間値を並べる。"""
    rows: list[list[str]] = []
    for entry in comparison.stations:
        cur, prev = entry.current, entry.previous
        temp_diff = (
            round(cur.temp_mean - prev.temp_mean, 1)
            if cur.temp_mean is not None and prev.temp_mean is not None
            else None
        )
        precip_diff = (
            round(cur.precip_total - prev.precip_total, 1)
            if cur.precip_total is not None and prev.precip_total is not None
            else None
        )
        rows.append(
            [
                entry.station.name
                + ("（代表）" if entry.station.block_no
                   == comparison.current.representative.block_no else ""),
                _num(cur.temp_mean),
                _num(prev.temp_mean),
                _signed(temp_diff),
                _num(cur.precip_total),
                _num(prev.precip_total),
                _signed(precip_diff),
                str(cur.extremely_hot_days),
                str(prev.extremely_hot_days),
                _signed(float(cur.extremely_hot_days - prev.extremely_hot_days), digits=0),
            ]
        )
    header = [
        "地点",
        f"平均気温<br>{comparison.current.year}",
        f"平均気温<br>{comparison.previous.year}",
        "差<br>(℃)",
        f"降水量<br>{comparison.current.year}",
        f"降水量<br>{comparison.previous.year}",
        "差<br>(mm)",
        f"猛暑日<br>{comparison.current.year}",
        f"猛暑日<br>{comparison.previous.year}",
        "差",
    ]
    return _table(header, rows)


def _extremes_section(comparison: YearComparison) -> str:
    """県内の極値どうしの比較。地点名と日付も併記する。"""
    items = (
        ("最高気温", comparison.current.hottest, comparison.previous.hottest, "℃"),
        ("最低気温", comparison.current.coldest, comparison.previous.coldest, "℃"),
        ("日降水量", comparison.current.wettest, comparison.previous.wettest, "mm"),
        ("最大瞬間風速", comparison.current.windiest, comparison.previous.windiest, "m/s"),
    )
    rows = []
    for label, cur, prev, unit in items:
        delta = compare_extremes(cur, prev)
        rows.append(
            [
                label,
                f"{_num(cur.value)}{unit}（{cur.label}）" if cur else "--",
                f"{_num(prev.value)}{unit}（{prev.label}）" if prev else "--",
                _signed(delta.diff),
            ]
        )
    header = ["項目", comparison.label_current, comparison.label_previous, "差"]
    return _table(header, rows)


def _headline(metric: Metric) -> str | None:
    """1 項目を 1 文にする。差が小さい項目は ``None`` を返して省く。"""
    diff = metric.delta.diff
    if diff is None:
        return None
    threshold = NEGLIGIBLE.get(metric.unit, 0.0)
    if abs(diff) < threshold:
        return None

    magnitude = f"{abs(diff):.{metric.digits}f}{metric.unit}"
    sentence = (
        f"**{metric.label}**は前年より {magnitude} {metric.direction_word(diff)}"
    )
    if metric.show_ratio and metric.delta.ratio is not None:
        sentence += f"（{metric.delta.ratio:.2f} 倍）"
    return sentence


def _summary_narrative(comparison: YearComparison) -> str:
    """主な差分を箇条書きにする。しきい値未満の項目は落とす。"""
    lines = [
        f"- {sentence}"
        for sentence in (
            _headline(metric)
            for metric in (*comparison.metrics, *comparison.day_counts)
        )
        if sentence
    ]
    if not lines:
        return "月間統計に目立った差はありませんでした。"
    return "\n".join(lines)


def _notes_section(comparison: YearComparison) -> str:
    current_only = [
        s.name
        for s in comparison.current.summaries
        if s.block_no not in {c.station.block_no for c in comparison.stations}
    ]
    previous_only = [
        s.name
        for s in comparison.previous.summaries
        if s.block_no not in {c.station.block_no for c in comparison.stations}
    ]
    lines = [
        "- これは**平年値との比較ではなく、特定の 1 年との比較**です。1 年分の差は"
        "年々変動の範囲に収まることが多く、気候の傾向を示すものではありません。"
        "平年偏差を見たい場合は気象庁の平年値（1991〜2020 年平均）と比較してください。",
        "- 差は「当年 − 前年」です。プラスは当年の方が大きいことを表します。",
        "- 月降水量・月間日照時間は**欠測日を除いた合計**です。片方の年だけ欠測が"
        f"多いと差が過大に出ます。有効観測日数が暦日数の 90% を下回る項目には"
        "「〔要注意〕」を付けています。",
        "- 日別対照表と天気概況は**暦日**でそろえています。曜日は年によって異なります。",
        "- **天気概況は官署（地方気象台）でのみ観測**しています。アメダスにはありません。"
        "また観測値ではなく観測者による記述のため、年による表現のゆれがありえます。",
        "- 「熱帯夜」は日最低気温 25℃ 以上で近似しています。",
        "- 統計値は後日修正されることがあります。取得時点の値です。",
    ]
    if current_only:
        lines.append(
            f"- {comparison.label_previous}に対応する地点がないため比較から除外: "
            f"{'、'.join(current_only)}"
        )
    if previous_only:
        lines.append(
            f"- {comparison.label_current}に対応する地点がないため比較から除外: "
            f"{'、'.join(previous_only)}"
        )
    return "\n".join(lines)


def render_markdown(pref: Prefecture, comparison: YearComparison) -> str:
    """前年同月比レポートを組み立てる。"""
    current, previous = comparison.current, comparison.previous
    station = current.representative
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    sections = [
        f"# {pref.name} {comparison.label_current} 気象概況"
        f"（{comparison.label_previous}との比較）",
        "\n".join(
            [
                f"- **対象**: {pref.name}",
                f"- **比較**: {comparison.label_current} ⇔ {comparison.label_previous}",
                f"- **代表地点**: {station.name}（観測所番号 {station.block_no}）",
                f"- **比較対象地点**: {len(comparison.stations)} 地点"
                "（両年に観測がある地点のみ）",
                f"- **出典**: [{SOURCE_NAME}]({SOURCE_URL})",
                f"- **作成日時**: {generated_at}",
            ]
        ),
        "## 1. 要点",
        _summary_narrative(comparison),
        f"## 2. どんな月だったか（{station.name}）",
        "降水があった日となかった日で月を区切り、期間ごとの性格を述べます。"
        "区切りは日降水量 1mm を境にした便宜的なもので、"
        "気象庁の梅雨入り・梅雨明けの発表とは関係ありません。",
        _climate_summary_section(comparison),
        f"## 3. 月間値の比較（{station.name}）",
        _overview_section(comparison),
        "### 日数の比較",
        _day_count_section(comparison),
        "## 4. 旬別の比較",
        "月合計だけでは月内のどこで差がついたかが分かりません。"
        "上旬・中旬・下旬に分けて示します。",
        _segment_section(comparison),
        "## 5. 県内の極値の比較",
        _extremes_section(comparison),
        "## 6. 地点別の比較",
        _station_section(comparison),
        f"## 7. 日別対照表（{station.name}）",
        _daily_section(comparison),
        f"## 8. 日別の天気概況（{station.name}）",
        _weather_text_section(comparison),
        "## 9. 注記",
        _notes_section(comparison),
    ]
    return "\n\n".join(sections) + "\n"


def write_csv(path: Path, comparison: YearComparison) -> None:
    """月間値の比較を 1 枚の CSV にする。表計算での再利用を想定。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "区分",
                "項目",
                "単位",
                comparison.label_current,
                comparison.label_previous,
                "差",
                "比",
                "観測日数注意",
            ]
        )
        groups = (("月間値", comparison.metrics), ("日数", comparison.day_counts))
        for group, metrics in groups:
            for metric in metrics:
                delta = metric.delta
                # 日数は整数の項目なので 26.0 ではなく 26 と書く。
                cast = int if metric.unit == "日" else float

                def value(number: float | None, cast=cast) -> object:
                    return "" if number is None else cast(number)

                writer.writerow(
                    [
                        group,
                        metric.label,
                        metric.unit,
                        value(delta.current),
                        value(delta.previous),
                        value(delta.diff),
                        ""
                        if not metric.show_ratio or delta.ratio is None
                        else round(delta.ratio, 3),
                        "要注意" if delta.is_sparse else "",
                    ]
                )
        for segment in comparison.segments:
            for label, delta, unit in (
                ("平均気温", segment.temp_mean, "℃"),
                ("降水量", segment.precip_total, "mm"),
                ("日照時間", segment.sunshine, "時間"),
            ):
                writer.writerow(
                    [
                        f"旬別（{segment.name}）",
                        label,
                        unit,
                        "" if delta.current is None else delta.current,
                        "" if delta.previous is None else delta.previous,
                        "" if delta.diff is None else delta.diff,
                        "",
                        "",
                    ]
                )


def write_daily_csv(path: Path, comparison: YearComparison) -> None:
    """両年の日別値を 1 枚の CSV にまとめる。

    県ごとの ``daily.csv`` は対象年しか持たないため、比較対象年の日別値は
    このファイルにしか残らない。表計算で 2 年分を並べられるよう、``年`` と
    ``日`` の列を足して同じ暦日どうしを突き合わせやすくしている。

    地点は両年に共通するものに限らず、取得できたものをすべて出す。
    比較表から外れた地点でも観測値そのものは失いたくないため。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["年", "地点", "観測所番号", "種別", "日付", "日", "曜日"]
    header += [FIELD_LABELS.get(f, f) for f in VALUE_FIELDS]
    header += ["flags"]

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for result in (comparison.current, comparison.previous):
            for station, records in result.by_station.items():
                for record in records:
                    row: list[object] = [
                        result.year,
                        station.name,
                        station.block_no,
                        "官署" if station.is_official else "アメダス",
                        record.day.isoformat(),
                        record.day.day,
                        record.weekday_ja,
                    ]
                    row += [getattr(record, f) for f in VALUE_FIELDS]
                    row.append(
                        ";".join(f"{k}={v}" for k, v in sorted(record.flags.items()))
                    )
                    writer.writerow(["" if v is None else v for v in row])


def write_report(
    output_dir: Path, pref: Prefecture, comparison: YearComparison
) -> tuple[Path, Path, Path]:
    """Markdown と CSV 2 種を書き出し、そのパスを返す。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"compare_{comparison.previous.year}-{comparison.previous.month:02d}"
    markdown_path = output_dir / f"{stem}.md"
    csv_path = output_dir / f"{stem}.csv"
    daily_csv_path = output_dir / f"{stem}_daily.csv"
    markdown_path.write_text(render_markdown(pref, comparison), encoding="utf-8")
    write_csv(csv_path, comparison)
    write_daily_csv(daily_csv_path, comparison)
    return markdown_path, csv_path, daily_csv_path
