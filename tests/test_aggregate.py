"""月間統計と県内集計のテスト。"""

from __future__ import annotations

from datetime import date

from weather_report import aggregate
from weather_report.models import KIND_AMEDAS, KIND_STATION, DailyRecord, Station

SAGA = Station(85, "47813", "佐賀", KIND_STATION)
IMARI = Station(85, "0851", "伊万里", KIND_AMEDAS)


def record(day: int, station: Station = SAGA, **values) -> DailyRecord:
    return DailyRecord(station=station, day=date(2026, 7, day), **values)


class TestSummarize:
    def test_合計と平均(self):
        records = [
            record(1, precip_total=10.0, temp_mean=28.0),
            record(2, precip_total=20.0, temp_mean=30.0),
        ]
        summary = aggregate.summarize(SAGA, records)
        assert summary.precip_total == 30.0
        assert summary.temp_mean == 29.0

    def test_欠測は集計から除く(self):
        records = [
            record(1, precip_total=10.0, temp_mean=28.0),
            record(2, precip_total=None, temp_mean=None),
            record(3, precip_total=20.0, temp_mean=32.0),
        ]
        summary = aggregate.summarize(SAGA, records)
        assert summary.precip_total == 30.0
        assert summary.temp_mean == 30.0
        # 欠測の多寡が分かるよう有効日数を残す
        assert summary.observed_days["temp_mean"] == 2

    def test_すべて欠測ならNone(self):
        summary = aggregate.summarize(SAGA, [record(1), record(2)])
        assert summary.precip_total is None
        assert summary.temp_mean is None

    def test_日数の集計(self):
        records = [
            record(1, temp_max=36.0, temp_min=26.0, precip_total=0.0),
            record(2, temp_max=31.0, temp_min=24.0, precip_total=60.0),
            record(3, temp_max=28.0, temp_min=22.0, precip_total=0.5),
        ]
        summary = aggregate.summarize(SAGA, records)
        assert summary.extremely_hot_days == 1
        assert summary.midsummer_days == 2
        assert summary.tropical_nights == 1
        assert summary.heavy_rain_days == 1
        # 0.5mm は降水日に数えない
        assert summary.rainy_days == 1


class TestPrefectureExtremes:
    def test_県内最高気温の地点と日を特定する(self):
        by_station = {
            SAGA: [record(1, temp_max=34.0), record(2, temp_max=33.0)],
            IMARI: [
                record(1, IMARI, temp_max=32.0),
                record(2, IMARI, temp_max=35.6),
            ],
        }
        result = aggregate.build(2026, 7, SAGA, by_station)
        assert result.hottest is not None
        assert result.hottest.value == 35.6
        assert result.hottest.station is IMARI
        assert result.hottest.day == date(2026, 7, 2)

    def test_県内最低気温は最小値を選ぶ(self):
        by_station = {
            SAGA: [record(1, temp_min=22.0)],
            IMARI: [record(1, IMARI, temp_min=19.4)],
        }
        result = aggregate.build(2026, 7, SAGA, by_station)
        assert result.coldest is not None
        assert result.coldest.value == 19.4
        assert result.coldest.station is IMARI

    def test_日ごとの県内最大(self):
        by_station = {
            SAGA: [record(1, precip_total=10.0), record(2, precip_total=50.0)],
            IMARI: [
                record(1, IMARI, precip_total=80.0),
                record(2, IMARI, precip_total=5.0),
            ],
        }
        result = aggregate.build(2026, 7, SAGA, by_station)
        day1, day2 = result.daily_extremes
        assert day1.precip.station is IMARI
        assert day1.precip.value == 80.0
        assert day2.precip.station is SAGA
        assert day2.precip.value == 50.0

    def test_値が無ければNone(self):
        result = aggregate.build(2026, 7, SAGA, {SAGA: [record(1)]})
        assert result.hottest is None
        assert result.wettest is None
