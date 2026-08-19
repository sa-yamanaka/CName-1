#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""7日間ストーリー ステートマシン・プロトタイプ（1ユーザー分・ローカルJSON）

1マッチが「7日間の連載」として進行する仕組みを、ユーザー1人分のセッションを
模した data/story_state.json で検証する。本番のDB設計ではなく、状態遷移の
ロジックが妥当かを確認するためのもの。

使い方:
    python3 data/story_engine.py --start                 # 対話で新しい物語を開始
    python3 data/story_engine.py --advance               # 1日進める（対話）
    python3 data/story_engine.py --status                # 現在の状態を表示
    python3 data/story_engine.py --reset                 # 状態ファイルを削除
    python3 data/story_engine.py --simulate-days 7       # 7日分の擬似入力を連続実行

シミュレーションの例:
    # 通常進行（7日で自然完了）
    python3 data/story_engine.py --simulate-days 7 --pattern same
    # 一時保存 → 翌日再開
    python3 data/story_engine.py --simulate-days 8 --pattern 0,0,2,0,0,0,0,0 \
        --on-change pause --on-resume resume
    # 中断（同じ日から翌日やり直し）
    python3 data/story_engine.py --simulate-days 8 --pattern 0,0,2,0,0,0,0,0 \
        --on-change skip
    # 中止（即座に再マッチング）
    python3 data/story_engine.py --simulate-days 8 --pattern 0,0,2,2,2,2,2,2 \
        --on-change cancel

== 状態モデル ==
    data/story_state.json に、1ユーザー分の状態を保持する。

    story.figure_id        マッチした人物のID
    story.started_date     物語の開始日（JST）
    story.current_day      1〜7。「次に表示する章」の番号
    story.status           active / paused / cancelled / completed
    story.original_vector  マッチ時に使った感情ベクトル（{タグ: 強度}）

    上記に加え、検証しやすさのために figure_name / last_advanced_date /
    day_log（章表示の履歴）と、終了した物語を積む archive を持つ。
    仕様上の必須項目は上の5つで、残りはプロトタイプ用の付加情報。

== 1日進める処理 ==
    その日の入力ベクトルと original_vector のコサイン類似度を取り、
    SIMILARITY_THRESHOLD 以上なら通常進行、未満なら「感情の変化を検知」として
    3択（一時保存 / 中断 / 中止）に分岐する。

    通常進行 : current_day の章を表示 → current_day += 1 → 7を超えたら completed
    一時保存 : status=paused（current_day は維持）
    中断     : 今日はスキップ。current_day も status も変えない
    中止     : status=cancelled にして破棄し、その場で「今日の入力ベクトル」で
               再マッチングして新しい物語を current_day=1 で作り直す

== paused からの再開 ==
    status=paused のとき、次回の「1日進める」では最初に
    「保存中の物語を再開しますか？それとも新しく占いますか？」を選ばせる。
    再開なら status=active に戻して同じ current_day から続行し、その日の入力
    ベクトルの判定に進む。新しく占うなら、その日の入力で再マッチングする。

== 章の中身 ==
    章本文は CHAPTERS のプレースホルダー。7日分の骨格（出会い→旅立ち）だけを
    置いてあり、実際の文章生成は本プロトタイプの対象外。
