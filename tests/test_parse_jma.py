"""日別値ページのパーサのテスト。"""

from __future__ import annotations

from datetime import date

import pytest

from weather_report.models import KIND_AMEDAS, KIND_STATION, Station
from weather_report.parse_jma import (
    ParseError,
    parse_daily_page,
    parse_number,
    parse_text,
    split_quality_flag,
)

from .fixtures import amedas_row, build_daily_table, official_row

SAGA = Station(prec_no=85, block_no="47813", name="佐賀", kind=KIND_STATION)
IMARI = Station(prec_no=85, block_no="0851", name="伊万里", kind=KIND_AMEDAS)


class TestParseNumber:
    def test_通常の数値(self):
        assert parse_number("28.4", field="temp_mean") == (28.4, None)

    def test_整数(self):
        assert parse_number("75", field="humidity_mean") == (75.0, None)

    def test_負の値(self):
        assert parse_number("-3.2", field="temp_min") == (-3.2, None)

    def test_現象なしは積算量なら0(self):
        assert parse_number("--", field="precip_total") == (0.0, None)
        assert parse_number("--", field="snowfall") == (0.0, None)

    def test_現象なしは非積算量ならNone(self):
        assert parse_number("--", field="temp_mean") == (None, None)

    def test_欠測(self):
        value, flag = parse_number("×", field="temp_max")
        assert value is None
        assert flag == "×"

    def test_空欄は未観測(self):
        assert parse_number("", field="humidity_mean") == (None, None)

    def test_準正常値の記号を残す(self):
        assert parse_number("12.5 )", field="precip_total") == (12.5, ")")

    def test_資料不足値の記号を残す(self):
        assert parse_number("30.0]", field="sunshine") == (30.0, "]")

    def test_全角空白を除去(self):
        assert parse_number("　28.4　", field="temp_mean") == (28.4, None)

    def test_解釈できない文字列はNone(self):
        value, _ = parse_number("あいうえお", field="temp_mean")
        assert value is None


class TestSplitQualityFlag:
    @pytest.mark.parametrize(
        "raw,body,flag",
        [
            ("12.5", "12.5", None),
            ("12.5)", "12.5", ")"),
            ("12.5]", "12.5", "]"),
            ("12.5 )", "12.5", ")"),
            ("12.5#", "12.5", "#"),
        ],
    )
    def test_記号の切り離し(self, raw, body, flag):
        assert split_quality_flag(raw) == (body, flag)


class TestParseText:
    def test_風向(self):
        assert parse_text("南南西") == ("南南西", None)

    def test_天気概況(self):
        assert parse_text("曇一時雨") == ("曇一時雨", None)

    def test_空欄(self):
        assert parse_text("") == (None, None)


class TestParseDailyPage:
    def test_官署の21列を解釈する(self):
        html = build_daily_table([official_row(d) for d in range(1, 32)])
        records = parse_daily_page(html, SAGA, 2026, 7)

        assert len(records) == 31
        first = records[0]
        assert first.day == date(2026, 7, 1)
        assert first.temp_max == 32.0
        assert first.temp_min == 24.0
        assert first.humidity_mean == 75.0
        assert first.wind_gust == 11.2
        assert first.wind_gust_dir == "南南西"
        assert first.weather_day == "晴"
        assert first.weather_night == "晴"
        # 夏の降雪・積雪は「--」なので 0 になる
        assert first.snowfall == 0.0

    def test_アメダスの16列を解釈する(self):
        html = build_daily_table([amedas_row(d) for d in range(1, 32)])
        records = parse_daily_page(html, IMARI, 2026, 7)

        assert len(records) == 31
        first = records[0]
        assert first.temp_max == 31.5
        assert first.wind_prevailing_dir == "南"
        # アメダスは湿度と天気概況を観測しない
        assert first.humidity_mean is None
        assert first.weather_day is None

    def test_日付順に並ぶ(self):
        rows = [official_row(d) for d in (5, 1, 3)]
        records = parse_daily_page(build_daily_table(rows), SAGA, 2026, 7)
        assert [r.day.day for r in records] == [1, 3, 5]

    def test_見出し行を読み飛ばす(self):
        html = build_daily_table([official_row(1)])
        records = parse_daily_page(html, SAGA, 2026, 7)
        assert len(records) == 1

    def test_品質記号をflagsに残す(self):
        rows = [official_row(1, precip="45.5 )")]
        records = parse_daily_page(build_daily_table(rows), SAGA, 2026, 7)
        assert records[0].precip_total == 45.5
        assert records[0].flags["precip_total"] == ")"

    def test_表が無ければParseError(self):
        with pytest.raises(ParseError):
            parse_daily_page("<html><body>no table</body></html>", SAGA, 2026, 7)

    def test_存在しない日は捨てる(self):
        # 2 月 30 日のような不正な日付が来ても落ちない
        rows = [official_row(30)]
        records = parse_daily_page(build_daily_table(rows), SAGA, 2026, 2)
        assert records == []

    def test_未知の列数でも先頭列は取れる(self):
        # 気象庁が列を増やした場合を想定。落ちずに読める範囲を読む。
        row = official_row(1) + ["余分な列"]
        records = parse_daily_page(build_daily_table([row]), SAGA, 2026, 7)
        assert len(records) == 1
        assert records[0].temp_max == 32.0


class TestDailyRecordFlags:
    def test_猛暑日の判定(self):
        rows = [official_row(1, temp_max="35.4")]
        record = parse_daily_page(build_daily_table(rows), SAGA, 2026, 7)[0]
        assert record.is_extremely_hot_day
        assert record.is_midsummer_day

    def test_熱帯夜の判定(self):
        rows = [official_row(1, temp_min="26.1")]
        record = parse_daily_page(build_daily_table(rows), SAGA, 2026, 7)[0]
        assert record.is_tropical_night

    def test_大雨日の判定(self):
        rows = [official_row(1, precip="88.0")]
        record = parse_daily_page(build_daily_table(rows), SAGA, 2026, 7)[0]
        assert record.is_heavy_rain_day
        assert record.is_rainy_day

    def test_微量の降水は降水日にしない(self):
        rows = [official_row(1, precip="0.5")]
        record = parse_daily_page(build_daily_table(rows), SAGA, 2026, 7)[0]
        assert not record.is_rainy_day
