#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""感情ベクトル → 偉人マッチング 最小プロトタイプ（手動テスト用・UIなし）

使い方:
    python3 data/prototype_match.py                    # テストパターンを一括実行
    python3 data/prototype_match.py -i                 # 対話モード
    python3 data/prototype_match.py -n 5               # 上位5人まで表示（既定は3）
    python3 data/prototype_match.py --date 2026-08-20  # 日付を固定して実行（テスト用）
    python3 data/prototype_match.py --rotation hidden  # ローテーションを直接指定

仕組み:
    - 入力  : 7タグそれぞれに 0〜3 の強度を持つベクトル
    - 人物  : worry_tags を同じ7次元の one-hot ベクトルに変換
    - 照合  : コサイン類似度 → 下記のタイブレーク順で上位N人

== 並び順（タイブレーク）==
    1. 類似度スコア（降順）
    2. quote_source_status: 検証済 > 要確認 > 誤帰属
       出典が確認できている格言を優先的に上位へ出す。
       （誤帰属は現在DB上0件だが、将来の混入に備えて最下位に置いている）
    3. fame_tier の日替わりローテーション
       日付から決まる3モードのいずれかで tier の優先順を入れ替える:
         - famous  : 超有名 → 知る人ぞ知る → マイナー
         - hidden  : マイナー → 知る人ぞ知る → 超有名
         - neutral : tier で差をつけない（4. のid順に委ねる）
       モードは JST の日付文字列の SHA-256 を 3 で割った余りで決まる。
       Python 組み込みの hash() はプロセスごとに変わる（PYTHONHASHSEED）ため
       使わず、hashlib を用いて日付が同じなら常に同じモードになるようにしている。
    4. id 昇順（最終的な決定打。実行ごとの揺れをなくす）

== スコアと同点に関する注意 ==
    本DBの50人は全員ちょうど2タグを持つため、人物ベクトルのノルムは
    全員 sqrt(2) で一定になる。したがってコサイン類似度による「順位」は
    「その人物の2タグに対応する入力強度の単純合計」と数学的に等価であり、
    現時点では正規化はスコアを 0〜1 に収める役割しか果たしていない。
    さらに50人が18種類のタグ集合しか持たないため同点が多発する
    （例: 「孤独 + 怒り」は8人が完全に同スコア）。上記2〜4はその同点集団を
    どう並べるかのルールである。

    なお 3. のローテーションは「日ごとに3通りの並びを切り替える」ものであり、
    同じ入力に対する上位N人は3パターンに限られる。真に日替わりで多様な人物を
    出したい場合は、同点集団からの巡回選択など別の仕組みが必要になる。
