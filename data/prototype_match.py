#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""感情ベクトル → 偉人マッチング 最小プロトタイプ（手動テスト用・UIなし）

使い方:
    python3 data/prototype_match.py          # 用意したテストパターンを一括実行
    python3 data/prototype_match.py -i       # 対話モード（7タグの強度を自分で入力）
    python3 data/prototype_match.py -n 5     # 上位5人まで表示（既定は3）

仕組み:
    - 入力  : 7タグそれぞれに 0〜3 の強度を持つベクトル
    - 人物  : worry_tags を同じ7次元の one-hot ベクトルに変換
    - 照合  : コサイン類似度の降順で上位N人

【スコアの読み方に関する注意】
    本DBの50人は全員ちょうど2タグを持つため、人物ベクトルのノルムは
    全員 sqrt(2) で一定になる。したがってコサイン類似度による「順位」は
    「その人物の2タグに対応する入力強度の単純合計」と数学的に等価であり、
    現時点では正規化はスコアを 0〜1 に収める役割しか果たしていない。
    さらに50人が18種類のタグ集合しか持たないため同点が多発する
    （例: 「孤独 + 怒り」は8人が完全に同スコア）。
    そのため上位N人は同点集団からの決定的な切り出しにすぎない。
    本スクリプトは同点数を併記し、順位は (スコア降順, id昇順) で
    再現可能に固定している。
"""
import sys
import math
import argparse
from collections import Counter

sys.path.insert(0, '/home/user/CName-1/data')
from figures_data import FIGURES

# worry_tags と同一の7軸（順序がベクトルの次元順になる）
TAGS = ["喜び／期待", "悲しみ", "怒り", "不安・恐れ", "疲労・無気力", "孤独", "迷い・混乱"]
TAG_INDEX = {t: i for i, t in enumerate(TAGS)}

MIN_LEVEL, MAX_LEVEL = 0, 3

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


def match(scores, top_n=3):
    """入力ベクトルに近い人物を上位 top_n 件返す。

    戻り値: [(similarity, figure, tied_total), ...]
    tied_total は同じスコアを持つ人物の総数（同点集団の大きさ）。
    """
    query = to_vector(scores)
    ranked = []
    for fig in FIGURES:
        ranked.append((cosine(query, figure_vector(fig)), fig))

    # 同点は id 昇順で決定的に並べる（実行ごとに順位が揺れないように）
    ranked.sort(key=lambda r: (-r[0], r[1]["id"]))

    # スコアは浮動小数なので丸めてから同点数を数える
    tie_count = Counter(round(s, 9) for s, _ in ranked)
    return [(s, f, tie_count[round(s, 9)]) for s, f in ranked[:top_n]]


def format_query(scores):
    active = [(t, scores.get(t, 0)) for t in TAGS if scores.get(t, 0) > 0]
    if not active:
        return "(すべて0)"
    return "、".join("%s=%d" % (t, v) for t, v in active)


def print_results(scores, top_n=3, label=None):
    if label:
        print("■ %s" % label)
    print("  入力: %s" % format_query(scores))

    if not any(scores.get(t, 0) > 0 for t in TAGS):
        print("  → 入力が零ベクトルのため類似度を計算できません。\n")
        return

    results = match(scores, top_n)
    print()
    for rank, (score, fig, tied) in enumerate(results, 1):
        tie_note = "  ※同点%d人中" % tied if tied > 1 else ""
        print("  %d位  類似度 %.3f%s" % (rank, score, tie_note))
        print("      %s（%s）" % (fig["name"], fig["era"]))
        print("      悩みの軸: %s ／ 有名度: %s"
              % (" + ".join(fig["worry_tags"]), fig["fame_tier"]))
        status = fig.get("quote_source_status", "")
        warn = "  ⚠ 出典未特定" if status == "要確認" else ""
        print("      格言: 「%s」%s" % (fig["quote"], warn))
        print("      背景: %s" % fig["quote_background"])
        print()


def run_presets(top_n):
    print("=" * 72)
    print("感情ベクトル → 偉人マッチング プロトタイプ")
    print("対象: %d人 / タグ7軸 / 強度 %d〜%d"
          % (len(FIGURES), MIN_LEVEL, MAX_LEVEL))
    print("=" * 72)
    print()
    for label, scores in TEST_PATTERNS:
        print_results(scores, top_n, label)
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


def run_interactive(top_n):
    print("=" * 72)
    print("対話モード — 7タグの強度を 0〜%d で入力（空Enterで0）" % MAX_LEVEL)
    print("Ctrl-D で終了")
    print("=" * 72)
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
        print_results(scores, top_n, label="入力したベクトル")
        print("-" * 72)


def main():
    parser = argparse.ArgumentParser(
        description="感情ベクトルから偉人・格言をマッチングする最小プロトタイプ")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="対話モードで自分の数値を入力してテストする")
    parser.add_argument("-n", "--top", type=int, default=3,
                        help="表示する上位件数（既定: 3）")
    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top は1以上を指定してください")

    if args.interactive:
        run_interactive(args.top)
    else:
        run_presets(args.top)


if __name__ == "__main__":
    main()
