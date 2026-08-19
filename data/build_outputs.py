# -*- coding: utf-8 -*-
"""figures_data.py から JSON と Markdown を生成する。"""
import sys, json, os
from collections import Counter, defaultdict

sys.path.insert(0, '/home/user/CName-1/data')
from figures_data import FIGURES

OUT = "/mnt/user-data/outputs"
os.makedirs(OUT, exist_ok=True)

# 誤帰属フレーズの逐語を含む照合用リストの出力先。
# AIサービスのコーパス取り込み対象（outputs/）から意図的に分離している。
DOCS = "/home/user/CName-1/docs"
os.makedirs(DOCS, exist_ok=True)

# ---- DB投入用スキーマに整形 ----
CORE = ["id", "name", "name_en", "era", "nationality", "field", "worry_tags",
        "struggle", "bio_summary", "achievement", "quote", "quote_background",
        "fame_tier", "sources"]
EXTRA = ["quote_source_status", "notes", "quote_alt", "quote_alt_source_status",
         "quote_alt_background", "quote_alt_source"]

records = []
for f in FIGURES:
    rec = {k: f.get(k) for k in CORE}
    for k in EXTRA:
        if f.get(k):
            rec[k] = f[k]
    records.append(rec)

with open(os.path.join(OUT, "great_figures.json"), "w", encoding="utf-8") as fp:
    json.dump(records, fp, ensure_ascii=False, indent=2)
    fp.write("\n")

# ---- スキーマ定義も別ファイルで出す ----
schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "great_figure",
    "type": "object",
    "required": ["id", "name", "era", "nationality", "field", "worry_tags",
                 "struggle", "bio_summary", "achievement", "quote",
                 "quote_background", "fame_tier", "sources"],
    "properties": {
        "id": {"type": "string", "description": "スラッグ形式の主キー"},
        "name": {"type": "string", "description": "氏名（日本語表記）"},
        "name_en": {"type": "string", "description": "氏名（原語・英語表記）"},
        "era": {"type": "string", "description": "生没年。存命者は '1994–' 形式"},
        "nationality": {"type": "string"},
        "field": {"type": "string", "description": "分野。'大分類（小分類）' 形式"},
        "worry_tags": {
            "type": "array", "minItems": 1, "maxItems": 2,
            "items": {"enum": ["喜び／期待", "悲しみ", "怒り", "不安・恐れ",
                               "疲労・無気力", "孤独", "迷い・混乱"]},
        },
        "struggle": {"type": "string", "description": "抱えていた困難・葛藤（2〜3文）"},
        "bio_summary": {"type": "string", "description": "伝記要約（3〜5文）"},
        "achievement": {"type": "string", "description": "成し遂げたこと（2〜3文）"},
        "quote": {"type": "string", "description": "代表的な格言"},
        "quote_background": {"type": "string", "description": "格言の背景思想（1〜2文）"},
        "quote_source_status": {
            "enum": ["検証済", "要確認", "誤帰属"],
            "description": "検証済=一次/信頼できる二次資料で確認、要確認=一次出典未特定、"
                           "誤帰属=本人の言葉でないと判明（quote_alt を使うこと）",
        },
        "fame_tier": {"enum": ["超有名", "知る人ぞ知る", "マイナー"],
                      "description": "日本の一般層における人物としての認知度"},
        "sources": {"type": "array", "minItems": 1, "items": {"type": "string", "format": "uri"}},
        "notes": {"type": "string", "description": "誤帰属注意・留意事項"},
        "quote_alt": {"type": "string", "description": "quote が誤帰属の場合に使う代替引用"},
    },
}
with open(os.path.join(OUT, "great_figures.schema.json"), "w", encoding="utf-8") as fp:
    json.dump(schema, fp, ensure_ascii=False, indent=2)
    fp.write("\n")

# ---- Markdown ----
TAGS = ["喜び／期待", "悲しみ", "怒り", "不安・恐れ", "疲労・無気力", "孤独", "迷い・混乱"]
TIERS = ["超有名", "知る人ぞ知る", "マイナー"]
STATUS_MARK = {"検証済": "✅ 検証済", "要確認": "⚠️ 要確認", "誤帰属": "❌ 誤帰属"}

