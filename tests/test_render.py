"""レポート出力のテスト。"""

from __future__ import annotations

import csv
from datetime import date

from weather_report import aggregate, narrative, render
from weather_report.models import KIND_AMEDAS, KIND_STATION, DailyRecord, Station
from weather_report.prefectures import resolve

SAGA_PREF = resolve("佐賀県")
SAGA = Station(85, "47813", "佐賀", KIND_STATION)
IMARI = Station(85, "0851", "伊万里", KIND_AMEDAS)


def build_result() -> aggregate.PrefectureSummary:
    saga_records = [
        DailyRecord(
            station=SAGA,
            day=date(2026, 7, d),
            precip_total=float(d),
            temp_mean=28.0,
            temp_max=30.0 + d * 0.2,
            temp_min=24.0,
            humidity_mean=78.0,
            humidity_min=55.0,
            wind_mean=2.4,
            wind_max=6.0,
            wind_max_dir="南",
            wind_gust=12.0,
            wind_gust_dir="南南西",
            sunshine=7.0,
            weather_day="晴後曇",
            weather_night="曇",
        )
        for d in range(1, 6)
    ]
    imari_records = [
        DailyRecord(
            station=IMARI,
            day=date(2026, 7, d),
            precip_total=float(d) * 2,
            temp_max=29.0,
            temp_min=23.0,
            wind_gust=10.0,
        )
        for d in range(1, 6)
    ]
    return aggregate.build(2026, 7, SAGA, {SAGA: saga_records, IMARI: imari_records})


class TestRenderMarkdown:
    def test_主要な見出しが揃う(self):
        text = render.render_markdown(SAGA_PREF, build_result())
        for heading in (
            "# 佐賀県 2026年7月 気象概況",
            "## 1. 月間サマリ",
            "## 2. 特筆すべき日",
            "## 3. 日別一覧",
            "## 5. 県内各地点の日別値",
            "## 6. 県内クロス集計",
            "## 7. 注記",
        ):
            assert heading in text

    def test_出典を明記する(self):
        text = render.render_markdown(SAGA_PREF, build_result())
        assert "気象庁" in text
        assert "data.jma.go.jp" in text

    def test_代表地点の表に湿度列がある(self):
        text = render.render_markdown(SAGA_PREF, build_result())
        assert "平均湿度" in text

    def test_アメダスには湿度がない旨を注記する(self):
        text = render.render_markdown(SAGA_PREF, build_result())
        assert "アメダスのため湿度・天気概況の観測はありません" in text

    def test_全日分の行が出る(self):
        text = render.render_markdown(SAGA_PREF, build_result())
        # 5 日分 × 2 地点 + クロス集計 5 行
        assert text.count("| 1 |") >= 2

    def test_欠測はハイフンで表す(self):
        result = aggregate.build(
            2026,
            7,
            SAGA,
            {SAGA: [DailyRecord(station=SAGA, day=date(2026, 7, 1))]},
        )
        text = render.render_markdown(SAGA_PREF, result)
        assert "--" in text


class TestWriteReport:
    def test_ファイルが2つできる(self, tmp_path):
        markdown_path, csv_path = render.write_report(
            tmp_path, SAGA_PREF, build_result()
        )
        assert markdown_path.exists()
        assert csv_path.exists()

    def test_CSVに全地点分の行が入る(self, tmp_path):
        _, csv_path = render.write_report(tmp_path, SAGA_PREF, build_result())
        with csv_path.open(encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 10  # 2 地点 × 5 日
        assert {r["地点"] for r in rows} == {"佐賀", "伊万里"}

    def test_CSVの列名が日本語(self, tmp_path):
        _, csv_path = render.write_report(tmp_path, SAGA_PREF, build_result())
        with csv_path.open(encoding="utf-8-sig") as handle:
            header = next(csv.reader(handle))
        assert "降水量合計(mm)" in header
        assert "平均湿度(%)" in header


class TestRenderIndex:
    def test_複数県の一覧を作る(self):
        entries = [(SAGA_PREF, build_result()), (resolve("福岡県"), build_result())]
        text = render.render_index(2026, 7, entries)
        assert "佐賀県" in text
        assert "福岡県" in text
        assert "41_saga/report.md" in text


class TestNarrative:
    def test_猛暑日を言い換える(self):
        record = DailyRecord(
            station=SAGA, day=date(2026, 7, 1), temp_max=36.2, temp_min=26.5
        )
        text = narrative.describe_day(record)
        assert "猛暑日" in text
        assert "熱帯夜" in text

    def test_大雨を言い換える(self):
        record = DailyRecord(
            station=SAGA, day=date(2026, 7, 1), precip_total=120.0, precip_max_1h=55.0
        )
        text = narrative.describe_day(record)
        assert "非常に激しい雨" in text

    def test_強風を言い換える(self):
        record = DailyRecord(
            station=SAGA, day=date(2026, 7, 1), wind_gust=32.0, wind_gust_dir="南"
        )
        assert "暴風" in narrative.describe_day(record)

    def test_特徴が無い日(self):
        record = DailyRecord(station=SAGA, day=date(2026, 7, 1), temp_max=25.0)
        assert narrative.describe_day(record) == "大きな特徴なし"

    def test_天気概況を先頭に置く(self):
        record = DailyRecord(
            station=SAGA, day=date(2026, 7, 1), weather_day="曇一時雨", temp_max=31.0
        )
        assert narrative.describe_day(record).startswith("曇一時雨")
