"""日別の概況コメントを組み立てる。

観測値からしきい値で機械的に文を作る。予報や解説ではなく、
数値を日本語に言い換えたものと位置づける。しきい値は気象庁の用語
（真夏日・猛暑日・熱帯夜・大雨）と注意報のおおよその目安に合わせている。
"""

from __future__ import annotations

from .models import DailyRecord

#: 日降水量 (mm) → 表現。大きいものから順に判定する。
PRECIP_LEVELS: tuple[tuple[float, str], ...] = (
    (200.0, "記録的な大雨"),
    (100.0, "非常に激しい雨"),
    (50.0, "大雨"),
    (20.0, "まとまった雨"),
    (5.0, "雨"),
    (1.0, "弱い雨"),
    (0.1, "わずかな降水"),
)

#: 最大 1 時間降水量 (mm) → 表現。気象庁の雨の強さの表現に合わせる。
HOURLY_LEVELS: tuple[tuple[float, str], ...] = (
    (80.0, "猛烈な雨"),
    (50.0, "非常に激しい雨"),
    (30.0, "激しい雨"),
    (20.0, "強い雨"),
)

#: 最大瞬間風速 (m/s) → 表現。
GUST_LEVELS: tuple[tuple[float, str], ...] = (
    (30.0, "暴風"),
    (20.0, "非常に強い風"),
    (15.0, "強い風"),
)


def _level(value: float | None, levels: tuple[tuple[float, str], ...]) -> str | None:
    """しきい値表から該当する表現を返す。"""
    if value is None:
        return None
    for threshold, label in levels:
        if value >= threshold:
            return label
    return None


def _fmt(value: float | None, unit: str, *, digits: int = 1) -> str:
    """欠測を「--」にした数値表記。"""
    if value is None:
        return "--"
    return f"{value:.{digits}f}{unit}"


def describe_temperature(record: DailyRecord) -> str | None:
    """気温に関する一文。該当がなければ ``None``。"""
    parts: list[str] = []
    if record.is_extremely_hot_day:
        parts.append(f"猛暑日（最高 {_fmt(record.temp_max, '℃')}）")
    elif record.is_midsummer_day:
        parts.append(f"真夏日（最高 {_fmt(record.temp_max, '℃')}）")
    if record.is_tropical_night:
        parts.append(f"熱帯夜（最低 {_fmt(record.temp_min, '℃')}）")
    return "、".join(parts) if parts else None


def describe_precipitation(record: DailyRecord) -> str | None:
    """降水に関する一文。降水がなかった日は ``None``。"""
    if record.precip_total is None or record.precip_total < 0.1:
        return None

    label = _level(record.precip_total, PRECIP_LEVELS) or "降水"
    text = f"{label}（日降水量 {_fmt(record.precip_total, 'mm')}"

    hourly = _level(record.precip_max_1h, HOURLY_LEVELS)
    if hourly:
        text += f"、最大 1 時間 {_fmt(record.precip_max_1h, 'mm')} の{hourly}"
    elif record.precip_max_1h:
        text += f"、最大 1 時間 {_fmt(record.precip_max_1h, 'mm')}"
    return text + "）"


def describe_wind(record: DailyRecord) -> str | None:
    """風に関する一文。強風でなければ ``None``。"""
    label = _level(record.wind_gust, GUST_LEVELS)
    if not label:
        return None
    direction = f"{record.wind_gust_dir}の" if record.wind_gust_dir else ""
    return f"{direction}{label}（最大瞬間 {_fmt(record.wind_gust, 'm/s')}）"


def describe_humidity(record: DailyRecord) -> str | None:
    """湿度に関する一文。特筆すべき値でなければ ``None``。"""
    if record.humidity_mean is None:
        return None
    if record.humidity_mean >= 90:
        return f"非常に多湿（平均湿度 {_fmt(record.humidity_mean, '%', digits=0)}）"
    if record.humidity_min is not None and record.humidity_min <= 30:
        return f"空気が乾燥（最小湿度 {_fmt(record.humidity_min, '%', digits=0)}）"
    return None


def describe_day(record: DailyRecord) -> str:
    """1 日分の概況コメントを組み立てる。

    天気概況（官署のみ）があれば先頭に置き、続けて数値から導いた注記を並べる。
    特筆すべきことがなければ「大きな特徴なし」とする。
    """
    parts: list[str] = []
    if record.weather_day:
        parts.append(record.weather_day)

    for describe in (
        describe_precipitation,
        describe_temperature,
        describe_wind,
        describe_humidity,
    ):
        text = describe(record)
        if text:
            parts.append(text)

    if not parts:
        return "大きな特徴なし"
    return "／".join(parts)


def notable_days(records: list[DailyRecord], *, limit: int = 5) -> list[DailyRecord]:
    """特筆すべき日を目立つ順に選ぶ。

    大雨・猛暑・強風のいずれかに該当する日を、影響の大きさの目安で並べる。
    """

    def score(record: DailyRecord) -> float:
        value = 0.0
        if record.precip_total:
            value += record.precip_total
        if record.temp_max and record.temp_max >= 35.0:
            value += (record.temp_max - 35.0) * 20.0
        if record.wind_gust and record.wind_gust >= 15.0:
            value += (record.wind_gust - 15.0) * 5.0
        return value

    candidates = [
        r
        for r in records
        if r.is_heavy_rain_day
        or r.is_extremely_hot_day
        or (r.wind_gust is not None and r.wind_gust >= 15.0)
    ]
    candidates.sort(key=score, reverse=True)
    return candidates[:limit]
