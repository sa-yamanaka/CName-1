#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""感情ベクトル → 偉人マッチング 最小プロトタイプ（手動テスト用・UIなし）

使い方:
    python3 data/prototype_match.py                    # テストパターンを一括実行
    python3 data/prototype_match.py -i                 # 対話モード
    python3 data/prototype_match.py -n 5               # 上位5人まで表示（既定は3）
    python3 data/prototype_match.py --date 2026-08-20  # 日付を固定して実行（テスト用）
    python3 data/prototype_match.py --rotation hidden  # 表示順のtier優先を変更
    python3 data/prototype_match.py --simulate 30      # 30日間の被り頻度を集計

仕組み:
    - 入力  : 7タグそれぞれに 0〜3 の強度を持つベクトル
    - 人物  : worry_tags を同じ7次元の one-hot ベクトルに変換
    - 照合  : コサイン類似度でプールを作り、日替わりで K 人を選出

== 選出（誰を出すか）==
    「かぶりたくない」の基準を “同一入力で特定の人物が30日間に上位K人へ
    入る回数を1〜2回以内に抑える” と定義し直したことに伴い、
    fame_tier による3モード（famous / hidden / neutral）での絞り込みは撤廃した。

    1. 類似度スコアが完全に同一の人物をひとつのプールとする
       （fame_tier も quote_source_status も選出には一切影響しない）
    2. スコアの高いプールから順に、start = epoch_days % pool_size を起点として
       K人を円環的に取り出す
    3. プールがK人に満たない場合は全員を採用し、残り枠を次のプールから
       同じ方法で埋める

    start が経過日数そのものなので、プールサイズと互いに素かどうかに関わらず
    日ごとに1ずつ進み、プール全体を均等に巡回する。

== 表示順（選ばれたK人をどう並べるか）==
    選出とは独立に、その日のK人だけを次の優先順で並べ替える。
    並べ替えは誰が選ばれるかには一切影響しない。
    1. quote_source_status: 検証済 > 要確認 > 誤帰属
    2. fame_tier: 既定は「超有名 → 知る人ぞ知る → マイナー」
       --rotation で hidden（マイナー優先）/ neutral（tierを見ない）に変更可
    3. id 昇順

== 被り頻度についての注意 ==
    1人あたりの30日間の期待出現回数は 30 * K / pool_size である。
    K=3 で2回以内に収めるにはプールが45人必要だが、本DBの50人は
    18種類のタグ集合しか持たず、同一スコアのプールは最大8人しかない。
    したがって現在のデータ構造では、この基準は原理的に達成できない。
    実測値は --simulate で確認できる。
