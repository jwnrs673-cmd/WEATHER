"""月間統計と県内横断の集計。

欠測 (``None``) は平均・合計から除く。1 日でも欠測があると合計値は過小に
なるため、集計結果には対象日数を持たせ、レポート側で注記できるようにする。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .models import DailyRecord, Station


@dataclass
class Extreme:
    """県内で最も大きい（小さい）値と、それを記録した地点・日。"""

    value: float
    station: Station
    day: date

    @property
    def label(self) -> str:
        """「35.4℃（佐賀・7月20日）」のような表示用の断片。"""
        return f"{self.station.name}・{self.day.month}月{self.day.day}日"


@dataclass
class MonthlySummary:
    """1 地点・1 か月分の統計。"""

    station: Station
    records: list[DailyRecord]

    precip_total: float | None = None
    """月降水量 (mm)。"""
    precip_max_daily: float | None = None
    """日降水量の最大 (mm)。"""
    temp_mean: float | None = None
    """月平均気温 (℃)。"""
    temp_max: float | None = None
    """月間の最高気温 (℃)。"""
    temp_min: float | None = None
    """月間の最低気温 (℃)。"""
    humidity_mean: float | None = None
    """月平均湿度 (%)。官署のみ。"""
    wind_max: float | None = None
    """月間の最大風速 (m/s)。"""
    wind_gust_max: float | None = None
    """月間の最大瞬間風速 (m/s)。"""
    sunshine_total: float | None = None
    """月間日照時間 (時間)。"""

    midsummer_days: int = 0
    """真夏日（最高 30℃ 以上）の日数。"""
    extremely_hot_days: int = 0
    """猛暑日（最高 35℃ 以上）の日数。"""
    tropical_nights: int = 0
    """熱帯夜（最低 25℃ 以上）の日数。"""
    rainy_days: int = 0
    """降水日（1mm 以上）の日数。"""
    heavy_rain_days: int = 0
    """大雨日（50mm 以上）の日数。"""

    observed_days: dict[str, int] = None  # type: ignore[assignment]
    """項目ごとの有効な観測日数。欠測の多寡を注記するために持つ。"""


def _values(records: list[DailyRecord], field: str) -> list[float]:
    """欠測を除いた数値の並びを返す。"""
    return [
        value
        for value in (getattr(r, field) for r in records)
        if isinstance(value, (int, float))
    ]


def _sum(records: list[DailyRecord], field: str) -> float | None:
    values = _values(records, field)
    return round(sum(values), 1) if values else None


def _mean(records: list[DailyRecord], field: str) -> float | None:
    values = _values(records, field)
    return round(sum(values) / len(values), 1) if values else None


def _max(records: list[DailyRecord], field: str) -> float | None:
    values = _values(records, field)
    return max(values) if values else None


def _min(records: list[DailyRecord], field: str) -> float | None:
    values = _values(records, field)
    return min(values) if values else None


def summarize(station: Station, records: list[DailyRecord]) -> MonthlySummary:
    """1 地点分の月間統計を作る。"""
    tracked = (
        "precip_total",
        "temp_mean",
        "temp_max",
        "temp_min",
        "humidity_mean",
        "wind_mean",
        "sunshine",
    )
    return MonthlySummary(
        station=station,
        records=records,
        precip_total=_sum(records, "precip_total"),
        precip_max_daily=_max(records, "precip_total"),
        temp_mean=_mean(records, "temp_mean"),
        temp_max=_max(records, "temp_max"),
        temp_min=_min(records, "temp_min"),
        humidity_mean=_mean(records, "humidity_mean"),
        wind_max=_max(records, "wind_max"),
        wind_gust_max=_max(records, "wind_gust"),
        sunshine_total=_sum(records, "sunshine"),
        midsummer_days=sum(1 for r in records if r.is_midsummer_day),
        extremely_hot_days=sum(1 for r in records if r.is_extremely_hot_day),
        tropical_nights=sum(1 for r in records if r.is_tropical_night),
        rainy_days=sum(1 for r in records if r.is_rainy_day),
        heavy_rain_days=sum(1 for r in records if r.is_heavy_rain_day),
        observed_days={f: len(_values(records, f)) for f in tracked},
    )


def _extreme(
    by_station: dict[Station, list[DailyRecord]],
    field: str,
    *,
    largest: bool = True,
) -> Extreme | None:
    """県内全地点・全日から最大（最小）の 1 点を選ぶ。"""
    best: Extreme | None = None
    for station, records in by_station.items():
        for record in records:
            value = getattr(record, field)
            if not isinstance(value, (int, float)):
                continue
            if (
                best is None
                or (largest and value > best.value)
                or (not largest and value < best.value)
            ):
                best = Extreme(value=float(value), station=station, day=record.day)
    return best


@dataclass
class DailyPrefectureExtremes:
    """ある 1 日について、県内で最も顕著だった地点。"""

    day: date
    precip: Extreme | None = None
    temp_max: Extreme | None = None
    temp_min: Extreme | None = None
    wind_gust: Extreme | None = None


def daily_extremes(
    by_station: dict[Station, list[DailyRecord]],
) -> list[DailyPrefectureExtremes]:
    """日ごとに県内の最大降水量・最高気温・最低気温・最大瞬間風速を求める。"""
    days = sorted({r.day for records in by_station.values() for r in records})
    result: list[DailyPrefectureExtremes] = []
    for day in days:
        one_day = {
            station: [r for r in records if r.day == day]
            for station, records in by_station.items()
        }
        result.append(
            DailyPrefectureExtremes(
                day=day,
                precip=_extreme(one_day, "precip_total"),
                temp_max=_extreme(one_day, "temp_max"),
                temp_min=_extreme(one_day, "temp_min", largest=False),
                wind_gust=_extreme(one_day, "wind_gust"),
            )
        )
    return result


@dataclass
class PrefectureSummary:
    """1 県・1 か月分の集計結果。レポート生成の入力になる。"""

    year: int
    month: int
    representative: Station
    by_station: dict[Station, list[DailyRecord]]
    summaries: dict[Station, MonthlySummary]
    daily_extremes: list[DailyPrefectureExtremes]

    hottest: Extreme | None = None
    """県内の最高気温。"""
    coldest: Extreme | None = None
    """県内の最低気温。"""
    wettest: Extreme | None = None
    """県内の日降水量の最大。"""
    windiest: Extreme | None = None
    """県内の最大瞬間風速。"""

    @property
    def representative_summary(self) -> MonthlySummary:
        """代表地点の月間統計。"""
        return self.summaries[self.representative]

    @property
    def representative_records(self) -> list[DailyRecord]:
        """代表地点の日別値。メイン表に使う。"""
        return self.by_station[self.representative]


def build(
    year: int,
    month: int,
    representative_station: Station,
    by_station: dict[Station, list[DailyRecord]],
) -> PrefectureSummary:
    """県単位の集計をまとめる。"""
    return PrefectureSummary(
        year=year,
        month=month,
        representative=representative_station,
        by_station=by_station,
        summaries={s: summarize(s, r) for s, r in by_station.items()},
        daily_extremes=daily_extremes(by_station),
        hottest=_extreme(by_station, "temp_max"),
        coldest=_extreme(by_station, "temp_min", largest=False),
        wettest=_extreme(by_station, "precip_total"),
        windiest=_extreme(by_station, "wind_gust"),
    )
