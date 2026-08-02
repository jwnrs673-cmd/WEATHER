"""観測地点の探索のテスト。"""

from __future__ import annotations

from weather_report.models import KIND_AMEDAS, KIND_STATION, Station
from weather_report.prefectures import resolve
from weather_report.stations import parse_prefecture_page, representative

from .fixtures import build_prefecture_page


class TestParsePrefecturePage:
    def test_官署とアメダスを見分ける(self):
        html = build_prefecture_page(
            [("s", "47813", "佐賀"), ("a", "0851", "伊万里")]
        )
        stations = parse_prefecture_page(html, 85)

        by_name = {s.name: s for s in stations}
        assert by_name["佐賀"].kind == KIND_STATION
        assert by_name["佐賀"].observes_humidity
        assert by_name["伊万里"].kind == KIND_AMEDAS
        assert not by_name["伊万里"].observes_humidity

    def test_官署を先に並べる(self):
        html = build_prefecture_page(
            [("a", "0851", "伊万里"), ("a", "0849", "白石"), ("s", "47813", "佐賀")]
        )
        stations = parse_prefecture_page(html, 85)
        assert stations[0].name == "佐賀"

    def test_重複した地点をまとめる(self):
        html = build_prefecture_page(
            [("s", "47813", "佐賀"), ("s", "47813", "佐賀")]
        )
        assert len(parse_prefecture_page(html, 85)) == 1

    def test_地点が無ければ空(self):
        assert parse_prefecture_page("<html><body></body></html>", 85) == []


class TestRepresentative:
    def test_代表地点の番号が一致するものを選ぶ(self):
        saga = resolve("佐賀県")
        stations = [
            Station(85, "0851", "伊万里", KIND_AMEDAS),
            Station(85, "47813", "佐賀", KIND_STATION),
        ]
        assert representative(stations, saga).name == "佐賀"

    def test_一致が無ければ官署を選ぶ(self):
        saga = resolve("佐賀県")
        stations = [
            Station(85, "0851", "伊万里", KIND_AMEDAS),
            Station(85, "47812", "佐世保", KIND_STATION),
        ]
        assert representative(stations, saga).kind == KIND_STATION

    def test_官署が無ければ先頭を使う(self):
        saga = resolve("佐賀県")
        stations = [Station(85, "0851", "伊万里", KIND_AMEDAS)]
        assert representative(stations, saga).name == "伊万里"