"""
import sys
import math
import hashlib
import argparse
import datetime
from collections import Counter

sys.path.insert(0, '/home/user/CName-1/data')
from figures_data import FIGURES

# worry_tags と同一の7軸（順序がベクトルの次元順になる）
TAGS = ["喜び／期待", "悲しみ", "怒り", "不安・恐れ", "疲労・無気力", "孤独", "迷い・混乱"]
TAG_INDEX = {t: i for i, t in enumerate(TAGS)}

MIN_LEVEL, MAX_LEVEL = 0, 3

# 日本向けサービスを想定し、日付は JST で判定する
JST = datetime.timezone(datetime.timedelta(hours=9))

# タイブレーク2: 出典ステータスの優先順（小さいほど上位）
STATUS_RANK = {"検証済": 0, "要確認": 1, "誤帰属": 2}
STATUS_FALLBACK = 9

# タイブレーク3: fame_tier の日替わりローテーション（小さいほど上位）
ROTATIONS = ["famous", "hidden", "neutral"]
ROTATION_LABEL = {
    "famous": "超有名を優先",
    "hidden": "マイナー・知る人ぞ知るを優先",
    "neutral": "tierで差をつけない（通常表示）",
}
FAME_RANK = {
    "famous": {"超有名": 0, "知る人ぞ知る": 1, "マイナー": 2},
    "hidden": {"マイナー": 0, "知る人ぞ知る": 1, "超有名": 2},
    "neutral": {"超有名": 0, "知る人ぞ知る": 0, "マイナー": 0},
}
FAME_FALLBACK = 9

# 手動テスト用のプリセット（説明, ベクトル）
TEST_PATTERNS = [
    ("理不尽への怒りと、誰にも分かってもらえない孤立",
     {"怒り": 3, "孤独": 2, "悲しみ": 1}),
    ("挑戦したい高揚感が主。少し進路に迷いもある",
     {"喜び／期待": 3, "迷い・混乱": 1}),
    ("先が見えない不安と、燃え尽きて動けない状態",
     {"不安・恐れ": 3, "疲労・無気力": 2}),
    ("大切なものを失った悲しみと、その後の孤独",
     {"悲しみ": 3, "孤独": 2}),
    ("自分が何者か分からない混乱と、それに伴う恐れ",
     {"迷い・混乱": 3, "不安・恐れ": 2}),
]


def today_jst():
    return datetime.datetime.now(JST).date()


def rotation_for_date(day):
    """日付から fame_tier ローテーションのモードを決める。

    同じ日付なら常に同じモードを返す（プロセスをまたいでも不変）。
    """
    digest = hashlib.sha256(day.isoformat().encode("utf-8")).hexdigest()
    return ROTATIONS[int(digest, 16) % len(ROTATIONS)]


def to_vector(scores):
    """{タグ名: 強度} を7次元ベクトルへ。未指定タグは0。"""
    unknown = set(scores) - set(TAGS)
    if unknown:
        raise ValueError("未知のタグ: %s" % ", ".join(sorted(unknown)))
    vec = [0.0] * len(TAGS)
    for tag, level in scores.items():
        if not MIN_LEVEL <= level <= MAX_LEVEL:
            raise ValueError("%s の強度 %r が範囲外（%d〜%d）"
                             % (tag, level, MIN_LEVEL, MAX_LEVEL))
        vec[TAG_INDEX[tag]] = float(level)
    return vec


def figure_vector(figure):
    """人物の worry_tags を one-hot ベクトルへ。"""
    vec = [0.0] * len(TAGS)
    for tag in figure["worry_tags"]:
        vec[TAG_INDEX[tag]] = 1.0
    return vec


def cosine(a, b):
    """コサイン類似度。どちらかが零ベクトルなら 0.0 を返す。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def sort_key(score, figure, mode):
    """(類似度降順, 出典ステータス, fame_tierローテーション, id) の複合キー。"""
    status = figure.get("quote_source_status")
    tier = figure.get("fame_tier")
    return (
        -score,
        STATUS_RANK.get(status, STATUS_FALLBACK),
        FAME_RANK[mode].get(tier, FAME_FALLBACK),
        figure["id"],
    )


def match(scores, top_n=3, mode=None):
    """入力ベクトルに近い人物を上位 top_n 件返す。

    mode を省略した場合は JST の当日からローテーションを決める。
    戻り値: [(similarity, figure, tied_total), ...]
    tied_total は同じ類似度を持つ人物の総数（同点集団の大きさ）。
    """
    if mode is None:
        mode = rotation_for_date(today_jst())
    if mode not in FAME_RANK:
        raise ValueError("未知のローテーション: %s" % mode)

    query = to_vector(scores)
    scored = [(cosine(query, figure_vector(f)), f) for f in FIGURES]
    scored.sort(key=lambda r: sort_key(r[0], r[1], mode))

    # スコアは浮動小数なので丸めてから同点数を数える
    tie_count = Counter(round(s, 9) for s, _ in scored)
    return [(s, f, tie_count[round(s, 9)]) for s, f in scored[:top_n]]


def format_query(scores):
    active = [(t, scores.get(t, 0)) for t in TAGS if scores.get(t, 0) > 0]
    if not active:
        return "(すべて0)"
    return "、".join("%s=%d" % (t, v) for t, v in active)


