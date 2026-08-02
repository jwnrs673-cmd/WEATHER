"""県内の観測地点の探索。

観測所番号 (``block_no``) は県ごとに違ううえ、アメダスは統廃合される。
そこで番号を決め打ちせず、気象庁の府県地図ページから毎回読み取る。

読み取った一覧は ``config/stations/<slug>.json`` に保存され、次回以降は
そちらが使われる。地点を絞りたいときはこの JSON を編集すればよい。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .fetch_jma import fetch_prefecture_page
from .models import KIND_AMEDAS, KIND_STATION, Station
from .prefectures import Prefecture

logger = logging.getLogger(__name__)

#: 府県地図ページの ``<area>` に埋め込まれた地点情報。
#: 例: ``viewPoint('s','47813','saga','佐賀','33','15','130','18')``
_VIEW_POINT_RE = re.compile(
    r"viewPoint\(\s*'([sa])'\s*,\s*'(\d+)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'"
)

#: ``viewPoint`` が拾えなかったときに使う href 側のパターン。
_BLOCK_NO_RE = re.compile(r"block_no=(\d+)")
_PAGE_KIND_RE = re.compile(r"daily_(s|a)1\.php")


def _from_area_tag(tag, prec_no: int) -> Station | None:
    """``<area>`` 1 つから :class:`Station` を作る。地点でなければ ``None``。"""
    # onmouseover に viewPoint(...) が入っているのが通常の形。
    for attr in ("onmouseover", "onclick", "href"):
        value = tag.get(attr)
        if not value:
            continue
        match = _VIEW_POINT_RE.search(value)
        if match:
            kind, block_no, _romaji, name = match.groups()
            if not name:
                continue
            return Station(
                prec_no=prec_no, block_no=block_no, name=name, kind=kind
            )

    # 形式が変わっていた場合に備えた保険。href から番号と種別を拾う。
    href = tag.get("href") or ""
    block_match = _BLOCK_NO_RE.search(href)
    if not block_match:
        return None
    kind_match = _PAGE_KIND_RE.search(href)
    kind = kind_match.group(1) if kind_match else KIND_AMEDAS
    name = (tag.get("alt") or "").strip()
    if not name:
        return None
    return Station(
        prec_no=prec_no, block_no=block_match.group(1), name=name, kind=kind
    )


def parse_prefecture_page(html: str, prec_no: int) -> list[Station]:
    """府県地図ページの HTML から観測地点の一覧を取り出す。

    同じ地点が複数の ``<area>`` に現れることがあるので番号で重複を除く。
    官署を先、アメダスを後にし、それぞれ地点名順に並べて返す。
    """
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Station] = {}
    for tag in soup.find_all("area"):
        station = _from_area_tag(tag, prec_no)
        if station is None:
            continue
        # 官署としてもアメダスとしても現れる地点は、項目の多い官署を優先する。
        existing = found.get(station.block_no)
        if existing is None or (
            existing.kind != KIND_STATION and station.kind == KIND_STATION
        ):
            found[station.block_no] = station

    stations = sorted(
        found.values(), key=lambda s: (0 if s.is_official else 1, s.name)
    )
    return stations


def _config_path(pref: Prefecture, config_dir: Path) -> Path:
    return config_dir / "stations" / f"{pref.slug}.json"


def _load_config(path: Path, prec_no: int) -> list[Station] | None:
    """保存済みの地点一覧を読む。無ければ ``None``。"""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("%s を読めませんでした (%s)。取得し直します。", path, exc)
        return None
    return [
        Station(
            prec_no=prec_no,
            block_no=str(item["block_no"]),
            name=item["name"],
            kind=item.get("kind", KIND_AMEDAS),
        )
        for item in payload.get("stations", [])
    ]


def _save_config(path: Path, pref: Prefecture, stations: list[Station]) -> None:
    """地点一覧を JSON に保存する。人が読んで編集できる形で書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "prefecture": pref.name,
        "prec_no": pref.prec_no,
        "_comment": (
            "気象庁の府県地図ページから自動取得した観測地点。"
            "kind の s は官署（湿度・天気概況あり）、a はアメダス。"
            "対象地点を絞りたい場合はこのファイルから項目を削除してください。"
        ),
        "stations": [
            {"block_no": s.block_no, "name": s.name, "kind": s.kind} for s in stations
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_stations(
    pref: Prefecture,
    *,
    config_dir: Path,
    cache_dir: Path,
    refresh: bool = False,
) -> list[Station]:
    """県内の観測地点を返す。

    保存済みの設定があればそれを使い、無ければ気象庁のページから探索して保存する。
    探索に失敗した場合は、県を代表する地方気象台 1 地点だけで処理を続ける。
    """
    path = _config_path(pref, config_dir)
    if not refresh:
        cached = _load_config(path, pref.prec_no)
        if cached:
            logger.info("%s: 設定済みの %d 地点を使用します", pref.name, len(cached))
            return cached

    try:
        html = fetch_prefecture_page(pref.prec_no, cache_dir, refresh=refresh)
        stations = parse_prefecture_page(html, pref.prec_no)
    except Exception as exc:  # 探索の失敗でレポート全体を止めない
        logger.warning("%s: 地点一覧を取得できませんでした (%s)", pref.name, exc)
        stations = []

    if not stations:
        logger.warning(
            "%s: 地点を検出できなかったため、代表地点 %s のみで続行します",
            pref.name,
            pref.representative_block_no,
        )
        return [
            Station(
                prec_no=pref.prec_no,
                block_no=pref.representative_block_no,
                name=pref.short_name,
                kind=KIND_STATION,
            )
        ]

    logger.info("%s: %d 地点を検出しました", pref.name, len(stations))
    _save_config(path, pref, stations)
    return stations


def representative(stations: list[Station], pref: Prefecture) -> Station:
    """県の代表地点（地方気象台）を選ぶ。

    レポートのメイン表と月間サマリの基準に使う。代表地点だけが湿度と
    天気概況を持つため、どれを選ぶかで表の情報量が変わる。
    """
    for station in stations:
        if station.block_no == pref.representative_block_no:
            return station
    for station in stations:
        if station.is_official:
            return station
    return stations[0]
