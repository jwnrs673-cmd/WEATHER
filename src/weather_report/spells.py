"""月を「雨が続いた期間」「降らなかった期間」に区切る。

月降水量や旬別の集計だけでは「梅雨がいつ明けたか」のような月内の切り替わりが
見えない。日降水量の有無で連続する日をまとめ、期間ごとに性格を記述するための
下ごしらえをする。

区切りは統計的な検定ではなく、単純なしきい値と平滑化による**便宜的なもの**である。
気象庁の梅雨入り・梅雨明けの発表とは無関係で、一致も保証しない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .models import DailyRecord

#: 降水日とみなす日降水量 (mm)。気象庁の「降水日」の定義に合わせる。
WET_THRESHOLD = 1.0

#: この日数未満の期間は、前後の長い方に吸収する。
#: 連続した雨の中の 1 日だけの晴れ間で期間が分断されるのを防ぐ。
MIN_SPELL_DAYS = 3

#: 天気概況の先頭に現れる主な語。長いものから順に照合する（「大雨」を「雨」より先に）。
WEATHER_HEADS: tuple[str, ...] = (
    "快晴",
    "大雨",
    "大雪",
    "みぞれ",
    "霧雨",
    "晴",
    "曇",
    "雨",
    "雪",
    "霧",
)

WET = "wet"
DRY = "dry"


def classify(record: DailyRecord) -> str:
    """1 日を降水の有無で分ける。

    降水量が欠測の日は乾燥期として扱う。降っていない証拠にはならないが、
    欠測だけで期間を区切るよりは前後に吸収させた方が読みやすいため。
    """
    if record.precip_total is None:
        return DRY
    return WET if record.precip_total >= WET_THRESHOLD else DRY


@dataclass
class Spell:
    """降水の有無が同じ状態で続いた期間。"""

    kind: str
    """:data:`WET` か :data:`DRY`。"""

    records: list[DailyRecord]

    @property
    def start(self) -> date:
        return self.records[0].day

    @property
    def end(self) -> date:
        return self.records[-1].day

    @property
    def days(self) -> int:
        return len(self.records)

    @property
    def is_wet(self) -> bool:
        return self.kind == WET

    def _values(self, field: str) -> list[float]:
        return [
            value
            for value in (getattr(r, field) for r in self.records)
            if isinstance(value, (int, float))
        ]

    def total(self, field: str) -> float | None:
        values = self._values(field)
        return round(sum(values), 1) if values else None

    def mean(self, field: str) -> float | None:
        values = self._values(field)
        return round(sum(values) / len(values), 1) if values else None

    def maximum(self, field: str) -> float | None:
        values = self._values(field)
        return max(values) if values else None

    @property
    def extremely_hot_days(self) -> int:
        return sum(1 for r in self.records if r.is_extremely_hot_day)

    @property
    def tropical_nights(self) -> int:
        return sum(1 for r in self.records if r.is_tropical_night)

    @property
    def heavy_rain_days(self) -> int:
        return sum(1 for r in self.records if r.is_heavy_rain_day)

    @property
    def label(self) -> str:
        """「7月1日〜7月6日」形式。1 日だけなら「7月1日」。"""
        if self.days == 1:
            return f"{self.start.month}月{self.start.day}日"
        return (
            f"{self.start.month}月{self.start.day}日〜"
            f"{self.end.month}月{self.end.day}日"
        )

    def weather_heads(self, limit: int = 2) -> list[str]:
        """期間中に多かった天気概況の語を、多い順に返す。

        「大雨時々曇、雷を伴う」のような記述から先頭の語だけを取り出して数える。
        官署以外は天気概況を観測していないため、その場合は空のリストになる。
        """
        counts: dict[str, int] = {}
        for record in self.records:
            head = weather_head(record.weather_day)
            if head:
                counts[head] = counts.get(head, 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return [head for head, _ in ordered[:limit]]


def weather_head(text: str | None) -> str | None:
    """天気概況の先頭の語を取り出す。該当しなければ ``None``。"""
    if not text:
        return None
    stripped = text.strip()
    for head in WEATHER_HEADS:
        if stripped.startswith(head):
            return head
    # 「時々」などで始まる想定外の表記は、最初に現れた語を拾う。
    match = re.search("|".join(WEATHER_HEADS), stripped)
    return match.group(0) if match else None


def _runs(records: list[DailyRecord]) -> list[Spell]:
    """連続する同じ区分をまとめる。"""
    spells: list[Spell] = []
    for record in records:
        kind = classify(record)
        if spells and spells[-1].kind == kind:
            spells[-1].records.append(record)
        else:
            spells.append(Spell(kind=kind, records=[record]))
    return spells


def _absorb_short(spells: list[Spell], min_days: int) -> list[Spell]:
    """短すぎる期間を前後の長い方に吸収する。

    1 日だけの晴れ間で雨天期が分断されると、期間の数ばかり増えて読みにくい。
    先頭・末尾の短い期間は隣が 1 つしかないためそちらに寄せる。
    """
    if len(spells) <= 1:
        return spells

    while True:
        if len(spells) <= 1:
            return spells
        index = next(
            (i for i, s in enumerate(spells) if s.days < min_days),
            None,
        )
        if index is None:
            return spells

        previous = spells[index - 1] if index > 0 else None
        following = spells[index + 1] if index + 1 < len(spells) else None
        if previous is None:
            target = following
        elif following is None:
            target = previous
        else:
            target = previous if previous.days >= following.days else following

        # 端では隣が 1 つしかなく、吸収先の方が短いことがある。
        # その場合は日数の多い側の区分を期間の性格として採る。
        absorbed = spells[index]
        if absorbed.days > target.days:
            target.kind = absorbed.kind

        # 吸収先に合わせて日を並べ直し、隣接する同区分どうしも繋げる。
        target.records.extend(absorbed.records)
        target.records.sort(key=lambda r: r.day)
        spells.pop(index)
        spells = _merge_adjacent(spells)


def _merge_adjacent(spells: list[Spell]) -> list[Spell]:
    """吸収の結果、同じ区分が隣り合ったら 1 つにする。"""
    merged: list[Spell] = []
    for spell in spells:
        if merged and merged[-1].kind == spell.kind:
            merged[-1].records.extend(spell.records)
            merged[-1].records.sort(key=lambda r: r.day)
        else:
            merged.append(spell)
    return merged


def detect(records: list[DailyRecord], *, min_days: int = MIN_SPELL_DAYS) -> list[Spell]:
    """日別値を雨天期・乾燥期の並びに区切る。

    ``min_days`` 未満の期間は前後に吸収するため、返る期間はすべて
    ``min_days`` 日以上になる（月全体が 1 期間になる場合を除く）。
    """
    if not records:
        return []
    ordered = sorted(records, key=lambda r: r.day)
    return _absorb_short(_runs(ordered), min_days)