def print_results(scores, top_n=3, mode=None, label=None):
    if label:
        print("■ %s" % label)
    print("  入力: %s" % format_query(scores))

    if not any(scores.get(t, 0) > 0 for t in TAGS):
        print("  → 入力が零ベクトルのため類似度を計算できません。\n")
        return

    print()
    for rank, (score, fig, tied) in enumerate(match(scores, top_n, mode), 1):
        tie_note = "  ※同点%d人中" % tied if tied > 1 else ""
        status = fig.get("quote_source_status", "")
        warn = "  ⚠ 出典未特定" if status == "要確認" else ""
        print("  %d位  類似度 %.3f%s" % (rank, score, tie_note))
        print("      %s（%s）" % (fig["name"], fig["era"]))
        print("      悩みの軸: %s ／ 有名度: %s ／ 出典: %s"
              % (" + ".join(fig["worry_tags"]), fig["fame_tier"], status))
        print("      格言: 「%s」%s" % (fig["quote"], warn))
        print("      背景: %s" % fig["quote_background"])
        print()


def print_header(day, mode):
    print("=" * 72)
    print("感情ベクトル → 偉人マッチング プロトタイプ")
    print("対象: %d人 / タグ7軸 / 強度 %d〜%d"
          % (len(FIGURES), MIN_LEVEL, MAX_LEVEL))
    print("日付: %s（JST） / ローテーション: %s — %s"
          % (day.isoformat(), mode, ROTATION_LABEL[mode]))
    print("同点の並び: 出典ステータス（検証済>要確認） → fame_tier → id")
    print("=" * 72)
    print()


def run_presets(top_n, mode, day):
    print_header(day, mode)
    for label, scores in TEST_PATTERNS:
        print_results(scores, top_n, mode, label)
        print("-" * 72)
        print()


def ask_level(tag):
    """1タグぶんの強度を対話取得。空入力は0。EOFなら None。"""
    while True:
        try:
            raw = input("  %-8s (%d-%d) [0]: " % (tag, MIN_LEVEL, MAX_LEVEL)).strip()
        except EOFError:
            return None
        if raw == "":
            return 0
        try:
            value = int(raw)
        except ValueError:
            print("      整数を入力してください。")
            continue
        if not MIN_LEVEL <= value <= MAX_LEVEL:
            print("      %d〜%d の範囲で入力してください。" % (MIN_LEVEL, MAX_LEVEL))
            continue
        return value


def run_interactive(top_n, mode, day):
    print_header(day, mode)
    print("対話モード — 7タグの強度を 0〜%d で入力（空Enterで0）" % MAX_LEVEL)
    print("Ctrl-D で終了")
    while True:
        print()
        scores = {}
        for tag in TAGS:
            level = ask_level(tag)
            if level is None:
                print("\n終了します。")
                return
            scores[tag] = level
        print()
        print_results(scores, top_n, mode, label="入力したベクトル")
        print("-" * 72)


def parse_date(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD 形式で指定してください: %s" % text)


def main():
    parser = argparse.ArgumentParser(
        description="感情ベクトルから偉人・格言をマッチングする最小プロトタイプ")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="対話モードで自分の数値を入力してテストする")
    parser.add_argument("-n", "--top", type=int, default=3,
                        help="表示する上位件数（既定: 3）")
    parser.add_argument("--date", type=parse_date, default=None,
                        help="日付を固定して実行（YYYY-MM-DD、テスト用）")
    parser.add_argument("--rotation", choices=ROTATIONS, default=None,
                        help="fame_tierローテーションを直接指定（--date より優先）")
    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top は1以上を指定してください")

    day = args.date or today_jst()
    mode = args.rotation or rotation_for_date(day)

    if args.interactive:
        run_interactive(args.top, mode, day)
    else:
        run_presets(args.top, mode, day)


if __name__ == "__main__":
    main()
