"""前年同月比の集計と出力のテスト。"""

from __future__ import annotations

from datetime import date

from weather_report import aggregate, compare, render_compare
from weather_report.models import KIND_AMEDAS, KIND_STATION, DailyRecord, Station
from weather_report.prefectures import resolve

SAGA = Station(85, "47813", "佐賀", KIND_STATION)
IMARI = Station(85, "0851", "伊万里", KIND_AMEDAS)
URESHINO = Station(85, "0830", "嬉野", KIND_AMEDAS)


def record(year: int, day: int, station: Station = SAGA, **values) -> DailyRecord:
    return DailyRecord(station=station, day=date(year, 7, day), **values)


def summary(year: int, records_by_station: dict[Station, list[DailyRecord]]):
    representative = next(iter(records_by_station))
    return aggregate.build(year, 7, representative, records_by_station)


def simple(year: int, temps: list[float], precips: list[float] | None = None):
    """1 地点・指定日数分の最小データを組み立てる。"""
    precips = precips if precips is not None else [0.0] * len(temps)
    records = [
        record(year, i + 1, temp_mean=t, temp_max=t + 4, temp_min=t - 4, precip_total=p)
        for i, (t, p) in enumerate(zip(temps, precips))
    ]
    return summary(year, {SAGA: records})


class TestDelta:
    def test_差と比(self):
        delta = compare.Delta(current=336.0, previous=43.0)
        assert delta.diff == 293.0
        assert round(delta.ratio, 2) == 7.81

    def test_片方が欠測なら差も比もNone(self):
        assert compare.Delta(current=None, previous=10.0).diff is None
        assert compare.Delta(current=10.0, previous=None).ratio is None

    def test_前年が0なら比を出さない(self):
        # 降水量は 0 になりうるため 0 除算を避ける
        delta = compare.Delta(current=50.0, previous=0.0)
        assert delta.diff == 50.0
        assert delta.ratio is None

    def test_観測日数が足りなければ要注意(self):
        sparse = compare.Delta(
            current=100.0,
            previous=100.0,
            observed_current=20,
            observed_previous=31,
            days_current=31,
            days_previous=31,
        )
        assert sparse.is_sparse

    def test_観測日数が揃っていれば要注意にしない(self):
        full = compare.Delta(
            current=100.0,
            previous=100.0,
            observed_current=31,
            observed_previous=31,
            days_current=31,
            days_previous=31,
        )
        assert not full.is_sparse


class TestBuild:
    def test_代表地点の月間値を比較する(self):
        current = simple(2026, [28.0] * 31, [10.0] * 31)
        previous = simple(2025, [30.0] * 31, [5.0] * 31)
        result = compare.build(current, previous)

        by_label = {m.label: m for m in result.metrics}
        assert by_label["月平均気温"].delta.diff == -2.0
        assert by_label["月降水量"].delta.diff == 155.0
        assert by_label["月降水量"].delta.ratio == 2.0

    def test_旬ごとに分ける(self):
        # 上旬だけ雨、それ以外は降らない年
        current = simple(2026, [28.0] * 31, [10.0] * 10 + [0.0] * 21)
        previous = simple(2025, [28.0] * 31, [0.0] * 31)
        result = compare.build(current, previous)

        segments = {s.name: s for s in result.segments}
        assert segments["上旬"].precip_total.diff == 100.0
        assert segments["中旬"].precip_total.diff == 0.0
        assert segments["下旬"].precip_total.diff == 0.0

    def test_日別は暦日でそろえる(self):
        current = simple(2026, [28.0] * 31)
        previous = simple(2025, [30.0] * 31)
        result = compare.build(current, previous)

        assert len(result.daily_pairs) == 31
        first = result.daily_pairs[0]
        assert first.day_of_month == 1
        assert first.current.day == date(2026, 7, 1)
        assert first.previous.day == date(2025, 7, 1)

    def test_片方にしかない日は欠けたまま並べる(self):
        current = summary(2026, {SAGA: [record(2026, d, temp_mean=28.0) for d in (1, 2)]})
        previous = summary(2025, {SAGA: [record(2025, d, temp_mean=30.0) for d in (2, 3)]})
        result = compare.build(current, previous)

        pairs = {p.day_of_month: p for p in result.daily_pairs}
        assert pairs[1].previous is None
        assert pairs[3].current is None
        assert pairs[2].current is not None and pairs[2].previous is not None

    def test_両年にある地点だけ比較する(self):
        current = summary(
            2026,
            {
                SAGA: [record(2026, 1, temp_mean=28.0)],
                IMARI: [record(2026, 1, IMARI, temp_mean=27.0)],
            },
        )
        previous = summary(
            2025,
            {
                SAGA: [record(2025, 1, temp_mean=30.0)],
                URESHINO: [record(2025, 1, URESHINO, temp_mean=29.0)],
            },
        )
        result = compare.build(current, previous)

        # 伊万里は前年に、嬉野は当年にないため落とす
        assert [c.station.block_no for c in result.stations] == ["47813"]

    def test_代表地点を先頭に置く(self):
        current = summary(
            2026,
            {
                SAGA: [record(2026, 1, temp_mean=28.0)],
                IMARI: [record(2026, 1, IMARI, temp_mean=27.0)],
            },
        )
        previous = summary(
            2025,
            {
                SAGA: [record(2025, 1, temp_mean=30.0)],
                IMARI: [record(2025, 1, IMARI, temp_mean=29.0)],
            },
        )
        result = compare.build(current, previous)
        assert result.stations[0].station.block_no == current.representative.block_no


