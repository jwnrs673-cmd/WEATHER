"""気象庁の日別値ページ (HTML) を :class:`DailyRecord` に変換する。

気象庁の表の値には品質記号が付く。意味は以下のとおりで、
:func:`parse_number` がこれを解釈する。

======  ==========================================================
記号    意味
======  ==========================================================
``)``   準正常値。統計値を求める際に許容範囲内で資料が欠けている
``]``   資料不足値。欠測した回数が許容範囲を超えている
``#``   値が疑わしい、または合計・平均の対象資料が不足している
``--``  現象がなかった（降水量・降雪などは 0 として扱う）
``×``   欠測
（空欄） その項目を観測していない
======  ==========================================================

``--`` は「観測はしていたが現象が起きなかった」なので、降水量や降雪では
0 に、それ以外では ``None`` にする。``×`` と空欄はいずれも ``None``。
記号が付いた値は数値として採用したうえで、記号を
:attr:`DailyRecord.flags` に残す。
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from .models import KIND_STATION, DailyRecord, Station

logger = logging.getLogger(__name__)

#: 欠測・未観測を表すトークン。いずれも ``None`` になる。
MISSING_TOKENS = frozenset({"", "×", "✕", "x", "X", "///", "//", "＃", "-"})

#: 「現象がなかった」ことを表すトークン。
NO_PHENOMENON_TOKENS = frozenset({"--", "－－", "ーー", "―――"})

#: 値の末尾に付きうる品質記号。
QUALITY_SUFFIXES = ")]#*）〕"

#: 「現象なし」を 0 として扱う項目。積算量なので 0 が正しい。
ACCUMULATION_FIELDS = frozenset(
    {
        "precip_total",
        "precip_max_1h",
        "precip_max_10min",
        "sunshine",
        "snowfall",
        "snow_depth",
    }
)

#: 文字列としてそのまま保持する項目（風向・天気概況）。
TEXT_FIELDS = frozenset(
    {
        "wind_max_dir",
        "wind_gust_dir",
        "wind_prevailing_dir",
        "weather_day",
        "weather_night",
    }
)

#: 官署 (``daily_s1``) の列並び。先頭の ``day`` を含めて 21 列。
LAYOUT_OFFICIAL: tuple[str, ...] = (
    "day",
    "pressure_local",
    "pressure_sea",
    "precip_total",
    "precip_max_1h",
    "precip_max_10min",
    "temp_mean",
    "temp_max",
    "temp_min",
    "humidity_mean",
    "humidity_min",
    "wind_mean",
    "wind_max",
    "wind_max_dir",
    "wind_gust",
    "wind_gust_dir",
    "sunshine",
    "snowfall",
    "snow_depth",
    "weather_day",
    "weather_night",
)

#: アメダス (``daily_a1``) の列並び。雪の観測がある地点は 16 列。
LAYOUT_AMEDAS: tuple[str, ...] = (
    "day",
    "precip_total",
    "precip_max_1h",
    "precip_max_10min",
    "temp_mean",
    "temp_max",
    "temp_min",
    "wind_mean",
    "wind_max",
    "wind_max_dir",
    "wind_gust",
    "wind_gust_dir",
    "wind_prevailing_dir",
    "sunshine",
    "snowfall",
    "snow_depth",
)

#: 雪を観測しない地点は末尾の降雪・積雪 2 列が無い。
LAYOUT_AMEDAS_NO_SNOW: tuple[str, ...] = LAYOUT_AMEDAS[:-2]

#: 最多風向を持たない古い形式のアメダス表。
LAYOUT_AMEDAS_NO_PREVAILING: tuple[str, ...] = tuple(
    c for c in LAYOUT_AMEDAS if c != "wind_prevailing_dir"
)

#: セル数から列並びを引く。気象庁の表は地点によって列数が変わるため、
#: 位置決め打ちではなくセル数で判別する。
LAYOUTS_BY_WIDTH: dict[str, dict[int, tuple[str, ...]]] = {
    KIND_STATION: {
        len(LAYOUT_OFFICIAL): LAYOUT_OFFICIAL,
    },
    "a": {
        len(LAYOUT_AMEDAS): LAYOUT_AMEDAS,
        len(LAYOUT_AMEDAS_NO_SNOW): LAYOUT_AMEDAS_NO_SNOW,
        len(LAYOUT_AMEDAS_NO_PREVAILING): LAYOUT_AMEDAS_NO_PREVAILING,
    },
}

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


class ParseError(RuntimeError):
    """HTML から日別値を取り出せなかった。"""


def clean_text(raw: str) -> str:
    """セルの文字列から空白類を取り除く。全角空白と ``&nbsp;`` も対象。"""
    return raw.replace(" ", " ").replace("　", " ").strip()


def split_quality_flag(value: str) -> tuple[str, str | None]:
    """末尾の品質記号を切り離して ``(値, 記号)`` を返す。"""
    flag_chars = ""
    body = value
    while body and body[-1] in QUALITY_SUFFIXES:
        flag_chars = body[-1] + flag_chars
        body = body[:-1].rstrip()
    return body, flag_chars or None


def parse_number(raw: str, *, field: str) -> tuple[float | None, str | None]:
    """セルの文字列を数値に変換し、``(値, 品質記号)`` を返す。

    ``--``（現象なし）は積算量なら 0.0、それ以外は ``None``。
    ``×`` や空欄などの欠測は ``None``。
    """
    text = clean_text(raw)
    if text in NO_PHENOMENON_TOKENS:
        return (0.0 if field in ACCUMULATION_FIELDS else None), None
    if text in MISSING_TOKENS:
        return None, ("×" if text else None)

    body, flag = split_quality_flag(text)
    if body in NO_PHENOMENON_TOKENS:
        return (0.0 if field in ACCUMULATION_FIELDS else None), flag
    if body in MISSING_TOKENS:
        return None, flag or "×"
    if not _NUMBER_RE.match(body):
        logger.debug("数値として解釈できないセル (%s): %r", field, raw)
        return None, flag
    return float(body), flag


def parse_text(raw: str) -> tuple[str | None, str | None]:
    """風向や天気概況のセルを文字列として取り出す。"""
    text = clean_text(raw)
    if text in MISSING_TOKENS or text in NO_PHENOMENON_TOKENS:
        return None, ("×" if text in MISSING_TOKENS and text else None)
    body, flag = split_quality_flag(text)
    return (body or None), flag


def _select_layout(kind: str, width: int) -> tuple[str, ...] | None:
    """セル数に合う列並びを返す。見つからなければ ``None``。"""
    return LAYOUTS_BY_WIDTH.get(kind, {}).get(width)


def _data_rows(soup: BeautifulSoup) -> list[list[str]]:
    """日別値の行だけを取り出す。

    表の ``id`` や ``class`` に依存すると気象庁側の小さな変更で壊れるので、
    「先頭セルが 1〜31 の整数」「セルが 10 個以上」という中身の条件で選ぶ。
    """
    rows: list[list[str]] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 10:
            continue
        head = clean_text(cells[0].get_text())
        if not head.isdigit():
            continue
        if not 1 <= int(head) <= 31:
            continue
        rows.append([c.get_text() for c in cells])
    return rows


def parse_daily_page(
    html: str, station: Station, year: int, month: int
) -> list[DailyRecord]:
    """日別値ページの HTML を :class:`DailyRecord` のリストに変換する。

    日付順に並べて返す。表に無い日（未来日など）は含まれない。
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = _data_rows(soup)
    if not rows:
        raise ParseError(
            f"{station.name}({station.block_no}) {year}年{month}月: "
            "日別値の表が見つかりませんでした"
        )

    records: list[DailyRecord] = []
    for cells in rows:
        layout = _select_layout(station.kind, len(cells))
        if layout is None:
            # 気象庁が列を増減させた可能性がある。取れる範囲だけ取って先へ進む。
            fallback = LAYOUT_OFFICIAL if station.is_official else LAYOUT_AMEDAS
            logger.warning(
                "%s(%s): 未知の列数 %d です。先頭 %d 列のみ解釈します。"
                "parse_jma.LAYOUTS_BY_WIDTH に定義を追加してください。",
                station.name,
                station.block_no,
                len(cells),
                min(len(cells), len(fallback)),
            )
            layout = fallback

        day_text = clean_text(cells[0])
        try:
            day = date(year, month, int(day_text))
        except ValueError:
            logger.warning("日付として解釈できません: %r", day_text)
            continue

        record = DailyRecord(station=station, day=day)
        for column, raw in zip(layout[1:], cells[1:]):
            if column in TEXT_FIELDS:
                value, flag = parse_text(raw)
            else:
                value, flag = parse_number(raw, field=column)
            setattr(record, column, value)
            if flag:
                record.flags[column] = flag
        records.append(record)

    records.sort(key=lambda r: r.day)
    return records
