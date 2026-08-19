# -*- coding: utf-8 -*-
"""figures_data.py のスキーマ検証と文字混入チェック"""
import sys, re, unicodedata
from collections import Counter

sys.path.insert(0, '/home/user/CName-1/data')
from figures_data import FIGURES

REQ = ["id", "name", "era", "nationality", "field", "worry_tags", "struggle",
       "bio_summary", "achievement", "quote", "quote_background", "fame_tier", "sources"]
TAGS = {"喜び／期待", "悲しみ", "怒り", "不安・恐れ", "疲労・無気力", "孤独", "迷い・混乱"}
TIERS = {"超有名", "知る人ぞ知る", "マイナー"}
STAT = {"検証済", "要確認", "誤帰属"}

# 許容するUnicodeスクリプト名の断片（日本語・ラテン・記号）
BAD_SCRIPTS = ("CYRILLIC", "GREEK", "ARABIC", "HEBREW", "HANGUL", "THAI", "DEVANAGARI")


def script_ok(ch):
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return True
    return not any(s in name for s in BAD_SCRIPTS)


errs = []
for f in FIGURES:
    fid = f.get("id", "?")
    for k in REQ:
        if k not in f or f[k] in ("", [], None):
            errs.append("%s: missing/empty %s" % (fid, k))
    bad = set(f.get("worry_tags", [])) - TAGS
    if bad:
        errs.append("%s: bad tags %s" % (fid, bad))
    if not 1 <= len(f.get("worry_tags", [])) <= 2:
        errs.append("%s: tag count %d" % (fid, len(f.get("worry_tags", []))))
    if f.get("fame_tier") not in TIERS:
        errs.append("%s: bad fame_tier %r" % (fid, f.get("fame_tier")))
    if f.get("quote_source_status") not in STAT:
        errs.append("%s: bad quote_source_status %r" % (fid, f.get("quote_source_status")))
    for u in f.get("sources", []):
        if not u.startswith("https://"):
            errs.append("%s: non-https source %s" % (fid, u))
    # 誤帰属ステータスなら代替引用が必須
    if f.get("quote_source_status") == "誤帰属" and not f.get("quote_alt"):
        errs.append("%s: 誤帰属 but no quote_alt" % fid)
    # 文字混入チェック
    for k, v in f.items():
        txt = " ".join(v) if isinstance(v, list) else str(v)
        weird = sorted({c for c in txt if not script_ok(c)})
        if weird:
            errs.append("%s.%s: foreign script chars %s" % (fid, k, weird))
    # 全角スペース・二重スペースの混入
    for k in ("struggle", "bio_summary", "achievement", "quote", "quote_background"):
        if "  " in str(f.get(k, "")):
            errs.append("%s.%s: double space" % (fid, k))

print("=== SCHEMA CHECK: %d entries ===" % len(FIGURES))
if errs:
    print("ERRORS (%d):" % len(errs))
    for e in errs:
        print("  -", e)
else:
    print("OK — no errors")

print("\nfame_tier   :", dict(Counter(f["fame_tier"] for f in FIGURES)))
print("quote_status:", dict(Counter(f["quote_source_status"] for f in FIGURES)))
print("worry_tags  :", dict(Counter(t for f in FIGURES for t in f["worry_tags"])))
print("field       :", dict(Counter(f["field"].split("／")[0] for f in FIGURES)))
