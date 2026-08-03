"""月を雨天期・乾燥期に区切る処理のテスト。"""

from __future__ import annotations

from datetime import date

from weather_report import spells, summary_text
from weather_report.aggregate import summarize
from weather_report.models import KIND_STATION, DailyRecord, Station

SAGA = Station(85, "47813", "佐賀", KIND_STATION)


def record(day: int, precip: float | None, **values) -> DailyRecord:
    return DailyRecord(
        station=SAGA, day=date(2026, 7, day), precip_total=precip, **values
    )


def series(precips: list[float | None], **common) -> list[DailyRecord]:
    return [record(i + 1, p, **common) for i, p in enumerate(precips)]


class TestClassify:
    def test_1mm以上が降水日(self):
        assert spells.classify(record(1, 1.0)) == spells.WET
        assert spells.classify(record(1, 0.9)) == spells.DRY

    def test_欠測は乾燥期として扱う(self):
        assert spells.classify(record(1, None)) == spells.DRY


class TestWeatherHead:
    def test_先頭の語を取り出す(self):
        assert spells.weather_head("大雨時々曇、雷を伴う") == "大雨"
        assert spells.weather_head("曇一時晴後一時雨") == "曇"
        assert spells.weather_head("快晴") == "快晴"

    def test_大雨は雨より優先する(self):
        # 「雨」で先に一致すると「大雨」を取りこぼす
        assert spells.weather_head("大雨") == "大雨"

    def test_該当なしはNone(self):
        assert spells.weather_head(None) is None
        assert spells.weather_head("") is None


class TestDetect:
    def test_雨と晴れの並びで区切る(self):
        records = series([10.0] * 5 + [0.0] * 10)
        result = spells.detect(records)

        assert [s.kind for s in result] == [spells.WET, spells.DRY]
        assert result[0].days == 5
        assert result[1].days == 10

    def test_短い晴れ間で分断しない(self):
        # 雨が続く中の 1 日だけの晴れ間は雨天期に吸収する
        records = series([10.0] * 4 + [0.0] + [10.0] * 4)
        result = spells.detect(records)

        assert len(result) == 1
        assert result[0].kind == spells.WET
        assert result[0].days == 9

    def test_短い雨も晴天期に吸収する(self):
        records = series([0.0] * 8 + [5.0] + [0.0] * 8)
        result = spells.detect(records)

        assert len(result) == 1
        assert result[0].kind == spells.DRY

    def test_区切りは最低日数を満たす(self):
        records = series([10.0, 0.0, 10.0, 0.0, 10.0] + [0.0] * 20)
        result = spells.detect(records)

        assert all(s.days >= spells.MIN_SPELL_DAYS for s in result)

    def test_端の短い期間は隣に吸収する(self):
        records = series([10.0] + [0.0] * 14)
        result = spells.detect(records)

        assert len(result) == 1
        assert result[0].kind == spells.DRY

    def test_吸収後は日数の多い側の性格を採る(self):
        # 先頭 2 日の雨が 1 日の晴れに吸収されるとき、雨として扱う
        records = series([10.0, 10.0, 0.0])
        result = spells.detect(records)

        assert len(result) == 1
        assert result[0].kind == spells.WET

    def test_日付順に並べ直す(self):
        records = list(reversed(series([10.0] * 5 + [0.0] * 10)))
        result = spells.detect(records)

        assert result[0].start == date(2026, 7, 1)
        assert result[-1].end == date(2026, 7, 15)

    def test_空なら空(self):
        assert spells.detect([]) == []


class TestSpell:
    def test_期間の集計(self):
        records = series([10.0, 20.0, 30.0], temp_max=36.0, temp_min=26.0)
        spell = spells.detect(records)[0]

        assert spell.total("precip_total") == 60.0
        assert spell.maximum("precip_total") == 30.0
        assert spell.mean("temp_max") == 36.0
        assert spell.extremely_hot_days == 3
        assert spell.tropical_nights == 3

    def test_見出しの表記(self):
        spell = spells.detect(series([10.0] * 3))[0]
        assert spell.label == "7月1日〜7月3日"

    def test_多かった天気概況を数える(self):
        records = [
            record(1, 10.0, weather_day="大雨"),
            record(2, 10.0, weather_day="大雨時々曇"),
            record(3, 10.0, weather_day="曇一時雨"),
        ]
        spell = spells.detect(records)[0]
        assert spell.weather_heads() == ["大雨", "曇"]

    def test_天気概況がなければ空(self):
        spell = spells.detect(series([10.0] * 3))[0]
        assert spell.weather_heads() == []