"""
import sys
import math
import argparse
import datetime
import itertools
from collections import Counter, defaultdict

sys.path.insert(0, '/home/user/CName-1/data')
from figures_data import FIGURES

# worry_tags と同一の7軸（順序がベクトルの次元順になる）
TAGS = ["喜び／期待", "悲しみ", "怒り", "不安・恐れ", "疲労・無気力", "孤独", "迷い・混乱"]
TAG_INDEX = {t: i for i, t in enumerate(TAGS)}

MIN_LEVEL, MAX_LEVEL = 0, 3

# 日本向けサービスを想定し、日付は JST で判定する
JST = datetime.timezone(datetime.timedelta(hours=9))

# 巡回の起点。ここからの経過日数でプール内の取り出し位置が決まる。
# 変更すると全ユーザーの当日の並びが変わる。
EPOCH = datetime.date(2026, 1, 1)

# 表示順1: 出典ステータスの優先順（小さいほど上位）
STATUS_RANK = {"検証済": 0, "要確認": 1, "誤帰属": 2}
STATUS_FALLBACK = 9

# 表示順2: fame_tier の優先順（小さいほど上位）。選出には影響しない。
TIER_PREFS = ["famous", "hidden", "neutral"]
DEFAULT_TIER_PREF = "famous"
TIER_PREF_LABEL = {
    "famous": "超有名を上に",
    "hidden": "マイナー・知る人ぞ知るを上に",
    "neutral": "tierで差をつけない",
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


def epoch_days(day):
    """EPOCH からの経過日数。EPOCH より前の日付は負になる。"""
    return (day - EPOCH).days


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


def score_pools(scores):
    """[(score, [figure, ...]), ...] をスコア降順で返す。

    プールは「類似度が完全に同一の全員」。fame_tier も
    quote_source_status もプールの切り方には関与しない。
    プール内は id 昇順で固定し、円環インデックスの基準とする。
    """
    query = to_vector(scores)
    scored = [(round(cosine(query, figure_vector(f)), 9), f) for f in FIGURES]
    scored.sort(key=lambda r: (-r[0], r[1]["id"]))
    pools = []
    for score, group in itertools.groupby(scored, key=lambda r: r[0]):
        pools.append((score, [f for _, f in group]))
    return pools


def select_for_day(pools, top_n, day):
    """その日に表示する top_n 人を、プールを円環的に巡回して選ぶ。

    戻り値: [(score, figure, pool_size), ...]（選出順。表示順ではない）
    """
    start = epoch_days(day)
    chosen = []
    for score, members in pools:
        remaining = top_n - len(chosen)
        if remaining <= 0:
            break
        size = len(members)
        if size <= remaining:
            chosen.extend((score, f, size) for f in members)
        else:
            offset = start % size
            chosen.extend(
                (score, members[(offset + i) % size], size)
                for i in range(remaining))
    return chosen


def display_sort(selected, tier_pref):
    """選ばれたK人だけを表示順に並べ替える。選出結果は変えない。"""
    return sorted(
        selected,
        key=lambda r: (
            -r[0],
            STATUS_RANK.get(r[1].get("quote_source_status"), STATUS_FALLBACK),
            FAME_RANK[tier_pref].get(r[1].get("fame_tier"), FAME_FALLBACK),
            r[1]["id"],
        ),
    )


def match(scores, top_n=3, tier_pref=None, day=None):
    """入力ベクトルに対して、その日の top_n 人を表示順で返す。

    戻り値: [(similarity, figure, pool_size), ...]
    pool_size はその人物が属する同スコアプールの人数。
    """
    if day is None:
        day = today_jst()
    if tier_pref is None:
        tier_pref = DEFAULT_TIER_PREF
    if tier_pref not in FAME_RANK:
        raise ValueError("未知の tier 優先: %s" % tier_pref)

    pools = score_pools(scores)
    return display_sort(select_for_day(pools, top_n, day), tier_pref)


def format_query(scores):
    active = [(t, scores.get(t, 0)) for t in TAGS if scores.get(t, 0) > 0]
    if not active:
        return "(すべて0)"
    return "、".join("%s=%d" % (t, v) for t, v in active)


def is_zero_query(scores):
    return not any(scores.get(t, 0) > 0 for t in TAGS)


def print_results(scores, top_n=3, tier_pref=None, day=None, label=None):
    if label:
        print("■ %s" % label)
    print("  入力: %s" % format_query(scores))

    if is_zero_query(scores):
        print("  → 入力が零ベクトルのため類似度を計算できません。\n")
        return

    print()
    for rank, (score, fig, pool) in enumerate(
            match(scores, top_n, tier_pref, day), 1):
        pool_note = "  ※プール%d人" % pool if pool > 1 else ""
        status = fig.get("quote_source_status", "")
        warn = "  ⚠ 出典未特定" if status == "要確認" else ""
        print("  %d位  類似度 %.3f%s" % (rank, score, pool_note))
        print("      %s（%s）" % (fig["name"], fig["era"]))
        print("      悩みの軸: %s ／ 有名度: %s ／ 出典: %s"
              % (" + ".join(fig["worry_tags"]), fig["fame_tier"], status))
        print("      格言: 「%s」%s" % (fig["quote"], warn))
        print("      背景: %s" % fig["quote_background"])
        print()


def print_header(day, tier_pref):
    print("=" * 72)
    print("感情ベクトル → 偉人マッチング プロトタイプ")
    print("対象: %d人 / タグ7軸 / 強度 %d〜%d"
          % (len(FIGURES), MIN_LEVEL, MAX_LEVEL))
    print("日付: %s（JST） / 起点 %s からの経過日数 %d"
          % (day.isoformat(), EPOCH.isoformat(), epoch_days(day)))
    print("選出: 同スコアプールを経過日数で円環巡回（tier・出典は不関与）")
    print("表示順: 出典ステータス → fame_tier(%s) → id" % TIER_PREF_LABEL[tier_pref])
    print("=" * 72)
    print()


def run_presets(top_n, tier_pref, day):
    print_header(day, tier_pref)
    for label, scores in TEST_PATTERNS:
        print_results(scores, top_n, tier_pref, day, label)
        print("-" * 72)
        print()


def simulate(top_n, tier_pref, start_day, days):
    """各プリセットについて、期間中に各人物が上位K人へ入った回数を集計する。"""
    print("=" * 72)
    print("被り頻度シミュレーション")
    print("期間: %s から %d日間 / 表示件数 K=%d"
          % (start_day.isoformat(), days, top_n))
    print("基準: 同一入力で1人あたり %d日間に 1〜2回以内" % days)
    print("=" * 72)

    violations = []
    for label, scores in TEST_PATTERNS:
        pools = score_pools(scores)
        top_pool = len(pools[0][1]) if pools else 0
        counts = Counter()
        meta = {}
        for i in range(days):
            day = start_day + datetime.timedelta(days=i)
            for score, fig, pool in select_for_day(pools, top_n, day):
                counts[fig["name"]] += 1
                meta[fig["name"]] = pool
        print()
        print("■ %s" % label)
        print("   入力: %s" % format_query(scores))
        print("   最上位プール: %d人 / 理論期待値: %.1f回 (= %d*%d/%d)"
              % (top_pool, days * top_n / top_pool, days, top_n, top_pool))
        print("   %-28s %s" % ("人物", "出現回数"))
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            mark = "  ← 基準超過" if n > 2 else ""
            print("   %-28s %3d回%s" % (name, n, mark))
            if n > 2:
                violations.append((label, name, n, meta[name]))
    return violations


def print_violations(violations, days):
    print()
    print("=" * 72)
    print("基準（%d日間で1〜2回以内）を超えた人物" % days)
    print("=" * 72)
    if not violations:
        print("なし")
        return
    print("%-26s %-22s %6s %8s" % ("シナリオ", "人物", "出現", "プール"))
    for label, name, n, pool in violations:
        print("%-26s %-22s %5d回 %6d人" % (label[:24], name, n, pool))
    print()
    print("超過件数: %d 件" % len(violations))


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


def run_interactive(top_n, tier_pref, day):
    print_header(day, tier_pref)
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
        print_results(scores, top_n, tier_pref, day, label="入力したベクトル")
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
    parser.add_argument("--rotation", choices=TIER_PREFS, default=None,
                        help="表示順のtier優先（選出には影響しない。既定: %s）"
                             % DEFAULT_TIER_PREF)
    parser.add_argument("--simulate", type=int, nargs="?", const=30, default=None,
                        metavar="DAYS",
                        help="被り頻度シミュレーションを実行（既定30日）")
    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top は1以上を指定してください")
    if args.simulate is not None and args.simulate < 1:
        parser.error("--simulate は1以上を指定してください")

    day = args.date or today_jst()
    tier_pref = args.rotation or DEFAULT_TIER_PREF

    if args.simulate is not None:
        violations = simulate(args.top, tier_pref, day, args.simulate)
        print_violations(violations, args.simulate)
    elif args.interactive:
        run_interactive(args.top, tier_pref, day)
    else:
        run_presets(args.top, tier_pref, day)


if __name__ == "__main__":
    main()