tier_c = Counter(f["fame_tier"] for f in FIGURES)
tag_c = Counter(t for f in FIGURES for t in f["worry_tags"])
stat_c = Counter(f["quote_source_status"] for f in FIGURES)

by_tag = defaultdict(list)
for f in FIGURES:
    for t in f["worry_tags"]:
        by_tag[t].append(f["name"])

L = []
A = L.append

A("# 偉人データベース一覧（格言AIサービス用）\n")
A("全50人。既存15人はファクトチェックのみ実施、35人を新規追加。\n")
A("| 項目 | 値 |")
A("|---|---|")
A("| 収録人数 | **50人** |")
A("| 有名度 | 超有名 %d / 知る人ぞ知る %d / マイナー %d |"
  % (tier_c["超有名"], tier_c["知る人ぞ知る"], tier_c["マイナー"]))
A("| 格言の出典状況 | ✅検証済 %d / ⚠️要確認 %d / ❌誤帰属 %d |"
  % (stat_c["検証済"], stat_c["要確認"], stat_c["誤帰属"]))
A("| 対応JSON | `great_figures.json`（スキーマ定義は `great_figures.schema.json`） |")
A("")

A("## 出典ステータスの読み方\n")
A("| 記号 | 意味 | サービスでの扱い |")
A("|---|---|---|")
A("| ✅ 検証済 | 一次資料または信頼できる二次資料で出典を確認 | そのまま使用可 |")
A("| ⚠️ 要確認 | 広く流布しているが一次出典を特定できず | 「出典不明」と併記して使用、または使用を避ける |")
A("| ❌ 誤帰属 | 本人の言葉でないことが判明 | **使用しないこと**。代替引用を用意済み |")
A("")
A("> 断定を避けた項目には本文中に「要確認」と明記しています。"
  "ハルシネーション防止のため、⚠️・❌ の格言はそのまま断定表示しないでください。\n")

A("## 悩みの軸タグ別インデックス\n")
A("| タグ | 人数 | 人物 |")
A("|---|---|---|")
for t in TAGS:
    A("| %s | %d | %s |" % (t, tag_c[t], "、".join(by_tag[t])))
A("")

A("## 有名度タグ別インデックス（日替わり演出用）\n")
for tier in TIERS:
    names = [f["name"] for f in FIGURES if f["fame_tier"] == tier]
    A("- **%s（%d人）**: %s" % (tier, len(names), "、".join(names)))
A("")

A("## 誤帰属が確認された有名格言について\n")
A("本DBに収録した6名について、世間で本人の言葉として広く流通している格言が"
  "実際には本人の発言記録を持たないことを確認しました。該当箇所は各人物の"
  "`notes` に事実関係のみ記述しています。\n")
A("誤帰属フレーズの逐語は、AIサービスのコーパスを汚染しないよう本ファイルには"
  "掲載していません。メンテナー向けの照合用リストは、取り込み対象外の "
  "`docs/DO_NOT_USE_QUOTES.md` を参照してください。\n")

A("---\n")
A("## 人物詳細（50人）\n")

