#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""感情ベクトル → 偉人マッチング 最小プロトタイプ（手動テスト用・UIなし）

使い方:
    python3 data/prototype_match.py                    # テストパターンを一括実行
    python3 data/prototype_match.py -i                 # 対話モード
    python3 data/prototype_match.py -n 5               # 上位5人まで表示（既定は3）
    python3 data/prototype_match.py --pool 20          # プールを類似度上位20人に
    python3 data/prototype_match.py --date 2026-08-20  # 日付を固定して実行（テスト用）
    python3 data/prototype_match.py --rotation hidden  # 表示順のtier優先を変更
    python3 data/prototype_match.py --simulate 30      # 単一Nでの被り頻度を集計
    python3 data/prototype_match.py --compare 30       # シナリオ×N のマトリクス

仕組み:
    - 入力  : 7タグそれぞれに 0〜3 の強度を持つベクトル
    - 人物  : worry_tags を重み付き7次元ベクトルに変換（主軸=2 / 副軸=1）
    - 照合  : コサイン類似度の上位N人をプールとし、日替わりで K 人を選出

== 人物ベクトルの重み付け ==
    worry_tags の並び順を主軸→副軸とみなし、TAG_WEIGHTS = [2, 1] を割り当てる。
    従来のバイナリ(1/1)では順不同のタグ集合18種類しか区別できなかったが、
    重み付けにより順序を区別した24種類まで解像度が上がる。

    【注意】figures_data.py の worry_tags は、主軸/副軸を意識して並べたもの
    ではない。重みは「1番目のタグが主」という前提に依存するため、
    本番採用するなら各人物のタグ順を主軸基準で見直す必要がある。

== 選出（誰を出すか）==
    fame_tier も quote_source_status も選出には一切関与しない。

    1. 全50人を類似度降順に並べ、上位 N 人をプールとする
       （旧実装の「スコアが完全一致する同点集団」ではない）
    2. start = epoch_days % N を起点に K 人を円環的に取り出す
    3. プールが K 人未満なら全員

== 表示順（選ばれたK人をどう並べるか）==
    選出とは独立に、その日のK人だけを次の優先順で並べ替える。
    1. quote_source_status: 検証済 > 要確認 > 誤帰属
    2. fame_tier: 既定は「超有名 → 知る人ぞ知る → マイナー」
       --rotation で hidden / neutral に変更可
    3. id 昇順

== 被り頻度についての注意 ==
    1人あたりの平均出現回数は days * K / N まで下げられるが、
    **最大**出現回数は N を増やしても 3 で下げ止まる（K=3・30日の場合）。
    start が日ごとに1ずつ進むため、各人物は「K日連続で出続けてから
    長期間出ない」という露出のしかたになり、その連続K日が集計期間に
    入った人物が必ず K 回出るためである。

    さらに step=1 では 30日間に現れる start が30通りしかないため、
    N > 32 のプール後半は30日間で一度も表示されない。

    step を K にして窓を重ねない方式に変えると、N>=45 で最大2回に収まる
    （実測済み）。この変更は select_for_day の offset 計算1行で済むが、
    仕様変更にあたるため本コミットでは行っていない。
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

# worry_tags の並び順に対応する重み（主軸=2、副軸=1）
TAG_WEIGHTS = [2.0, 1.0]

# プール = 類似度上位N人。N の比較検証用候補と既定値。
POOL_SIZE_CANDIDATES = [10, 15, 20, 25, 30, 35, 40, 45]
DEFAULT_POOL_SIZE = 10

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
    """人物の worry_tags を重み付き7次元ベクトルへ。

    worry_tags の並び順を主軸→副軸とみなし、TAG_WEIGHTS の重みを割り当てる
    （主軸=2、副軸=1）。3個目以降があれば末尾の重みを流用する。
    """
    vec = [0.0] * len(TAGS)
    for i, tag in enumerate(figure["worry_tags"]):
        weight = TAG_WEIGHTS[min(i, len(TAG_WEIGHTS) - 1)]
        vec[TAG_INDEX[tag]] = float(weight)
    return vec


