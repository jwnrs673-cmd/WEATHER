"""観測地点と日別観測値のデータ構造。

気象庁の日別値ページには 2 系統ある。

``daily_s1``
    地方気象台などの「官署」。気圧・湿度・天気概況まで揃う。
``daily_a1``
    アメダス。降水量・気温・風・日照のみで、**湿度と天気概況は観測していない**。

:class:`DailyRecord` は両方を 1 つの型で表し、観測していない項目は ``None`` にする。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date

#: 官署（地上気象観測）を表す種別コード。気象庁ページの ``viewPoint('s', ...)`` に対応。
KIND_STATION = "s"

#: アメダスを表す種別コード。``viewPoint('a', ...)`` に対応。
KIND_AMEDAS = "a"

_WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")


@dataclass(frozen=True)
class Station:
    """1 観測地点。"""

    prec_no: int
    """府県番号。"""

    block_no: str
    """観測所番号。官署は 5 桁（例: ``47813``）、アメダスは 4 桁（例: ``0851``）。"""

    name: str
    """地点名（例: 「佐賀」「伊万里」）。"""

    kind: str
    """:data:`KIND_STATION` か :data:`KIND_AMEDAS`。"""

    @property
    def is_official(self) -> bool:
        """官署なら ``True``。湿度と天気概況が取れるかどうかの判定に使う。"""
        return self.kind == KIND_STATION

    @property
    def observes_humidity(self) -> bool:
        """湿度を観測している地点なら ``True``。アメダスは観測していない。"""
        return self.is_official


@dataclass
class DailyRecord:
    """ある地点・ある 1 日の観測値。

    欠測・未観測はすべて ``None``。単位は気象庁の表記に従う
    （降水量・降雪・積雪は mm または cm、気温は ℃、風速は m/s、日照は時間）。
    """

    station: Station
    day: date

    # 気圧（官署のみ）
    pressure_local: float | None = None
    """現地気圧の日平均 (hPa)。"""
    pressure_sea: float | None = None
    """海面気圧の日平均 (hPa)。"""

    # 降水量
    precip_total: float | None = None
    """日降水量の合計 (mm)。"""
    precip_max_1h: float | None = None
    """最大 1 時間降水量 (mm)。"""
    precip_max_10min: float | None = None
    """最大 10 分間降水量 (mm)。"""

    # 気温
    temp_mean: float | None = None
    """日平均気温 (℃)。"""
    temp_max: float | None = None
    """日最高気温 (℃)。"""
    temp_min: float | None = None
    """日最低気温 (℃)。"""

    # 湿度（官署のみ）
    humidity_mean: float | None = None
    """日平均相対湿度 (%)。"""
    humidity_min: float | None = None
    """日最小相対湿度 (%)。"""

    # 風
    wind_mean: float | None = None
    """日平均風速 (m/s)。"""
    wind_max: float | None = None
    """最大風速 (m/s)。"""
    wind_max_dir: str | None = None
    """最大風速時の風向（例: 「南南西」）。"""
    wind_gust: float | None = None
    """最大瞬間風速 (m/s)。"""
    wind_gust_dir: str | None = None
    """最大瞬間風速時の風向。"""
    wind_prevailing_dir: str | None = None
    """最多風向。アメダスの表にのみ存在する。"""

    # 日照・雪
    sunshine: float | None = None
    """日照時間 (時間)。"""
    snowfall: float | None = None
    """降雪の日合計 (cm)。"""
    snow_depth: float | None = None
    """最深積雪 (cm)。"""

    # 天気概況（官署のみ）
    weather_day: str | None = None
    """昼（06:00〜18:00）の天気概況。"""
    weather_night: str | None = None
    """夜（18:00〜翌 06:00）の天気概況。"""

    flags: dict[str, str] = field(default_factory=dict)
    """品質記号。値が正常でなかった項目名 → 記号（``)`` ``]`` ``#`` ``×`` など）。"""

    @property
    def weekday_ja(self) -> str:
        """曜日の 1 文字表記。"""
        return _WEEKDAY_JA[self.day.weekday()]

    @property
    def is_midsummer_day(self) -> bool:
        """真夏日（最高気温 30℃ 以上）。"""
        return self.temp_max is not None and self.temp_max >= 30.0

    @property
    def is_extremely_hot_day(self) -> bool:
        """猛暑日（最高気温 35℃ 以上）。"""
        return self.temp_max is not None and self.temp_max >= 35.0

    @property
    def is_tropical_night(self) -> bool:
        """熱帯夜（最低気温 25℃ 以上）。

        気象庁の正式な定義は「夜間の最低気温が 25℃ 以上」だが、日別値からは
        日最低気温で近似する。統計値としては一般的な扱い。
        """
        return self.temp_min is not None and self.temp_min >= 25.0

    @property
    def is_rainy_day(self) -> bool:
        """降水日（日降水量 1.0mm 以上）。"""
        return self.precip_total is not None and self.precip_total >= 1.0

    @property
    def is_heavy_rain_day(self) -> bool:
        """大雨日（日降水量 50mm 以上）。"""
        return self.precip_total is not None and self.precip_total >= 50.0


#: CSV 出力時の列順。``station`` と ``day`` は別途先頭に置く。
VALUE_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(DailyRecord) if f.name not in ("station", "day", "flags")
)

#: 列名 → 日本語ラベル。CSV と表の見出しに使う。
FIELD_LABELS: dict[str, str] = {
    "pressure_local": "現地気圧(hPa)",
    "pressure_sea": "海面気圧(hPa)",
    "precip_total": "降水量合計(mm)",
    "precip_max_1h": "最大1時間降水量(mm)",
    "precip_max_10min": "最大10分間降水量(mm)",
    "temp_mean": "平均気温(℃)",
    "temp_max": "最高気温(℃)",
    "temp_min": "最低気温(℃)",
    "humidity_mean": "平均湿度(%)",
    "humidity_min": "最小湿度(%)",
    "wind_mean": "平均風速(m/s)",
    "wind_max": "最大風速(m/s)",
    "wind_max_dir": "最大風速の風向",
    "wind_gust": "最大瞬間風速(m/s)",
    "wind_gust_dir": "最大瞬間風速の風向",
    "wind_prevailing_dir": "最多風向",
    "sunshine": "日照時間(h)",
    "snowfall": "降雪合計(cm)",
    "snow_depth": "最深積雪(cm)",
    "weather_day": "天気概況(昼)",
    "weather_night": "天気概況(夜)",
}