class TestSummaryText:
    def test_雨天期の記述(self):
        records = series([60.0] * 3, temp_max=28.0, weather_day="大雨")
        spell = spells.detect(records)[0]
        text = summary_text.describe_spell(spell)

        assert "7月1日〜7月3日（3日間）" in text
        assert "期間降水量 180.0mm" in text
        assert "大雨日 3日" in text
        assert "「大雨」" in text

    def test_乾燥期の記述(self):
        records = series([0.0] * 5, temp_max=36.0, sunshine=10.0)
        spell = spells.detect(records)[0]
        text = summary_text.describe_spell(spell)

        assert "降水なし" in text
        assert "日照 50.0時間" in text
        assert "猛暑日 5日" in text

    def test_総括は期間の推移を述べる(self):
        records = series([60.0] * 5 + [0.0] * 26, temp_max=36.0)
        detected = spells.detect(records)
        text = summary_text.overview(SAGA, summarize(SAGA, records), detected, 2026, 7)

        assert "2026年7月の佐賀は、" in text
        assert "7月1日〜7月5日" in text
        assert "集中しています" in text

    def test_降水が少ない月では集中と述べない(self):
        # 月降水量そのものが小さいと「集中」は実態を表さない
        records = series([2.0] * 3 + [0.0] * 28, temp_max=36.0)
        detected = spells.detect(records)
        text = summary_text.overview(SAGA, summarize(SAGA, records), detected, 2026, 7)

        assert "集中" not in text
        assert "分散" in text

    def test_雨天期がなければ降水量をそのまま述べる(self):
        records = series([0.0] * 31, temp_max=36.0)
        detected = spells.detect(records)
        text = summary_text.overview(SAGA, summarize(SAGA, records), detected, 2026, 7)

        assert "雨が続いた期間はなく" in text

    def test_単発の降水が散る月は集中と述べない(self):
        # 1 日ずつの降水は雨天期に育たず乾燥期に吸収されるが、
        # 月降水量としては無視できない量になりうる
        precips: list[float | None] = [0.0] * 31
        for day in (2, 6, 10, 14):
            precips[day] = 30.0
        records = series(precips, temp_max=34.0)
        detected = spells.detect(records)
        text = summary_text.overview(SAGA, summarize(SAGA, records), detected, 2026, 7)

        assert "集中" not in text
        assert "まとまった降水はなく" not in text
        assert "120.0mm" in text

    def test_1mm未満の微少な降水は降水日と数えない(self):
        precips: list[float | None] = [0.0] * 15
        precips[3] = 0.5
        spell = spells.detect(series(precips, temp_max=34.0))[0]
        text = summary_text.describe_spell(spell)

        assert "いずれも 1mm 未満" in text
        assert "降水日 0日" not in text

    def test_乾燥期でも降った分は示す(self):
        # 「雨が続かなかった」であって「降らなかった」ではない
        precips: list[float | None] = [0.0] * 15
        precips[3] = 40.0
        records = series(precips, temp_max=34.0)
        spell = spells.detect(records)[0]
        text = summary_text.describe_spell(spell)

        assert spell.kind == spells.DRY
        assert "期間降水量 40.0mm" in text
        assert "降水日 1日" in text
        assert "まとまった降水なし" not in text

    def test_対比は雨天期の長さと降水量に触れる(self):
        current = series([60.0] * 6 + [0.0] * 25, temp_max=36.0)
        previous = series([0.0] * 31, temp_max=36.0)
        text = summary_text.contrast(
            spells.detect(current),
            spells.detect(previous),
            summarize(SAGA, current),
            summarize(SAGA, previous),
            2026,
            2025,
        )

        assert "雨天期の長さ" in text
        assert "猛暑日" in text