def cosine(a, b):
    """コサイン類似度。どちらかが零ベクトルなら 0.0 を返す。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def ranked_figures(scores):
    """全50人を類似度降順に並べて [(score, figure), ...] を返す。

    同スコアは id 昇順で固定し、プールの円環インデックスの基準とする。
    """
    query = to_vector(scores)
    scored = [(round(cosine(query, figure_vector(f)), 9), f) for f in FIGURES]
    scored.sort(key=lambda r: (-r[0], r[1]["id"]))
    return scored


def build_pool(scores, pool_size):
    """プール = 類似度上位 pool_size 人。

    従来の「スコアが完全一致する同点集団」ではなく、スコア順の上位N人を
    そのままプールとする。N が総人数を超える場合は全員。
    """
    if pool_size < 1:
        raise ValueError("pool_size は1以上を指定してください")
    return ranked_figures(scores)[:pool_size]


def pool_stats(pool):
    """プール内スコアの分布（最高・最低・差・平均）。"""
    if not pool:
        return {"max": 0.0, "min": 0.0, "spread": 0.0, "mean": 0.0, "size": 0}
    vals = [s for s, _ in pool]
    return {
        "max": max(vals),
        "min": min(vals),
        "spread": max(vals) - min(vals),
        "mean": sum(vals) / len(vals),
        "size": len(pool),
    }


def select_for_day(pool, top_n, day):
    """プールから、その日に表示する top_n 人を円環的に選ぶ。

    start = epoch_days % len(pool) を起点に top_n 人を取り出す。
    戻り値: [(score, figure, pool_size), ...]（選出順。表示順ではない）
    """
    size = len(pool)
    if size == 0:
        return []
    take = min(top_n, size)
    offset = epoch_days(day) % size
    return [
        (pool[(offset + i) % size][0], pool[(offset + i) % size][1], size)
        for i in range(take)
    ]


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


def match(scores, top_n=3, tier_pref=None, day=None, pool_size=None):
    """入力ベクトルに対して、その日の top_n 人を表示順で返す。

    戻り値: [(similarity, figure, pool_size), ...]
    """
    if day is None:
        day = today_jst()
    if tier_pref is None:
        tier_pref = DEFAULT_TIER_PREF
    if pool_size is None:
        pool_size = DEFAULT_POOL_SIZE
    if tier_pref not in FAME_RANK:
        raise ValueError("未知の tier 優先: %s" % tier_pref)

    pool = build_pool(scores, pool_size)
    return display_sort(select_for_day(pool, top_n, day), tier_pref)


def format_query(scores):
    active = [(t, scores.get(t, 0)) for t in TAGS if scores.get(t, 0) > 0]
    if not active:
        return "(すべて0)"
    return "、".join("%s=%d" % (t, v) for t, v in active)


def is_zero_query(scores):
    return not any(scores.get(t, 0) > 0 for t in TAGS)


def print_results(scores, top_n=3, tier_pref=None, day=None, label=None,
                  pool_size=None):
    if label:
        print("■ %s" % label)
    print("  入力: %s" % format_query(scores))

    if is_zero_query(scores):
        print("  → 入力が零ベクトルのため類似度を計算できません。\n")
        return

    print()
    for rank, (score, fig, pool) in enumerate(
            match(scores, top_n, tier_pref, day, pool_size), 1):
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


def print_header(day, tier_pref, pool_size):
    print("=" * 72)
    print("感情ベクトル → 偉人マッチング プロトタイプ")
    print("対象: %d人 / タグ7軸 / 強度 %d〜%d"
          % (len(FIGURES), MIN_LEVEL, MAX_LEVEL))
    print("日付: %s（JST） / 起点 %s からの経過日数 %d"
          % (day.isoformat(), EPOCH.isoformat(), epoch_days(day)))
    print("選出: 類似度上位%d人のプールを経過日数で円環巡回（tier・出典は不関与）"
          % pool_size)
    print("人物ベクトル: 主軸=%g / 副軸=%g の重み付き" % (TAG_WEIGHTS[0], TAG_WEIGHTS[1]))
    print("表示順: 出典ステータス → fame_tier(%s) → id" % TIER_PREF_LABEL[tier_pref])
    print("=" * 72)
    print()


def run_presets(top_n, tier_pref, day, pool_size):
    print_header(day, tier_pref, pool_size)
    for label, scores in TEST_PATTERNS:
        print_results(scores, top_n, tier_pref, day, label, pool_size)
        print("-" * 72)
        print()


def simulate_counts(scores, top_n, start_day, days, pool_size):
    """期間中に各人物が上位K人へ入った回数と、プールのスコア分布を返す。"""
    pool = build_pool(scores, pool_size)
    counts = Counter()
    for i in range(days):
        day = start_day + datetime.timedelta(days=i)
        for _, fig, _ in select_for_day(pool, top_n, day):
            counts[fig["name"]] += 1
    return counts, pool_stats(pool)


def simulate(top_n, start_day, days, pool_size):
    """単一Nでの被り頻度シミュレーション（人物ごとの内訳を表示）。"""
    print("=" * 78)
    print("被り頻度シミュレーション")
    print("期間: %s から %d日間 / 表示件数 K=%d / プール上位 N=%d"
          % (start_day.isoformat(), days, top_n, pool_size))
    print("基準: 同一入力で1人あたり %d日間に 1〜2回以内" % days)
    print("=" * 78)

    violations = []
    for label, scores in TEST_PATTERNS:
        counts, st = simulate_counts(scores, top_n, start_day, days, pool_size)
        print()
        print("■ %s" % label)
        print("   入力: %s" % format_query(scores))
        print("   プール %d人 / スコア 最高%.3f 最低%.3f 差%.3f 平均%.3f"
              % (st["size"], st["max"], st["min"], st["spread"], st["mean"]))
        print("   理論期待値: %.1f回 (= %d*%d/%d)"
              % (days * top_n / st["size"], days, top_n, st["size"]))
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            mark = "  ← 基準超過" if n > 2 else ""
            print("   %-28s %3d回%s" % (name, n, mark))
            if n > 2:
                violations.append((label, name, n, st["size"]))
    return violations


def compare_pool_sizes(top_n, start_day, days, candidates):
    """シナリオ × N のマトリクスを出力する。

    各セルで「最大出現回数」と「プール内スコアの劣化」を並べて見られるようにする。
    """
    print("=" * 78)
    print("プールサイズ N の比較（シナリオ × N）")
    print("期間: %s から %d日間 / 表示件数 K=%d" % (start_day.isoformat(), days, top_n))
    print("人物ベクトル: 主軸=%g / 副軸=%g の重み付き" % (TAG_WEIGHTS[0], TAG_WEIGHTS[1]))
    print("基準: 1人あたりの最大出現回数 <= 2")
    print("=" * 78)

    summary = []
    for label, scores in TEST_PATTERNS:
        print()
        print("■ %s" % label)
        print("   入力: %s" % format_query(scores))
        print()
        print("   %3s | %8s %8s | %7s %7s %7s %7s | %s"
              % ("N", "最大出現", "平均出現", "最高", "最低", "スコア差", "平均", "判定"))
        print("   " + "-" * 74)
        best_n = None
        for n in candidates:
            counts, st = simulate_counts(scores, top_n, start_day, days, n)
            worst = max(counts.values()) if counts else 0
            avg = sum(counts.values()) / len(counts) if counts else 0.0
            ok = worst <= 2
            if ok and best_n is None:
                best_n = st["size"]
            print("   %3d | %6d回 %7.1f回 | %7.3f %7.3f %7.3f %7.3f | %s"
                  % (st["size"], worst, avg, st["max"], st["min"],
                     st["spread"], st["mean"], "OK" if ok else "超過"))
        print()
        if best_n is None:
            print("   → 基準を満たす最小N: 候補内（最大%d）では達成できず"
                  % max(candidates))
        else:
            print("   → 基準を満たす最小N: %d" % best_n)
        summary.append((label, best_n))

    print()
    print("=" * 78)
    print("シナリオ別の最小N まとめ")
    print("=" * 78)
    for label, best_n in summary:
        print("  %-30s %s" % (label[:28],
                              ("N=%d" % best_n) if best_n else "達成不可"))
    return summary


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


def run_interactive(top_n, tier_pref, day, pool_size):
    print_header(day, tier_pref, pool_size)
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
        print_results(scores, top_n, tier_pref, day, "入力したベクトル", pool_size)
        print("-" * 72)


def parse_date(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD 形式で指定してください: %s" % text)


def print_violations(violations, days):
    print()
    print("=" * 78)
    print("基準（%d日間で1〜2回以内）を超えた人物" % days)
    print("=" * 78)
    if not violations:
        print("なし")
        return
    print("%-26s %-22s %6s %8s" % ("シナリオ", "人物", "出現", "プール"))
    for label, name, n, pool in violations:
        print("%-26s %-22s %5d回 %6d人" % (label[:24], name, n, pool))
    print()
    print("超過件数: %d 件" % len(violations))


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
    parser.add_argument("--pool", type=int, default=DEFAULT_POOL_SIZE,
                        metavar="N",
                        help="プールとする類似度上位N人（既定: %d）" % DEFAULT_POOL_SIZE)
    parser.add_argument("--simulate", type=int, nargs="?", const=30, default=None,
                        metavar="DAYS",
                        help="単一Nでの被り頻度シミュレーション（既定30日）")
    parser.add_argument("--compare", type=int, nargs="?", const=30, default=None,
                        metavar="DAYS",
                        help="シナリオ×N のマトリクスを出力（既定30日）")
    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top は1以上を指定してください")
    if args.pool < 1:
        parser.error("--pool は1以上を指定してください")
    if args.simulate is not None and args.simulate < 1:
        parser.error("--simulate は1以上を指定してください")
    if args.compare is not None and args.compare < 1:
        parser.error("--compare は1以上を指定してください")

    day = args.date or today_jst()
    tier_pref = args.rotation or DEFAULT_TIER_PREF

    if args.compare is not None:
        compare_pool_sizes(args.top, day, args.compare, POOL_SIZE_CANDIDATES)
    elif args.simulate is not None:
        violations = simulate(args.top, day, args.simulate, args.pool)
        print_violations(violations, args.simulate)
    elif args.interactive:
        run_interactive(args.top, tier_pref, day, args.pool)
    else:
        run_presets(args.top, tier_pref, day, args.pool)


if __name__ == "__main__":
    main()
