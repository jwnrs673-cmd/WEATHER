"""気象庁「過去の気象データ検索」からの HTML 取得。

取得した HTML は ``data/raw/`` にそのまま保存する。パーサを直したときに
再取得せず作り直せるようにするためと、レポートの再現性を保つため。

気象庁のサーバに負荷をかけないよう、リクエスト間隔を必ず空ける。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from .models import KIND_STATION, Station

logger = logging.getLogger(__name__)

BASE_URL = "https://www.data.jma.go.jp/obd/stats/etrn"

#: 連続リクエストの最小間隔（秒）。気象庁のサーバへの配慮。
REQUEST_INTERVAL = 1.5

#: 取得元を明示する User-Agent。問い合わせ先が分かるようにしておくのが礼儀。
USER_AGENT = (
    "weather-report/0.1 (monthly weather summary generator; "
    "https://github.com/jwnrs673-cmd/weather)"
)

_last_request_at = 0.0


class FetchError(RuntimeError):
    """HTML の取得に失敗した。"""


def _throttle() -> None:
    """前回のリクエストから :data:`REQUEST_INTERVAL` 秒空ける。"""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def _get(url: str, *, retries: int = 3, timeout: float = 30.0) -> str:
    """URL を取得して本文を返す。一時的な失敗は指数バックオフで再試行する。"""
    last_error: Exception | None = None
    for attempt in range(retries):
        if attempt:
            wait = 2**attempt
            logger.warning("再試行まで %d 秒待機します (%d/%d)", wait, attempt + 1, retries)
            time.sleep(wait)
        _throttle()
        try:
            response = requests.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=timeout
            )
        except requests.RequestException as exc:
            last_error = exc
            continue
        if response.status_code == 200:
            # 気象庁のページは EUC-JP。requests の推測は当てにせず明示する。
            response.encoding = response.apparent_encoding or "euc-jp"
            return response.text
        # 4xx は再試行しても直らないので即座に諦める。
        if 400 <= response.status_code < 500:
            raise FetchError(f"{url} が HTTP {response.status_code} を返しました")
        last_error = FetchError(f"HTTP {response.status_code}")
    raise FetchError(f"{url} の取得に失敗しました: {last_error}")


def fetch(url: str, cache_path: Path, *, refresh: bool = False) -> str:
    """``cache_path`` にキャッシュしつつ URL を取得する。

    キャッシュがあればネットワークに出ない。``refresh=True`` で強制的に取り直す。
    """
    if cache_path.exists() and not refresh:
        logger.debug("キャッシュを使用: %s", cache_path)
        return cache_path.read_text(encoding="utf-8")

    logger.info("取得中: %s", url)
    html = _get(url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    return html


def prefecture_url(prec_no: int) -> str:
    """府県内の観測地点一覧ページの URL。"""
    return f"{BASE_URL}/select/prefecture.php?prec_no={prec_no}&block_no=&year=&month=&day=&view="


def daily_url(station: Station, year: int, month: int) -> str:
    """ある地点・ある月の日別値ページの URL。

    官署は ``daily_s1.php``、アメダスは ``daily_a1.php`` と参照先が異なる。
    """
    page = "daily_s1" if station.kind == KIND_STATION else "daily_a1"
    return (
        f"{BASE_URL}/view/{page}.php"
        f"?prec_no={station.prec_no}&block_no={station.block_no}"
        f"&year={year}&month={month}&day=&view="
    )


def fetch_prefecture_page(prec_no: int, cache_dir: Path, *, refresh: bool = False) -> str:
    """観測地点一覧ページの HTML を取得する。"""
    return fetch(
        prefecture_url(prec_no),
        cache_dir / f"prefecture_{prec_no}.html",
        refresh=refresh,
    )


def fetch_daily_page(
    station: Station, year: int, month: int, cache_dir: Path, *, refresh: bool = False
) -> str:
    """ある地点・ある月の日別値ページの HTML を取得する。"""
    return fetch(
        daily_url(station, year, month),
        cache_dir / f"{station.kind}_{station.block_no}_{year}{month:02d}.html",
        refresh=refresh,
    )
