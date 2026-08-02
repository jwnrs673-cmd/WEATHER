"""都道府県の定義と、気象庁「過去の気象データ検索」の府県番号(prec_no)の対応表。

ディレクトリ名やファイル名には ``slug``（例: ``41_saga``）を用いる。
先頭の数字は JIS X 0401 の都道府県コードで、全国に展開したときに
自然な順序で並ぶようにしている。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prefecture:
    """1 都道府県分の定義。"""

    jis_code: int
    """JIS X 0401 の都道府県コード（佐賀県なら 41）。"""

    name: str
    """正式名称（例: 「佐賀県」）。"""

    short_name: str
    """「県」を除いた呼称（例: 「佐賀」）。見出しなどに使う。"""

    romaji: str
    """ディレクトリ名に使うローマ字表記。"""

    prec_no: int
    """気象庁「過去の気象データ検索」の府県番号。"""

    representative_block_no: str
    """県を代表する地方気象台の観測所番号。

    地点探索に失敗したときのフォールバックとして用いる。実際に使う地点は
    原則 :mod:`weather_report.stations` が気象庁のページから自動取得する。
    """

    @property
    def slug(self) -> str:
        """``41_saga`` 形式のディレクトリ名。"""
        return f"{self.jis_code:02d}_{self.romaji}"


#: 九州 7 県。``prec_no`` は気象庁の府県選択ページで使われている番号。
KYUSHU: tuple[Prefecture, ...] = (
    Prefecture(40, "福岡県", "福岡", "fukuoka", 82, "47807"),
    Prefecture(41, "佐賀県", "佐賀", "saga", 85, "47813"),
    Prefecture(42, "長崎県", "長崎", "nagasaki", 84, "47817"),
    Prefecture(43, "熊本県", "熊本", "kumamoto", 86, "47819"),
    Prefecture(44, "大分県", "大分", "oita", 83, "47815"),
    Prefecture(45, "宮崎県", "宮崎", "miyazaki", 87, "47830"),
    Prefecture(46, "鹿児島県", "鹿児島", "kagoshima", 88, "47827"),
)

#: 沖縄県。「九州・沖縄地方」として扱いたいときに ``--region kyushu-okinawa`` で加わる。
OKINAWA = Prefecture(47, "沖縄県", "沖縄", "okinawa", 91, "47936")

ALL: tuple[Prefecture, ...] = KYUSHU + (OKINAWA,)

REGIONS: dict[str, tuple[Prefecture, ...]] = {
    "kyushu": KYUSHU,
    "kyushu-okinawa": ALL,
}


def resolve(name: str) -> Prefecture:
    """県名・ローマ字・JIS コードのいずれからでも :class:`Prefecture` を引く。

    「佐賀県」「佐賀」「saga」「41」のすべてを受け付ける。
    """
    key = name.strip()
    for pref in ALL:
        if key in (pref.name, pref.short_name, pref.romaji, str(pref.jis_code)):
            return pref
    known = "、".join(p.name for p in ALL)
    raise KeyError(f"未知の都道府県です: {name!r}（対応: {known}）")


def resolve_many(names: list[str]) -> list[Prefecture]:
    """県名のリスト、または地方名 1 つを :class:`Prefecture` のリストに変換する。"""
    if len(names) == 1 and names[0] in REGIONS:
        return list(REGIONS[names[0]])
    return [resolve(n) for n in names]
