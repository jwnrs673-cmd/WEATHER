"""コマンドラインからの実行。

例::

    # 佐賀県の 2026 年 7 月
    python -m weather_report --pref 佐賀県 --month 2026-07

    # 九州 7 県まとめて
    python -m weather_report --pref kyushu --month 2026-07
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .pipeline import Paths, run
from .prefectures import REGIONS, resolve_many


def _parse_month(value: str) -> tuple[int, int]:
    """``2026-07`` または ``2026/7`` を ``(2026, 7)`` にする。"""
    text = value.replace("/", "-").strip()
    try:
        year_text, month_text = text.split("-")
        year, month = int(year_text), int(month_text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"月の指定が不正です: {value!r}（例: 2026-07）"
        ) from None
    if not 1 <= month <= 12:
        raise argparse.ArgumentTypeError(f"月は 1〜12 で指定してください: {month}")
    if not 1900 <= year <= date.today().year:
        raise argparse.ArgumentTypeError(f"年の指定が不正です: {year}")
    return year, month


def build_parser() -> argparse.ArgumentParser:
    regions = "、".join(REGIONS)
    parser = argparse.ArgumentParser(
        prog="weather_report",
        description="指定した月・都道府県の日別気象概況レポートを作成します。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--pref",
        nargs="+",
        required=True,
        metavar="県名",
        help=f"対象の都道府県。県名・ローマ字・JIS コードのいずれでも可。地方名（{regions}）も指定できます。",
    )
    parser.add_argument(
        "--month",
        required=True,
        type=_parse_month,
        metavar="YYYY-MM",
        help="対象年月（例: 2026-07）。",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="出力先のルートディレクトリ（既定: リポジトリ直下）。",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="キャッシュを無視して気象庁から取得し直します。",
    )
    parser.add_argument(
        "--max-stations",
        type=int,
        metavar="N",
        help="1 県あたりの対象地点数の上限。代表地点は必ず含まれます。",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="進捗ログを抑制します。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        prefectures = resolve_many(args.pref)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2

    year, month = args.month
    if (year, month) >= (date.today().year, date.today().month):
        print(
            f"警告: {year}年{month}月はまだ終わっていないため、"
            "月の途中までの値になります。",
            file=sys.stderr,
        )

    results = run(
        prefectures,
        year,
        month,
        Paths(args.root),
        refresh=args.refresh,
        max_stations=args.max_stations,
    )
    if not results:
        print(
            "レポートを 1 件も作成できませんでした。\n"
            "上のログに 403 や接続失敗が並んでいる場合は、"
            "気象庁 (www.data.jma.go.jp) への通信が許可されていない可能性があります。\n"
            "README の「必要なもの」を参照してください。",
            file=sys.stderr,
        )
        return 1

    print(f"{len(results)} 県のレポートを作成しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
