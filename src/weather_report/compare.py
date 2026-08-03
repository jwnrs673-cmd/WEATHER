"""2 つの月を突き合わせて差分を出す。前年同月比を想定している。

比較は**代表地点どうし**を軸にする。県内の地点構成は年によって変わりうるため、
地点別の比較は観測所番号 (``block_no``) が両年に存在するものだけを対象にする。

欠測の扱いには注意がいる。月降水量や月間日照時間は欠測日を除いた合計なので、
片方の年だけ欠測が多いと、実際には差がなくても差があるように見える。
そのため :class:`Delta` は値だけでなく**両年の有効観測日数**も持ち、
レポート側で警告を出せるようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .aggregate import Extreme, MonthlySummary, PrefectureSummary
from .models import DailyRecord, Station

#: 旬の区切り。(名称, 開始日, 終了日) で、下旬は月末まで。
SEGMENTS: tuple[tuple[str, int, int], ...] = (
    ("上旬", 1, 10),
    ("中旬", 11, 20),
    ("下旬", 21, 31),
)

#: 有効観測日数がこの割合を下回ったら、合計値の比較に注意を促す。
COVERAGE_WARN_RATIO = 0.9


@dataclass(frozen=True)
class Delta:
    """ある項目についての 2 年分の値と、その差。

    ``current`` が当年、``previous`` が比較対象年。どちらかが欠測なら
    :attr:`diff` と :attr:`ratio` は ``None`` になる。
    """

    current: float | None
    previous: float | None
    observed_current: int | None = None
    """当年の有効観測日数。合計値の項目でのみ意味を持つ。"""
    observed_previous: int | None = None
    """比較対象年の有効観測日数。"""
    days_current: int = 0
    """当年の暦日数。:attr:`is_sparse` の判定に使う。"""
    days_previous: int = 0
    """比較対象年の暦日数。"""

    @property
    def diff(self) -> float | None:
        """当年 − 前年。片方でも欠測なら ``None``。"""
        if self.current is None or self.previous is None:
            return None
        return round(self.current - self.previous, 1)

    @property
    def ratio(self) -> float | None:
        """前年を 1.0 としたときの当年の比。前年が 0 のときは ``None``。

        降水量のように 0 になりうる項目があるため、0 除算を避けている。
        """
        if self.current is None or self.previous is None or self.previous == 0:
            return None
        return self.current / self.previous

    @property
    def is_sparse(self) -> bool:
        """どちらかの年の観測日数が不足していれば ``True``。"""
        for observed, total in (
            (self.observed_current, self.days_current),
            (self.observed_previous, self.days_previous),
        ):
            if observed is not None and total and observed < total * COVERAGE_WARN_RATIO:
                return True
        return False


#: 差の向きを日本語にするときの語。項目の性質に合わせて使い分ける。
#: 「湿度が多い」「風速が少ない」といった不自然な文を避けるため。
DIRECTION_WORDS: dict[str, tuple[str, str]] = {
    "high_low": ("高い", "低い"),  # 気温・湿度
    "more_less": ("多い", "少ない"),  # 降水量・日照時間・日数
    "strong_weak": ("強い", "弱い"),  # 風速
}


@dataclass(frozen=True)
class Metric:
    """レポートに 1 行として並ぶ比較項目。"""

    label: str
    unit: str
    delta: Delta
    digits: int = 1
    show_ratio: bool = False
    """降水量・日照のように「前年の何倍か」が意味を持つ項目で ``True``。"""

    direction: str = "more_less"
    """差の向きの言い回し。:data:`DIRECTION_WORDS` のキー。"""

    def direction_word(self, diff: float) -> str:
        """差の符号に応じた「高い／低い」などの語を返す。"""
        higher, lower = DIRECTION_WORDS[self.direction]
        return higher if diff > 0 else lower


@dataclass
class SegmentComparison:
    """旬（上旬・中旬・下旬）ごとの比較。"""

    name: str
    temp_mean: Delta
    precip_total: Delta
    sunshine: Delta


@dataclass
class DailyPair:
    """同じ日付（月内の同じ日）どうしの突き合わせ。

    曜日は年で変わるため、比較はあくまで暦日で行う。
    """

    day_of_month: int
    current: DailyRecord | None
    previous: DailyRecord | None


@dataclass
class StationComparison:
    """1 地点の 2 年分の月間統計。"""

    station: Station
    current: MonthlySummary
    previous: MonthlySummary


@dataclass
class YearComparison:
    """1 県・同じ月の 2 年分をまとめた比較結果。"""

    current: PrefectureSummary
    previous: PrefectureSummary
    metrics: list[Metric]
    day_counts: list[Metric]
    segments: list[SegmentComparison]
    daily_pairs: list[DailyPair]
    stations: list[StationComparison]

    @property
    def label_current(self) -> str:
        return f"{self.current.year}年{self.current.month}月"

    @property
    def label_previous(self) -> str:
        return f"{self.previous.year}年{self.previous.month}月"


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _values(records: list[DailyRecord], field: str) -> list[float]:
    return [
        value
        for value in (getattr(r, field) for r in records)
        if isinstance(value, (int, float))
    ]


def _mean(records: list[DailyRecord], field: str) -> float | None:
    values = _values(records, field)
    return round(sum(values) / len(values), 1) if values else None


def _sum(records: list[DailyRecord], field: str) -> float | None:
    values = _values(records, field)
    return round(sum(values), 1) if values else None


def _delta(
    current: float | None,
    previous: float | None,
    *,
    observed: tuple[int, int] | None = None,
    days: tuple[int, int] = (0, 0),
) -> Delta:
    return Delta(
        current=current,
        previous=previous,
        observed_current=observed[0] if observed else None,
        observed_previous=observed[1] if observed else None,
        days_current=days[0],
        days_previous=days[1],
    )


def _build_metrics(
    current: MonthlySummary,
    previous: MonthlySummary,
    days: tuple[int, int],
) -> list[Metric]:
    """代表地点の月間値を項目ごとに比較する。"""

    def observed(field: str) -> tuple[int, int]:
        return (
            (current.observed_days or {}).get(field, 0),
            (previous.observed_days or {}).get(field, 0),
        )

    return [
        Metric(
            "月平均気温",
            "℃",
            _delta(
                current.temp_mean,
                previous.temp_mean,
                observed=observed("temp_mean"),
                days=days,
            ),
            direction="high_low",
        ),
        Metric(
            "日最高気温の平均",
            "℃",
            _delta(
                _mean(current.records, "temp_max"),
                _mean(previous.records, "temp_max"),
                observed=observed("temp_max"),
                days=days,
            ),
            direction="high_low",
        ),
        Metric(
            "日最低気温の平均",
            "℃",
            _delta(
                _mean(current.records, "temp_min"),
                _mean(previous.records, "temp_min"),
                observed=observed("temp_min"),
                days=days,
            ),
            direction="high_low",
        ),
        Metric(
            "月間最高気温",
            "℃",
            _delta(current.temp_max, previous.temp_max, days=days),
            direction="high_low",
        ),
        Metric(
            "月間最低気温",
            "℃",
            _delta(current.temp_min, previous.temp_min, days=days),
            direction="high_low",
        ),
        Metric(
            "月降水量",
            "mm",
            _delta(
                current.precip_total,
                previous.precip_total,
                observed=observed("precip_total"),
                days=days,
            ),
            show_ratio=True,
        ),
        Metric(
            "日降水量の最大",
            "mm",
            _delta(current.precip_max_daily, previous.precip_max_daily, days=days),
            show_ratio=True,
        ),
        Metric(
            "月平均湿度",
            "%",
            _delta(
                current.humidity_mean,
                previous.humidity_mean,
                observed=observed("humidity_mean"),
                days=days,
            ),
            digits=0,
            direction="high_low",
        ),
        Metric(
            "月間日照時間",
            "時間",
            _delta(
                current.sunshine_total,
                previous.sunshine_total,
                observed=observed("sunshine"),
                days=days,
            ),
            show_ratio=True,
        ),
        Metric(
            "最大風速",
            "m/s",
            _delta(current.wind_max, previous.wind_max, days=days),
            direction="strong_weak",
        ),
        Metric(
            "最大瞬間風速",
            "m/s",
            _delta(current.wind_gust_max, previous.wind_gust_max, days=days),
            direction="strong_weak",
        ),
    ]


def _build_day_counts(
    current: MonthlySummary, previous: MonthlySummary, days: tuple[int, int]
) -> list[Metric]:
    """真夏日・猛暑日などの日数を比較する。"""
    items = (
        ("真夏日（最高 30℃ 以上）", "midsummer_days"),
        ("猛暑日（最高 35℃ 以上）", "extremely_hot_days"),
        ("熱帯夜（最低 25℃ 以上）", "tropical_nights"),
        ("降水日（1mm 以上）", "rainy_days"),
        ("大雨日（50mm 以上）", "heavy_rain_days"),
    )
    return [
        Metric(
            label,
            "日",
            _delta(
                float(getattr(current, field)), float(getattr(previous, field)), days=days
            ),
            digits=0,
        )
        for label, field in items
    ]


def _segment_records(records: list[DailyRecord], start: int, end: int) -> list[DailyRecord]:
    return [r for r in records if start <= r.day.day <= end]


def _build_segments(
    current: MonthlySummary, previous: MonthlySummary, days: tuple[int, int]
) -> list[SegmentComparison]:
    """月内を上旬・中旬・下旬に割って比較する。

    月降水量だけでは「いつ降ったか」が分からないため、月の中の分布を粗く見る。
    """
    result: list[SegmentComparison] = []
    for name, start, end in SEGMENTS:
        cur = _segment_records(current.records, start, end)
        prev = _segment_records(previous.records, start, end)
        result.append(
            SegmentComparison(
                name=name,
                temp_mean=_delta(_mean(cur, "temp_mean"), _mean(prev, "temp_mean"), days=days),
                precip_total=_delta(
                    _sum(cur, "precip_total"), _sum(prev, "precip_total"), days=days
                ),
                sunshine=_delta(_sum(cur, "sunshine"), _sum(prev, "sunshine"), days=days),
            )
        )
    return result


def _build_daily_pairs(
    current: list[DailyRecord], previous: list[DailyRecord]
) -> list[DailyPair]:
    """暦日をキーに 2 年分の日別値を並べる。"""
    by_day_current = {r.day.day: r for r in current}
    by_day_previous = {r.day.day: r for r in previous}
    all_days = sorted(set(by_day_current) | set(by_day_previous))
    return [
        DailyPair(
            day_of_month=day,
            current=by_day_current.get(day),
            previous=by_day_previous.get(day),
        )
        for day in all_days
    ]


def _build_stations(
    current: PrefectureSummary, previous: PrefectureSummary
) -> list[StationComparison]:
    """両年に存在する地点だけを突き合わせる。

    地点構成は年で変わりうるので、観測所番号で照合する。片方にしかない地点は
    比較のしようがないため落とす（その旨はレポートの注記に出す）。
    """
    previous_by_block = {s.block_no: s for s in previous.summaries}
    result: list[StationComparison] = []
    for station, summary in current.summaries.items():
        counterpart = previous_by_block.get(station.block_no)
        if counterpart is None:
            continue
        result.append(
            StationComparison(
                station=station,
                current=summary,
                previous=previous.summaries[counterpart],
            )
        )
    # 代表地点を先頭に置く。
    result.sort(key=lambda c: c.station.block_no != current.representative.block_no)
    return result


def compare_extremes(
    current: Extreme | None, previous: Extreme | None
) -> Delta:
    """県内の極値どうしを比較する。"""
    return _delta(
        current.value if current else None,
        previous.value if previous else None,
    )


def build(current: PrefectureSummary, previous: PrefectureSummary) -> YearComparison:
    """2 つの :class:`~weather_report.aggregate.PrefectureSummary` を比較する。

    月が異なる組み合わせでも動くが、想定しているのは同じ月の別の年
    （前年同月比）である。
    """
    days = (
        _days_in_month(current.year, current.month),
        _days_in_month(previous.year, previous.month),
    )
    current_summary = current.representative_summary
    previous_summary = previous.representative_summary

    return YearComparison(
        current=current,
        previous=previous,
        metrics=_build_metrics(current_summary, previous_summary, days),
        day_counts=_build_day_counts(current_summary, previous_summary, days),
        segments=_build_segments(current_summary, previous_summary, days),
        daily_pairs=_build_daily_pairs(
            current.representative_records, previous.representative_records
        ),
        stations=_build_stations(current, previous),
    )