"""
import os
import sys
import json
import random
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prototype_match import (
    TAGS, MIN_LEVEL, MAX_LEVEL, DEFAULT_POOL_SIZE,
    cosine, to_vector, match, today_jst, format_query, is_zero_query,
    TEST_PATTERNS, parse_date,
)
from figures_data import FIGURES

FIGURE_BY_ID = {f["id"]: f for f in FIGURES}

# 状態ファイル（テスト用。gitignore 対象）
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "story_state.json")
STATE_VERSION = 1

# 1つの物語の長さ（日数）
STORY_LENGTH = 7

# 感情の変化を検知する閾値。これ未満なら「別の感情に移った」とみなす。
# 仮値であり、実データを見ながら調整する前提の変数。
SIMILARITY_THRESHOLD = 0.3

STATUS_ACTIVE = "active"
STATUS_PAUSED = "paused"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"
ALL_STATUSES = (STATUS_ACTIVE, STATUS_PAUSED, STATUS_CANCELLED, STATUS_COMPLETED)

# 変化検知時の3択
CHOICE_PAUSE = "pause"    # a. 一時保存
CHOICE_SKIP = "skip"      # b. 中断
CHOICE_CANCEL = "cancel"  # c. 中止
CHOICE_LABEL = {
    CHOICE_PAUSE: "a. 一時保存",
    CHOICE_SKIP: "b. 中断",
    CHOICE_CANCEL: "c. 中止",
}

# paused からの2択
RESUME_CONTINUE = "resume"
RESUME_NEW = "new"

# 7日分の章。プレースホルダー（本文生成はプロトタイプの対象外）
CHAPTERS = [
    ("出会い", "{name} の人生が、あなたの「{axis}」と交わる地点。"),
    ("兆し", "{name} が最初の違和感に気づいた頃の話。"),
    ("揺らぎ", "{name} がもっとも迷っていた時期。この時点で「{quote}」はまだ無い。"),
    ("対峙", "{name} が避け続けたものと向き合う章。{struggle}"),
    ("転回", "{name} の選択が反転する。7日間の折り返し点。"),
    ("手渡し", "「{quote}」が生まれた日。{background}"),
    ("旅立ち", "{name} の物語はここで終わり、続きはあなたのものになる。"),
]


# ---------------------------------------------------------------- 状態の入出力

def default_state():
    return {"version": STATE_VERSION, "story": None, "archive": []}


def load_state():
    """状態ファイルを読む。無ければ初期状態を返す。"""
    if not os.path.exists(STATE_PATH):
        return default_state()
    with open(STATE_PATH, encoding="utf-8") as fh:
        try:
            state = json.load(fh)
        except ValueError as exc:
            raise SystemExit("状態ファイルが壊れています（%s）: %s" % (STATE_PATH, exc))
    if not isinstance(state, dict) or "story" not in state:
        raise SystemExit("状態ファイルの形式が不正です: %s" % STATE_PATH)
    state.setdefault("version", STATE_VERSION)
    state.setdefault("archive", [])
    validate_story(state["story"])
    return state


def validate_story(story):
    if story is None:
        return
    required = ("figure_id", "started_date", "current_day", "status",
                "original_vector")
    missing = [k for k in required if k not in story]
    if missing:
        raise SystemExit("状態ファイルに必須項目がありません: %s" % ", ".join(missing))
    if story["status"] not in ALL_STATUSES:
        raise SystemExit("未知の status: %s" % story["status"])
    if not 1 <= story["current_day"] <= STORY_LENGTH + 1:
        raise SystemExit("current_day が範囲外です: %r" % story["current_day"])


def save_state(state):
    """状態ファイルを書く（実行のたびに読み書きする前提）。"""
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def reset_state():
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
        return True
    return False


# ------------------------------------------------------------------ 物語の操作

def log(message):
    print(message)


def stamp(day, message):
    print("[%s] %s" % (day.isoformat(), message))


def normalize_scores(scores):
    """7タグすべてを明示した辞書にそろえる（保存形式を安定させる）。"""
    return {tag: int(scores.get(tag, 0)) for tag in TAGS}


def start_story(state, scores, day, pool_size, reason):
    """マッチングして新しい物語を作る（status=active / current_day=1）。

    prototype_match.match() の1位をその物語の人物とする。
    """
    if is_zero_query(scores):
        raise SystemExit("入力が零ベクトルのためマッチングできません。")
    results = match(scores, top_n=1, day=day, pool_size=pool_size)
    if not results:
        raise SystemExit("マッチする人物が見つかりませんでした。")
    score, figure, _pool = results[0]
    story = {
        "figure_id": figure["id"],
        "figure_name": figure["name"],
        "started_date": day.isoformat(),
        "current_day": 1,
        "status": STATUS_ACTIVE,
        "original_vector": normalize_scores(scores),
        "match_similarity": round(score, 4),
        "last_advanced_date": None,
        "day_log": [],
    }
    state["story"] = story
    stamp(day, "新しい物語を開始（%s）" % reason)
    log("       入力: %s" % format_query(scores))
    log("       マッチ: %s（%s） 類似度 %.3f"
        % (figure["name"], figure["era"], score))
    log("       状態: status=active / current_day=1 / started_date=%s"
        % story["started_date"])
    return story


def archive_story(state, story, reason, day):
    """終了した物語を archive に積む（検証用の履歴）。"""
    entry = dict(story)
    entry["ended_reason"] = reason
    entry["ended_date"] = day.isoformat()
    state.setdefault("archive", []).append(entry)


def similarity_to_origin(story, scores):
    """その日の入力と original_vector のコサイン類似度。"""
    return cosine(to_vector(normalize_scores(scores)),
                  to_vector(normalize_scores(story["original_vector"])))


def render_chapter(story, day_number):
    """current_day の章を表示する（本文はプレースホルダー）。"""
    figure = FIGURE_BY_ID.get(story["figure_id"])
    title, body = CHAPTERS[day_number - 1]
    if figure is None:
        text = "（人物データが見つかりません: %s）" % story["figure_id"]
        name = story.get("figure_name", story["figure_id"])
    else:
        name = figure["name"]
        text = body.format(
            name=name,
            axis=" + ".join(figure["worry_tags"]),
            quote=figure["quote"],
            background=figure["quote_background"],
            struggle=figure["struggle"],
        )
    log("       ── 第%d章「%s」（%s）" % (day_number, title, name))
    log("          %s" % text)


def progress_one_day(story, day):
    """通常進行: 章を表示して current_day を1つ進める。"""
    shown = story["current_day"]
    render_chapter(story, shown)
    story["day_log"].append({"day": shown, "date": day.isoformat()})
    story["current_day"] = shown + 1
    if story["current_day"] > STORY_LENGTH:
        story["status"] = STATUS_COMPLETED
        stamp(day, "第%d章まで到達。status=completed（7日間の連載が完了）" % STORY_LENGTH)
    else:
        stamp(day, "通常進行。current_day %d → %d" % (shown, story["current_day"]))


# ------------------------------------------------ 入力ソースと選択のインタフェース

class InteractiveInput(object):
    """7タグの強度をCLIで対話取得する。"""

    def next_scores(self, label):
        log("")
        log("%s — 7タグの強度を %d〜%d で入力（空Enterで0、Ctrl-Dで中断）"
            % (label, MIN_LEVEL, MAX_LEVEL))
        scores = {}
        for tag in TAGS:
            scores[tag] = self._ask_level(tag)
        log("  入力: %s" % format_query(scores))
        return scores

    def _ask_level(self, tag):
        while True:
            try:
                raw = input("  %-8s (%d-%d) [0]: "
                            % (tag, MIN_LEVEL, MAX_LEVEL)).strip()
            except EOFError:
                raise SystemExit("\n中断しました。")
            if raw == "":
                return 0
            try:
                value = int(raw)
            except ValueError:
                log("      整数を入力してください。")
                continue
            if not MIN_LEVEL <= value <= MAX_LEVEL:
                log("      %d〜%d の範囲で入力してください。" % (MIN_LEVEL, MAX_LEVEL))
                continue
            return value


class ScriptedInput(object):
    """プリセットのテストパターンを指定順／ランダムで流す（シミュレーション用）。"""

    def __init__(self, indices, patterns=None):
        self.indices = list(indices)
        self.patterns = patterns if patterns is not None else TEST_PATTERNS
        self.cursor = 0

    def next_scores(self, label):
        index = self.indices[self.cursor % len(self.indices)]
        self.cursor += 1
        desc, scores = self.patterns[index]
        log("  入力[パターン%d] %s" % (index, desc))
        log("       %s" % format_query(scores))
        return dict(scores)


class InteractiveResponder(object):
    """変化検知時の3択と、paused からの2択をCLIで選ばせる。"""

    def ask_change(self):
        log("")
        log("  どうしますか？")
        log("    a. 一時保存 — 物語を保存して止める（続きは後日、同じ日から）")
        log("    b. 中断     — 今日はスキップ（明日また同じ日から）")
        log("    c. 中止     — この物語を破棄して、今の気持ちで占い直す")
        mapping = {"a": CHOICE_PAUSE, "b": CHOICE_SKIP, "c": CHOICE_CANCEL}
        return self._ask("  a / b / c を選択: ", mapping)

    def ask_resume(self):
        log("")
        log("  保存中の物語があります。")
        log("    1. 再開する   — 保存した続きから読む")
        log("    2. 新しく占う — 今の気持ちで占い直す")
        mapping = {"1": RESUME_CONTINUE, "2": RESUME_NEW}
        return self._ask("  1 / 2 を選択: ", mapping)

    def _ask(self, prompt, mapping):
        while True:
            try:
                raw = input(prompt).strip().lower()
            except EOFError:
                raise SystemExit("\n中断しました。")
            if raw in mapping:
                return mapping[raw]
            log("      %s のいずれかを入力してください。"
                % " / ".join(sorted(mapping)))


class ScriptedResponder(object):
    """シミュレーション用に選択を固定する。"""

    def __init__(self, on_change, on_resume):
        self.on_change = on_change
        self.on_resume = on_resume

    def ask_change(self):
        log("  選択（自動）: %s" % CHOICE_LABEL[self.on_change])
        return self.on_change

    def ask_resume(self):
        label = "1. 再開する" if self.on_resume == RESUME_CONTINUE else "2. 新しく占う"
        log("  選択（自動）: %s" % label)
        return self.on_resume


# ------------------------------------------------------------------ 1日進める

def advance_one_day(state, source, responder, day, threshold, pool_size):
    """1日ぶんの状態遷移を行う。state を書き換えて True/False を返す。

    戻り値は「この先も進められるか」。completed / cancelled のまま
    終わった場合は False。
    """
    story = state.get("story")
    if story is None:
        stamp(day, "物語がありません。--start で開始してください。")
        return False
    if story["status"] == STATUS_COMPLETED:
        stamp(day, "この物語は完了済みです（status=completed）。"
                   "--start で新しい物語を開始してください。")
        return False
    if story["status"] == STATUS_CANCELLED:
        stamp(day, "この物語は中止済みです（status=cancelled）。"
                   "--start で新しい物語を開始してください。")
        return False

    # paused のときは、まず「再開 or 新しく占う」を選ばせる
    if story["status"] == STATUS_PAUSED:
        stamp(day, "保存中の物語を検出（status=paused / current_day=%d）"
              % story["current_day"])
        if responder.ask_resume() == RESUME_NEW:
            archive_story(state, story, "paused から新規占いへ切り替え", day)
            scores = source.next_scores("新しく占う")
            start_story(state, scores, day, pool_size, "paused からの占い直し")
            story = state["story"]
            story["last_advanced_date"] = day.isoformat()
            return True
        story["status"] = STATUS_ACTIVE
        stamp(day, "再開。status=paused → active（current_day=%d から続行）"
              % story["current_day"])

    scores = source.next_scores("第%d章を読む前の、今日の気持ち" % story["current_day"])
    similarity = similarity_to_origin(story, scores)
    if is_zero_query(scores):
        # 零ベクトルとは類似度を定義できない。cosine() は 0.0 を返すため
        # そのまま「変化検知」に落ちるが、理由が違うので明示しておく。
        stamp(day, "入力が零ベクトルのため類似度を計算できません（変化検知として扱う）")
    else:
        stamp(day, "初回ベクトルとの類似度 %.3f（閾値 %.2f）" % (similarity, threshold))

    if similarity >= threshold:
        progress_one_day(story, day)
        story["last_advanced_date"] = day.isoformat()
        return story["status"] == STATUS_ACTIVE

    # 閾値未満 → 感情の変化を検知
    stamp(day, "⚠ 感情の変化を検知しました。")
    log("       前回までの気持ち: %s" % format_query(story["original_vector"]))
    log("       今日の気持ち    : %s" % format_query(scores))
    log("       今の物語（%s・第%d章）は、今日の気持ちとは違う方向に進んでいます。"
        % (story.get("figure_name", story["figure_id"]), story["current_day"]))

    choice = responder.ask_change()
    if choice == CHOICE_PAUSE:
        story["status"] = STATUS_PAUSED
        story["last_advanced_date"] = day.isoformat()
        stamp(day, "一時保存。status=active → paused（current_day=%d を維持）"
              % story["current_day"])
        return True
    if choice == CHOICE_SKIP:
        story["last_advanced_date"] = day.isoformat()
        stamp(day, "中断。今日はスキップ（current_day=%d のまま / status=%s のまま）"
              % (story["current_day"], story["status"]))
        return True

    # 中止 → 破棄して、その場で「今日の入力ベクトル」で再マッチング
    story["status"] = STATUS_CANCELLED
    stamp(day, "中止。status=active → cancelled（第%d章で破棄）" % story["current_day"])
    archive_story(state, story, "ユーザーが中止を選択", day)
    start_story(state, scores, day, pool_size, "中止直後の再マッチング")
    state["story"]["last_advanced_date"] = day.isoformat()
    return True


# ------------------------------------------------------------------ コマンド

def cmd_status(state):
    story = state.get("story")
    print("=" * 72)
    print("story_state: %s" % STATE_PATH)
    print("=" * 72)
    if story is None:
        print("物語はまだありません。--start で開始してください。")
    else:
        figure = FIGURE_BY_ID.get(story["figure_id"])
        print("  figure_id       : %s（%s）"
              % (story["figure_id"], figure["name"] if figure else "?"))
        print("  started_date    : %s" % story["started_date"])
        if story["status"] == STATUS_COMPLETED:
            print("  current_day     : %d（%d章すべて表示済み）"
                  % (story["current_day"], STORY_LENGTH))
        else:
            print("  current_day     : %d / %d（次に表示する章）"
                  % (story["current_day"], STORY_LENGTH))
        print("  status          : %s" % story["status"])
        print("  original_vector : %s" % format_query(story["original_vector"]))
        print("  最終実行日      : %s" % (story.get("last_advanced_date") or "-"))
        read = [str(d["day"]) for d in story.get("day_log", [])]
        print("  表示済みの章    : %s" % (", ".join(read) if read else "なし"))
    archive = state.get("archive", [])
    if archive:
        print()
        print("  過去の物語: %d件" % len(archive))
        for entry in archive:
            print("    - %s（%s / 第%d章まで / %s）"
                  % (entry.get("figure_name", entry["figure_id"]),
                     entry["status"], entry["current_day"], entry["ended_reason"]))
    print()


def cmd_start(day, pool_size):
    state = load_state()
    if state.get("story") and state["story"]["status"] in (STATUS_ACTIVE,
                                                           STATUS_PAUSED):
        stamp(day, "進行中の物語があります（status=%s / current_day=%d）。"
              % (state["story"]["status"], state["story"]["current_day"]))
        log("       上書きする場合は --reset のうえで実行してください。")
        return
    if state.get("story"):
        archive_story(state, state["story"], "新しい物語の開始により終了", day)
    scores = InteractiveInput().next_scores("今の気持ち")
    start_story(state, scores, day, pool_size, "--start")
    save_state(state)


def cmd_advance(day, threshold, pool_size):
    state = load_state()
    advance_one_day(state, InteractiveInput(), InteractiveResponder(),
                    day, threshold, pool_size)
    save_state(state)


def parse_pattern_spec(spec, days, start_pattern, seed, count):
    """--pattern の指定を、日ごとのパターン番号リストへ変換する。

    same        : 毎日 --start-pattern と同じパターン（＝類似度1.0で通常進行）
    random      : --seed 付きの疑似乱数で選ぶ
    "0,2,0,..." : 指定順（日数を超えたら循環）
    """
    if spec == "same":
        return [start_pattern] * days
    if spec == "random":
        rng = random.Random(seed)
        return [rng.randrange(count) for _ in range(days)]
    try:
        indices = [int(x) for x in spec.split(",") if x.strip() != ""]
    except ValueError:
        raise SystemExit("--pattern は same / random / 0,2,1 形式で指定してください: %s"
                         % spec)
    if not indices:
        raise SystemExit("--pattern が空です。")
    for i in indices:
        if not 0 <= i < count:
            raise SystemExit("パターン番号 %d は範囲外です（0〜%d）" % (i, count - 1))
    return indices


def cmd_simulate(days, spec, start_pattern, seed, on_change, on_resume,
                 start_day, threshold, pool_size):
    """N日分の擬似入力を連続実行し、状態遷移をログ表示する。

    再現性のため、状態ファイルを初期化してから開始する。
    毎日 load_state() → 遷移 → save_state() を通し、JSONの往復も検証する。
    """
    print("=" * 78)
    print("7日間ストーリー 状態遷移シミュレーション")
    print("期間  : %s から %d日間" % (start_day.isoformat(), days))
    print("入力  : --pattern %s（初期マッチはパターン%d）" % (spec, start_pattern))
    print("選択  : 変化検知時=%s / 再開時=%s" % (on_change, on_resume))
    print("閾値  : %.2f / プール上位 %d人 / 連載 %d日"
          % (threshold, pool_size, STORY_LENGTH))
    print("状態  : %s（毎日 読み込み→遷移→書き出し）" % STATE_PATH)
    print("=" * 78)
    print()
    print("--- プリセットのテストパターン ---")
    for i, (desc, scores) in enumerate(TEST_PATTERNS):
        print("  パターン%d: %s" % (i, desc))
        print("            %s" % format_query(scores))
    print()

    reset_state()
    indices = parse_pattern_spec(spec, days, start_pattern, seed,
                                 len(TEST_PATTERNS))

    # 初期マッチング（--start 相当）
    state = load_state()
    desc, scores = TEST_PATTERNS[start_pattern]
    print("=== Day 0: 初期マッチング ===")
    log("  入力[パターン%d] %s" % (start_pattern, desc))
    start_story(state, dict(scores), start_day, pool_size, "シミュレーション開始")
    save_state(state)

    source = ScriptedInput(indices)
    responder = ScriptedResponder(on_change, on_resume)

    for i in range(days):
        day = start_day + datetime.timedelta(days=i)
        print()
        print("=== Day %d (%s) ===" % (i + 1, day.isoformat()))
        state = load_state()          # 毎回ファイルから読み直す
        before = snapshot(state)
        cont = advance_one_day(state, source, responder, day, threshold,
                               pool_size)
        save_state(state)             # 毎回ファイルへ書き戻す
        after = snapshot(state)
        print("       状態: %s → %s" % (before, after))
        if not cont:
            print()
            print("これ以上進められないため終了します（残り %d日分は未実行）"
                  % (days - i - 1))
            break

    print()
    print("=" * 78)
    print("最終状態")
    print("=" * 78)
    cmd_status(load_state())


def snapshot(state):
    story = state.get("story")
    if story is None:
        return "(物語なし)"
    return "%s/day=%d/%s" % (story["figure_id"], story["current_day"],
                             story["status"])


def main():
    parser = argparse.ArgumentParser(
        description="7日間ストーリーの状態遷移プロトタイプ（1ユーザー分）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--start", action="store_true",
                      help="対話で入力して新しい物語を開始する")
    mode.add_argument("--advance", action="store_true",
                      help="1日進める（対話）")
    mode.add_argument("--status", action="store_true",
                      help="現在の story_state.json を表示する")
    mode.add_argument("--reset", action="store_true",
                      help="story_state.json を削除する")
    mode.add_argument("--simulate-days", type=int, default=None, metavar="N",
                      help="N日分の擬似入力を連続実行する（状態ファイルは初期化される）")

    parser.add_argument("--pattern", default="same", metavar="SPEC",
                        help="シミュレーションの入力パターン: same / random / "
                             "0,2,1 のような指定順（既定: same）")
    parser.add_argument("--start-pattern", type=int, default=0, metavar="IDX",
                        help="初期マッチングに使うパターン番号（既定: 0）")
    parser.add_argument("--seed", type=int, default=0,
                        help="--pattern random の乱数シード（既定: 0）")
    parser.add_argument("--on-change", choices=[CHOICE_PAUSE, CHOICE_SKIP,
                                                CHOICE_CANCEL],
                        default=CHOICE_PAUSE,
                        help="シミュレーション時、変化検知の3択で選ぶもの（既定: pause）")
    parser.add_argument("--on-resume", choices=[RESUME_CONTINUE, RESUME_NEW],
                        default=RESUME_CONTINUE,
                        help="シミュレーション時、paused からの2択で選ぶもの（既定: resume）")
    parser.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD,
                        metavar="F",
                        help="感情の変化を検知する類似度の閾値（既定: %.2f）"
                             % SIMILARITY_THRESHOLD)
    parser.add_argument("--pool", type=int, default=DEFAULT_POOL_SIZE,
                        metavar="N",
                        help="マッチングのプール上位N人（既定: %d）" % DEFAULT_POOL_SIZE)
    parser.add_argument("--date", type=parse_date, default=None,
                        help="基準日を固定して実行（YYYY-MM-DD、テスト用）")
    args = parser.parse_args()

    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold は 0.0〜1.0 で指定してください")
    if args.pool < 1:
        parser.error("--pool は1以上を指定してください")
    if not 0 <= args.start_pattern < len(TEST_PATTERNS):
        parser.error("--start-pattern は 0〜%d で指定してください"
                     % (len(TEST_PATTERNS) - 1))
    if args.simulate_days is not None and args.simulate_days < 1:
        parser.error("--simulate-days は1以上を指定してください")

    day = args.date or today_jst()

    if args.reset:
        print("状態ファイルを削除しました。" if reset_state()
              else "状態ファイルはありません。")
    elif args.status:
        cmd_status(load_state())
    elif args.start:
        cmd_start(day, args.pool)
    elif args.advance:
        cmd_advance(day, args.threshold, args.pool)
    elif args.simulate_days is not None:
        cmd_simulate(args.simulate_days, args.pattern, args.start_pattern,
                     args.seed, args.on_change, args.on_resume, day,
                     args.threshold, args.pool)
    else:
        cmd_status(load_state())
        print("使い方: --start / --advance / --status / --reset / "
              "--simulate-days N")


if __name__ == "__main__":
    main()