class TestMetricDirection:
    def test_項目ごとに言い回しを変える(self):
        temperature = compare.Metric(
            "月平均気温", "℃", compare.Delta(29.0, 28.0), direction="high_low"
        )
        wind = compare.Metric(
            "最大風速", "m/s", compare.Delta(8.0, 10.0), direction="strong_weak"
        )
        precip = compare.Metric("月降水量", "mm", compare.Delta(100.0, 50.0))

        assert temperature.direction_word(1.0) == "高い"
        assert wind.direction_word(-2.0) == "弱い"
        assert precip.direction_word(50.0) == "多い"


class TestRender:
    def test_差の符号を明示する(self):
        assert render_compare._signed(2.5) == "+2.5"
        assert render_compare._signed(-2.5) == "-2.5"
        # 差がないときに +0.0 と書くと増加に見えるため ± を使う
        assert render_compare._signed(0.0) == "±0.0"
        assert render_compare._signed(None) == "--"

    def test_前年が0のときは比の代わりに注記(self):
        assert render_compare._ratio(compare.Delta(50.0, 0.0)) == "前年 0"
        assert render_compare._ratio(compare.Delta(None, 0.0)) == "--"

    def test_差が小さい項目は要点から省く(self):
        # 0.3℃ 未満は年々変動の範囲として落とす
        tiny = compare.Metric(
            "月平均気温", "℃", compare.Delta(29.0, 28.9), direction="high_low"
        )
        assert render_compare._headline(tiny) is None

        clear = compare.Metric(
            "月平均気温", "℃", compare.Delta(29.6, 28.0), direction="high_low"
        )
        assert "高い" in render_compare._headline(clear)

    def test_天気概況を2年分並べる(self):
        current = summary(
            2026,
            {SAGA: [record(2026, 1, weather_day="大雨", weather_night="曇")]},
        )
        previous = summary(
            2025,
            {SAGA: [record(2025, 1, weather_day="晴", weather_night="快晴")]},
        )
        result = compare.build(current, previous)
        text = render_compare._weather_text_section(result)

        assert "| 1 | 大雨 | 曇 | 晴 | 快晴 |" in text
        assert "2026 昼" in text and "2025 夜" in text

    def test_片方の年に観測がない日は空欄にする(self):
        current = summary(2026, {SAGA: [record(2026, 1, weather_day="大雨")]})
        previous = summary(2025, {SAGA: [record(2025, 2, weather_day="晴")]})
        result = compare.build(current, previous)
        text = render_compare._weather_text_section(result)

        assert "| 1 | 大雨 | -- | -- | -- |" in text
        assert "| 2 | -- | -- | 晴 | -- |" in text

    def test_アメダスなら天気概況の表を出さない(self):
        # 天気概況は官署でのみ観測している
        current = summary(2026, {IMARI: [record(2026, 1, IMARI, temp_mean=28.0)]})
        previous = summary(2025, {IMARI: [record(2025, 1, IMARI, temp_mean=30.0)]})
        result = compare.build(current, previous)
        text = render_compare._weather_text_section(result)

        assert "アメダス" in text
        assert "|" not in text

    def test_マークダウンが主要な見出しを含む(self):
        current = simple(2026, [28.0] * 31, [10.0] * 31)
        previous = simple(2025, [30.0] * 31, [5.0] * 31)
        result = compare.build(current, previous)
        text = render_compare.render_markdown(resolve("佐賀県"), result)

        assert "# 佐賀県 2026年7月 気象概況（2025年7月との比較）" in text
        for heading in (
            "## 1. 要点",
            "## 3. 旬別の比較",
            "## 6. 日別対照表",
            "## 7. 日別の天気概況",
            "## 8. 注記",
        ):
            assert heading in text
        # 平年値との違いは必ず断る
        assert "平年値との比較ではなく" in text

    def test_書き出したファイル名に比較対象月が入る(self, tmp_path):
        current = simple(2026, [28.0] * 31)
        previous = simple(2025, [30.0] * 31)
        result = compare.build(current, previous)

        markdown_path, csv_path = render_compare.write_report(
            tmp_path, resolve("佐賀県"), result
        )
        assert markdown_path.name == "compare_2025-07.md"
        assert csv_path.name == "compare_2025-07.csv"
        assert markdown_path.read_text(encoding="utf-8").startswith("# 佐賀県")
        assert "月降水量" in csv_path.read_text(encoding="utf-8")
