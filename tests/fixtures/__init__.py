"""テスト用の合成 HTML を組み立てるヘルパー。

**重要**: ここで作る HTML は気象庁の実ページを参考にした「模擬」であり、
実物そのものではない。列数と値の記法という、パーサが依存している構造だけを
再現している。実ページに対する検証は
:doc:`docs/data_source` の手順で別途行うこと。
"""

from __future__ import annotations

#: 官署 (daily_s1) の 21 列。1 行分のセルを並べたもの。
OFFICIAL_ROW_WIDTH = 21

#: アメダス (daily_a1) の 16 列。
AMEDAS_ROW_WIDTH = 16


def build_daily_table(rows: list[list[str]], *, table_id: str = "tablefix1") -> str:
    """日別値ページを模した HTML を組み立てる。

    パーサは「先頭セルが 1〜31」「セル 10 個以上」で行を選ぶので、
    見出し行を混ぜても無視されることを確認できる形にしてある。
    """
    body = []
    # 見出し（先頭セルが数字でないので、パーサは読み飛ばすはず）
    body.append(
        "<tr>" + "".join(f"<th>col{i}</th>" for i in range(len(rows[0]))) + "</tr>"
    )
    for row in rows:
        body.append("<tr class='mtx'>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    return (
        "<html><body>"
        f"<table id='{table_id}'>{''.join(body)}</table>"
        "</body></html>"
    )


def official_row(
    day: int,
    *,
    precip: str = "0.0",
    precip_1h: str = "0.0",
    temp_mean: str = "28.0",
    temp_max: str = "32.0",
    temp_min: str = "24.0",
    humidity_mean: str = "75",
    humidity_min: str = "55",
    wind_mean: str = "2.5",
    wind_max: str = "6.1",
    wind_max_dir: str = "南",
    gust: str = "11.2",
    gust_dir: str = "南南西",
    sunshine: str = "8.0",
    weather_day: str = "晴",
    weather_night: str = "晴",
) -> list[str]:
    """官署の 1 行（21 セル）を作る。"""
    return [
        str(day),
        "1008.5",  # 現地気圧
        "1009.9",  # 海面気圧
        precip,
        precip_1h,
        "0.0",  # 最大10分間降水量
        temp_mean,
        temp_max,
        temp_min,
        humidity_mean,
        humidity_min,
        wind_mean,
        wind_max,
        wind_max_dir,
        gust,
        gust_dir,
        sunshine,
        "--",  # 降雪
        "--",  # 積雪
        weather_day,
        weather_night,
    ]


def amedas_row(
    day: int,
    *,
    precip: str = "0.0",
    temp_max: str = "31.5",
    temp_min: str = "23.0",
    gust: str = "9.8",
) -> list[str]:
    """アメダスの 1 行（16 セル）を作る。"""
    return [
        str(day),
        precip,
        "0.0",  # 最大1時間
        "0.0",  # 最大10分間
        "27.5",  # 平均気温
        temp_max,
        temp_min,
        "2.0",  # 平均風速
        "5.5",  # 最大風速
        "北西",
        gust,
        "西北西",
        "南",  # 最多風向
        "7.5",  # 日照時間
        "--",  # 降雪
        "--",  # 積雪
    ]


def build_prefecture_page(entries: list[tuple[str, str, str]]) -> str:
    """府県地図ページを模した HTML を作る。

    ``entries`` は ``(kind, block_no, name)`` の並び。
    """
    areas = []
    for kind, block_no, name in entries:
        areas.append(
            f"<area shape='circle' coords='1,2,3' "
            f"onmouseover=\"viewPoint('{kind}','{block_no}','romaji','{name}',"
            f"'33','15','130','18');\" "
            f"href='../view/daily_{kind}1.php?prec_no=85&block_no={block_no}"
            f"&year=&month=&day=&view='>"
        )
    return "<html><body><map name='point'>" + "".join(areas) + "</map></body></html>"
