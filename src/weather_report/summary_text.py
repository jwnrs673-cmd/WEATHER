"""期間の並びから「どんな月だったか」の文章を組み立てる。

数値表とは別に、月全体の性格と月内の切り替わりを日本語で述べる。予報や解説
ではなく、観測値としきい値から機械的に組み立てた記述である。
"""

from __future__ import annotations

from .aggregate import MonthlySummary
from .models import Station
from .spells import Spell

#: 猛暑日がこの割合以上を占める期間は「猛暑が続いた」と述べる。
HOT_SPELL_RATIO = 0.5

#: 期間降水量がこれ以上なら、その雨天期を月の主要因として扱う。
MAJOR_RAIN_MM = 100.0


def _fmt(value: float | None, unit: str, *, digits: int = 1) -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}{unit}"


def describe_spell(spell: Spell) -> str:
    """1 期間を 1 文にする。"""
    head = f"**{spell.label}（{spell.days}日間）**"
    parts: list[str] = []

    if spell.is_wet:
        precip = spell.total("precip_total")
        parts.append(f"期間降水量 {_fmt(precip, 'mm')}")
        heaviest = spell.maximum("precip_total")
        if heaviest is not None:
            parts.append(f"日最大 {_fmt(heaviest, 'mm')}")
        if spell.heavy_rain_days:
            parts.append(f"大雨日 {spell.heavy_rain_days}日")
    else:
        precip = spell.total("precip_total")
        if precip:
            parts.append(f"期間降水量 {_fmt(precip, 'mm')}（まとまった降水なし）")
        else:
            parts.append("降水なし")
        sunshine = spell.total("sunshine")
        if sunshine is not None:
            parts.append(f"日照 {_fmt(sunshine, '時間')}")

    temp_max_mean = spell.mean("temp_max")
    if temp_max_mean is not None:
        parts.append(f"最高気温の平均 {_fmt(temp_max_mean, '℃')}")
    if spell.extremely_hot_days:
        parts.append(f"猛暑日 {spell.extremely_hot_days}日")
    if spell.tropical_nights:
        parts.append(f"熱帯夜 {spell.tropical_nights}日")

    heads = spell.weather_heads()
    if heads:
        parts.append("天気概況は" + "・".join(f"「{h}」" for h in heads) + "が中心")

    return f"{head} {'、'.join(parts)}。"


def _character(spell: Spell) -> str:
    """期間の性格を短い語で表す。総括文の中で使う。"""
    if spell.is_wet:
        precip = spell.total("precip_total") or 0.0
        if precip >= MAJOR_RAIN_MM:
            return "まとまった雨"
        return "ぐずついた天気"
    if spell.days and spell.extremely_hot_days / spell.days >= HOT_SPELL_RATIO:
        return "晴天と猛暑"
    return "晴天"


def overview(
    station: Station,
    summary: MonthlySummary,
    spells: list[Spell],
    year: int,
    month: int,
) -> str:
    """月全体の総括を 1 段落にする。"""
    if not spells:
        return f"{year}年{month}月の{station.name}は、集計できる日別値がありませんでした。"

    sentences: list[str] = []

    # 月の骨格を、期間の並びとして述べる。
    flow = "、".join(f"{s.label}が{_character(s)}" for s in spells)
    sentences.append(f"{year}年{month}月の{station.name}は、{flow}という推移でした。")

    # 月の主役になった雨天期があれば名指しする。
    # 月降水量そのものが少ない月では「集中」と述べても実態を表さないため、
    # まとまった降水があった月に限る。
    wet_spells = [s for s in spells if s.is_wet]
    month_precip = summary.precip_total or 0.0
    biggest = (
        max(wet_spells, key=lambda s: s.total("precip_total") or 0.0)
        if wet_spells
        else None
    )
    biggest_precip = biggest.total("precip_total") if biggest else None
    share = (biggest_precip or 0.0) / month_precip if month_precip else 0.0

    if biggest is not None and month_precip >= MAJOR_RAIN_MM and share >= 0.5:
        sentences.append(
            f"月降水量 {_fmt(summary.precip_total, 'mm')} のうち "
            f"{_fmt(biggest_precip, 'mm')}（{share * 100:.0f}%）が"
            f"{biggest.label}に集中しています。"
        )
    else:
        sentences.append(
            "月を通してまとまった降水はなく、月降水量は "
            f"{_fmt(summary.precip_total, 'mm')} にとどまりました。"
        )

    # 暑さの側面。
    if summary.extremely_hot_days:
        sentences.append(
            f"猛暑日は {summary.extremely_hot_days}日、熱帯夜は "
            f"{summary.tropical_nights}日で、月間最高気温は "
            f"{_fmt(summary.temp_max, '℃')} でした。"
        )
    else:
        sentences.append(
            f"猛暑日はなく、月間最高気温は {_fmt(summary.temp_max, '℃')} でした。"
        )

    return "".join(sentences)


def contrast(
    current_spells: list[Spell],
    previous_spells: list[Spell],
    current_summary: MonthlySummary,
    previous_summary: MonthlySummary,
    current_year: int,
    previous_year: int,
) -> str:
    """2 つの月の性格の違いを述べる。"""
    lines: list[str] = []

    def wet_days(spells: list[Spell]) -> int:
        return sum(s.days for s in spells if s.is_wet)

    current_wet, previous_wet = wet_days(current_spells), wet_days(previous_spells)
    if current_wet != previous_wet:
        more, less = (
            (current_year, previous_year)
            if current_wet > previous_wet
            else (previous_year, current_year)
        )
        lines.append(
            f"- 雨天期の長さは {current_year}年 {current_wet}日 に対し "
            f"{previous_year}年 {previous_wet}日 で、{more}年の方が"
            f"{less}年より長く続きました。"
        )
    else:
        lines.append(f"- 雨天期の長さはどちらも {current_wet}日 で同じでした。")

    current_precip = current_summary.precip_total or 0.0
    previous_precip = previous_summary.precip_total or 0.0
    if previous_precip:
        ratio = current_precip / previous_precip
        lines.append(
            f"- 月降水量は {_fmt(current_precip, 'mm')} と "
            f"{_fmt(previous_precip, 'mm')} で {ratio:.2f} 倍の差があります。"
        )

    hot_diff = current_summary.extremely_hot_days - previous_summary.extremely_hot_days
    if hot_diff:
        direction = "多く" if hot_diff > 0 else "少なく"
        lines.append(
            f"- 猛暑日は {current_year}年 {current_summary.extremely_hot_days}日、"
            f"{previous_year}年 {previous_summary.extremely_hot_days}日 で、"
            f"{current_year}年の方が {abs(hot_diff)}日 {direction}なっています。"
        )
    else:
        lines.append(
            f"- 猛暑日はどちらも {current_summary.extremely_hot_days}日 で同数でした。"
        )

    return "\n".join(lines)
