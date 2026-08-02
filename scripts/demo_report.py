#!/usr/bin/env python3
"""レポートの体裁を確認するためのサンプルを作る。

**このスクリプトが作る数値はすべて架空**である。気象庁から取得した実測値では
ないため、気象の資料として使ってはならない。ネットワークが通らない環境でも
レポートの構成と見た目を確認できるようにするためだけのもの。

実データのレポートは次のコマンドで作る::

    python -m weather_report --pref 佐賀県 --month 2026-07
"""

from __future__ import annotations

import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from weather_report import aggregate, render  # noqa: E402
from weather_report.models import (  # noqa: E402
    KIND_AMEDAS,
    KIND_STATION,
    DailyRecord,
    Station,
)
from weather_report.prefectures import resolve  # noqa: E402

WARNING_BANNER = """\
> ⚠️ **このファイルはサンプルです。掲載されている数値はすべて架空の値であり、
> 実際の観測値ではありません。** レポートの構成と体裁を確認するためだけに
> `scripts/demo_report.py` が生成したものです。
>
> 実データのレポートは `python -m weather_report --pref 佐賀県 --month 2026-07`
> で作成してください（気象庁への接続が必要です）。

"""

WEATHER_PATTERNS = ["晴", "晴後曇", "曇時々晴", "曇", "曇一時雨", "雨", "大雨"]
DIRECTIONS = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]


def synth_records(station: Station, year: int, month: int, days: int) -> list[DailyRecord]:
    """それらしい形をした架空の日別値を作る。"""
    rng = random.Random(f"{station.block_no}-{year}-{month}")
    records = []
    for day in range(1, days + 1):
        rainy = rng.random() < 0.35
        precip = round(rng.choice([0.5, 3.0, 12.0, 45.0, 88.0]) * rng.random(), 1) if rainy else 0.0
        temp_max = round(rng.uniform(28.0, 36.5), 1)
        record = DailyRecord(
            station=station,
            day=date(year, month, day),
            precip_total=precip,
            precip_max_1h=round(precip * rng.uniform(0.2, 0.6), 1) if precip else 0.0,
            precip_max_10min=round(precip * rng.uniform(0.05, 0.15), 1) if precip else 0.0,
            temp_mean=round(temp_max - rng.uniform(3.0, 5.0), 1),
            temp_max=temp_max,
            temp_min=round(temp_max - rng.uniform(6.0, 10.0), 1),
            wind_mean=round(rng.uniform(1.5, 4.0), 1),
            wind_max=round(rng.uniform(4.0, 12.0), 1),
            wind_max_dir=rng.choice(DIRECTIONS),
            wind_gust=round(rng.uniform(8.0, 24.0), 1),
            wind_gust_dir=rng.choice(DIRECTIONS),
            sunshine=round(rng.uniform(0.0, 11.0), 1),
            snowfall=0.0,
            snow_depth=0.0,
        )
        if station.is_official:
            record.pressure_local = round(rng.uniform(1000.0, 1012.0), 1)
            record.pressure_sea = round(record.pressure_local + 1.4, 1)
            record.humidity_mean = round(rng.uniform(65.0, 92.0))
            record.humidity_min = round(rng.uniform(40.0, 70.0))
            record.weather_day = rng.choice(WEATHER_PATTERNS)
            record.weather_night = rng.choice(WEATHER_PATTERNS)
        else:
            record.wind_prevailing_dir = rng.choice(DIRECTIONS)
        records.append(record)
    return records


def main() -> int:
    pref = resolve("佐賀県")
    year, month, days = 2026, 7, 31

    stations = [
        Station(pref.prec_no, "47813", "佐賀", KIND_STATION),
        Station(pref.prec_no, "0851", "伊万里", KIND_AMEDAS),
        Station(pref.prec_no, "0849", "白石", KIND_AMEDAS),
    ]
    by_station = {s: synth_records(s, year, month, days) for s in stations}
    result = aggregate.build(year, month, stations[0], by_station)

    output_dir = Path(__file__).resolve().parents[1] / "reports" / "_sample"
    output_dir.mkdir(parents=True, exist_ok=True)

    markdown = WARNING_BANNER + render.render_markdown(pref, result)
    (output_dir / "report_sample.md").write_text(markdown, encoding="utf-8")
    render.write_csv(output_dir / "daily_sample.csv", result)

    print(f"サンプルを作成しました: {output_dir}")
    print("※ 数値はすべて架空です。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