for i, f in enumerate(FIGURES, 1):
    A("### %d. %s（%s）\n" % (i, f["name"], f["name_en"]))
    A("| | |")
    A("|---|---|")
    A("| 時代 | %s |" % f["era"])
    A("| 国籍 | %s |" % f["nationality"])
    A("| 分野 | %s |" % f["field"])
    A("| 悩みの軸 | %s |" % " / ".join("**%s**" % t for t in f["worry_tags"]))
    A("| 有名度 | %s |" % f["fame_tier"])
    A("")
    A("**悩み**  \n%s\n" % f["struggle"])
    A("**伝記要約**  \n%s\n" % f["bio_summary"])
    A("**成し遂げたこと**  \n%s\n" % f["achievement"])
    if f["quote_source_status"] == "誤帰属":
        A("**代表的な格言** ❌ 下記は誤帰属のため使用不可  \n> ~~%s~~\n" % f["quote"])
        A("**代替の格言** %s  \n> %s\n" % (STATUS_MARK[f["quote_alt_source_status"]], f["quote_alt"]))
        A("**格言の背景思想**  \n%s\n" % f["quote_alt_background"])
    else:
        A("**代表的な格言** %s  \n> %s\n" % (STATUS_MARK[f["quote_source_status"]], f["quote"]))
        A("**格言の背景思想**  \n%s\n" % f["quote_background"])
    if f.get("notes"):
        A("**注記**  \n%s\n" % f["notes"])
    A("**出典**  \n%s\n" % "  \n".join("- %s" % u for u in f["sources"]))
    A("")

with open(os.path.join(OUT, "great_figures.md"), "w", encoding="utf-8") as fp:
    fp.write("\n".join(L))

# ---- 誤帰属フレーズ照合用リスト（取り込み対象外・メンテナー向け） ----
# 逐語を載せる唯一のファイル。outputs/ には出さないこと。
DO_NOT_USE = [
    ("マハトマ・ガンディー", "Be the change you wish to see in the world",
     "発言記録なし。1913年『Indian Opinion』掲載の文章の要約が独り歩きしたもの"),
    ("ネルソン・マンデラ", "It always seems impossible until it's done",
     "マンデラ財団の引用データベースに記録なし。一次出典未確認"),
    ("アラン・チューリング",
     "Sometimes it is the people no one imagines anything of who do the things that no one can imagine",
     "映画『イミテーション・ゲーム』(2014) の脚本上の台詞。本人の発言記録なし"),
    ("ウォルト・ディズニー", "If you can dream it, you can do it",
     "イマジニアのトム・フィッツジェラルドがEPCOT『ホライズン』のために執筆した台詞"),
    ("チャールズ・ダーウィン", "生き残る種とは、最も強いものでも最も賢いものでもなく、変化に最もよく適応したものである",
     "著作に存在せず。1960年代の経営学者レオン・メギンソンによる要約が出典"),
]
ATTRIBUTION_CAVEAT = [
    ("モハメド・アリ", "Float like a butterfly, sting like a bee",
     "アリ本人が実際に使い広めた口上だが、考案者はセコンドのドリュー・バンディーニ・ブラウン。"
     "「誤帰属」ではなく著作者クレジットの問題であり、アリの言葉として紹介する場合はこの経緯を添えること"),
]

D = []
B = D.append
B("# 誤帰属フレーズ 照合用リスト（メンテナー向け）\n")
B("> **このファイルはAIサービスのコーパスに取り込まないでください。**  ")
B("> 誤帰属フレーズの逐語を含む唯一のファイルであり、`outputs/` 配下の")
B("> 配布物（`great_figures.json` / `great_figures.md`）からは意図的に分離しています。\n")
B("用途は、データ追加やレビューの際に「この格言は使ってよいか」を照合することです。"
  "`data/build_outputs.py` から生成されます。\n")
B("## 使用禁止（本人の発言記録がないもの）\n")
B("| 人物 | 流布している格言（逐語） | 実際 |")
B("|---|---|---|")
for who, phrase, why in DO_NOT_USE:
    B("| %s | %s | %s |" % (who, phrase, why))
B("")
B("## 帰属注意（本人は使ったが考案者が別）\n")
B("| 人物 | 該当フレーズ（逐語） | 実際 |")
B("|---|---|---|")
for who, phrase, why in ATTRIBUTION_CAVEAT:
    B("| %s | %s | %s |" % (who, phrase, why))
B("")

with open(os.path.join(DOCS, "DO_NOT_USE_QUOTES.md"), "w", encoding="utf-8") as fp:
    fp.write("\n".join(D))

print("wrote (deliverables):")
for fn in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, fn)
    print("  %-32s %8d bytes" % (fn, os.path.getsize(p)))
print("\nrecords:", len(records))
