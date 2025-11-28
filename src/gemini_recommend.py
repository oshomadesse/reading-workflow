# -*- coding: utf-8 -*-
"""
gemini_recommend.py
安全なタイトル正規化と推薦取得ロジック（Gemini Flash を用いる想定）
（フォールバックの固定テストデータは削除済み：genai未設定時は空リストを返します）
"""

import os
import json
import re
import unicodedata
import shutil
import difflib
from typing import List, Dict, Optional
from pathlib import Path

from dotenv import load_dotenv

try:
    import google.generativeai as genai
except Exception:
    genai = None

# プロジェクトルート（srcの親ディレクトリ）
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
ENV_PATH = PROJECT_DIR / ".env" # Updated to use Path object
if ENV_PATH.exists(): # Updated to use Path object's exists()
    load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and genai is not None:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        pass

FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
FLASH_TEMPERATURE = float(os.getenv("GEMINI_FLASH_TEMPERATURE", "0.35"))
FLASH_MAX_OUTPUT = int(os.getenv("GEMINI_PRO_MAX_TOKENS", "8192"))

SAFETY_ALLOW_ALL = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUAL", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS", "threshold": "BLOCK_NONE"},
]

VERSION_WORDS = r"(?:新版|新装版|改訂版|増補|増補改訂|合本|完全版|決定版|新訳|普及版|第\s*\d+\s*版)"

ALLOWED_CATS = [
    "ビジネス", "自己啓発", "ライフスタイル", "心理学", "歴史", "健康・医療",
    "教育", "科学", "哲学", "社会", "経済", "技術", "芸術", "宗教",
    "政治", "旅行", "料理", "子育て", "エッセイ", "生物", "物理", "数学"
]

# NOTE: 運用上の制約で現在は下記4カテゴリのみを推薦対象にする。
# ALLOWED_CATS は将来の復帰用に全件を保持しつつ、ACTIVE_CATS だけ実装で使用する。
ACTIVE_CATS = ["ビジネス", "自己啓発", "ライフスタイル", "心理学"]

KEYWORDS = [
    ("ビジネス", ["経営", "起業", "マネジメント", "戦略", "マーケティング", "営業", "仕事", "交渉"]),
    ("自己啓発", ["習慣", "目標", "成功", "生き方", "マインド", "やればできる", "自己", "行動力", "レジリエンス", "ウェルビーイング", "7つの習慣"]),
    ("ライフスタイル", ["暮らし", "ミニマル", "生活", "片付け", "旅", "食", "時間術"]),
    ("心理学", ["心理", "認知", "行動経済", "不合理", "影響力", "説得", "メンタル", "mindset", "ドゥエック", "チャルディーニ"]),
    ("歴史", ["歴史", "戦争", "文明", "帝国", "昭和", "中世", "近代"]),
    ("健康・医療", ["健康", "医療", "寿命", "睡眠", "運動", "食事"]),
    ("教育", ["勉強", "学習", "教育", "教師", "学び"]),
    ("科学", ["科学", "物理", "生物", "宇宙", "ai", "データ", "統計", "数学"]),
    ("哲学", ["哲学", "倫理", "ニーチェ", "ソクラテス", "カント"]),
    ("社会", ["社会", "文化", "ジェンダー", "差別", "格差"]),
    ("経済", ["経済", "金融", "株", "投資"]),
    ("技術", ["テクノロジー", "it", "プログラミング", "エンジニア"]),
    ("芸術", ["アート", "音楽", "デザイン", "建築"]),
    ("宗教", ["宗教", "仏教", "キリスト", "信仰"]),
    ("政治", ["政治", "選挙", "政策"]),
    ("旅行", ["旅行", "観光"]),
    ("料理", ["料理", "レシピ"]),
    ("子育て", ["育児", "子育て"]),
    ("エッセイ", ["エッセイ", "随筆", "コラム"]),
    ("生物", ["生物", "動物", "進化"]),
    ("物理", ["量子", "相対性理論", "物理"]),
    ("数学", ["数学", "代数", "解析"]),
]

ACTIVE_KEYWORDS = [kv for kv in KEYWORDS if kv[0] in ACTIVE_CATS]


def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", str(title)).lower().strip()
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"（.*?）", "", t)
    t = re.sub(r"\[.*?\]", "", t)
    t = re.sub(r"【.*?】", "", t)
    t = re.split(r"[:：]", t)[0]
    t = re.sub(VERSION_WORDS, "", t)
    t = re.sub(r"[^0-9a-zぁ-んァ-ン一-龥]", "", t)
    return t

def _char_class_counts(s: str):
    s2 = unicodedata.normalize("NFKC", str(s or ""))
    cjk = roman = total = 0
    for ch in s2:
        if ch.isspace():
            continue
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF:
            cjk += 1
        elif ('A' <= ch <= 'Z') or ('a' <= ch <= 'z'):
            roman += 1
        # 数字・記号はスコアから除外
        if ch.isalpha() or (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF):
            total += 1
    return cjk, roman, total

def is_japanese_like(s: str) -> bool:
    """日本語（CJK/かな/カナ）成分が十分に含まれるかを確認。
    - CJK系が1文字以上、かつ CJK比率>=0.30 or ローマ字比率<=0.50
    - 直感的な判定で英語タイトル/著者の混入を防ぐ
    """
    cjk, roman, total = _char_class_counts(s)
    if total <= 0:
        return False
    cjk_ratio = cjk / total if total else 0.0
    roman_ratio = roman / total if total else 0.0
    return (cjk >= 1) and (cjk_ratio >= 0.30 or roman_ratio <= 0.50)


def similar_or_contains(a: str, b: str, ratio_threshold: float = 0.82) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if short and short in long:
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= ratio_threshold


def is_banned_title(title: str, ban_titles: List[str], collected: List[Dict], threshold: float = 0.70) -> Optional[str]:
    nt = normalize_title(title)
    for b in (ban_titles + [y.get("title", "") for y in collected]):
        if not b:
            continue
        bn = normalize_title(b)
        if not bn:
            continue
        if bn in nt or nt in bn:
            return b
        try:
            if difflib.SequenceMatcher(None, bn, nt).ratio() >= threshold:
                return b
        except Exception:
            continue
    return None


def normalize_category(cat: str, title: str, reason: str) -> str:
    s = (cat or "").strip()
    pool = ACTIVE_CATS or ALLOWED_CATS
    keyword_pool = ACTIVE_KEYWORDS or KEYWORDS
    for c in pool:
        if c in s:
            return c
    text = " ".join([title or "", reason or "", s]).lower()
    for c, kws in keyword_pool:
        if any(k.lower() in text for k in kws):
            return c
    return pool[0] if pool else "その他"


class GeminiConnector:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        if genai is not None:
            try:
                self.fast = genai.GenerativeModel(
                    FLASH_MODEL,
                    generation_config={
                        "temperature": FLASH_TEMPERATURE,
                        "max_output_tokens": FLASH_MAX_OUTPUT,
                        "response_mime_type": "application/json",
                    },
                    safety_settings=SAFETY_ALLOW_ALL,
                )
            except Exception:
                self.fast = None
        else:
            self.fast = None

    def book_selection_prompt(self, excluded_books: List[str]) -> str:
        excluded_sample = excluded_books or []
        excluded_list = "\n".join(f"- {x}" for x in excluded_sample)
        category_list = ACTIVE_CATS or ALLOWED_CATS
        return (
            # 目的
            "今日読むべき本を5冊推薦してください。除外リストに含まれる書籍やその類似は選ばないでください。"
            + ("\n除外リスト:\n" + excluded_list + "\n" if excluded_list else "")
            # カテゴリ要件
            + " 以下のカテゴリの中から、その本に最も当てはまるものを必ず1つだけ選んでください: "
            + ",".join(category_list)
            + ". "
            + "categoryに「小説」という単語が含まれる場合はその本を推薦対象から除外してください。"
            # 日本語固定（邦題・著者名）
            + "\n重要: titleとauthorは必ず日本語で記載してください（邦題・日本語著者表記）。英語・ローマ字・原題は書かないでください。"
            + " 邦題が国内で未流通・不明な場合はその候補を推薦しないでください。直訳や推測の邦題を作らないこと。"
            + " 著者表記は日本語で一般的な表記（カタカナ等）に統一してください。"
            # 信頼性の担保（根拠の要請）
            + " reasonには、その邦題や著者表記の根拠（国内出版社名やISBN、国内流通名の言及など）を簡潔に含めてください（URLは不要）。"
            # 出力形式
            + " 出力はJSON配列で、各要素に title, author, category, reason の4項目のみを含めてください。"
        )

    def _call_flash_json(self, prompt):
        if self.verbose:
            try:
                preview = (prompt or "")[:300]
            except Exception:
                preview = "(preview error)"
            print("DEBUG: _call_flash_json called. prompt preview:", preview)
        try:
            if getattr(self, "fast", None) is None:
                if self.verbose:
                    print("WARNING: genai not configured - returning empty list (no fallback).")
                return []
            resp = self.fast.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": FLASH_TEMPERATURE,
                    "max_output_tokens": FLASH_MAX_OUTPUT,
                },
            )
            text = None
            if getattr(resp, "candidates", None):
                cand = resp.candidates[0]
                if getattr(cand, "content", None) and getattr(cand.content, "parts", None):
                    for part in cand.content.parts:
                        if getattr(part, "text", None):
                            text = part.text.strip()
                            if text:
                                break
            if self.verbose:
                print("\n===== Gemini raw output (expected JSON) =====")
                print(text if text else "(empty)")
                print("============================================\n")
            try:
                data = json.loads(text) if text else []
            except Exception:
                data = []
            if self.verbose:
                print("DEBUG: parsed candidates count =", len(data) if isinstance(data, list) else 0)
            return data if isinstance(data, list) else []
        except Exception as e:
            if self.verbose:
                print("ERROR in _call_flash_json:", e)
            return []

    def get_book_recommendations(self, excluded_books: List[str]) -> List[Dict]:
        target = 5
        collected: List[Dict] = []
        ban_titles: List[str] = list(excluded_books or [])
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts and len(collected) < target:
            attempts += 1
            prompt = self.book_selection_prompt(ban_titles + [c.get("title", "") for c in collected])
            batch = self._call_flash_json(prompt) if hasattr(self, "_call_flash_json") else []

            for x in batch:
                if not isinstance(x, dict):
                    continue
                t = (x.get("title") or "").strip()
                a = (x.get("author") or "").strip()
                c = (x.get("category") or "").strip()
                r = (x.get("reason") or "").strip()
                if not t:
                    continue

                # 日本語固定の安全柵: 英語/ローマ字っぽい候補は弾く（再試行で置き換え狙い）
                if not is_japanese_like(t) or (a and not is_japanese_like(a)):
                    if self.verbose:
                        print("WARN: non-Japanese title/author filtered:", t, f"author={a}")
                    # 同一候補の再出力を避けるため ban に追加
                    try:
                        if t not in ban_titles:
                            ban_titles.append(t)
                    except Exception:
                        pass
                    continue

                orig_tokens = [tt.strip().lower() for tt in re.split(r'[,\|/、・;]+', (c or "")) if tt.strip()]
                if any(tok in ["小説", "文学", "novel", "fiction", "ライトノベル", "児童文学", "短編", "青春"] for tok in orig_tokens):
                    if self.verbose:
                        print("WARN: excluded by genre:", t, "(", c, ")")
                    continue

                matched_ban = None
                try:
                    matched_ban = is_banned_title(t, ban_titles, collected)
                except Exception:
                    matched_ban = None

                if matched_ban:
                    if self.verbose:
                        print("WARN: excluded duplicate/near-duplicate title:", t, "(matched", matched_ban, ")")
                    continue

                if not matched_ban and any(similar_or_contains(t, b) for b in ban_titles + [y.get("title", "") for y in collected]):
                    if self.verbose:
                        print("WARN: excluded similar title:", t)
                    continue

                norm_cat = normalize_category(c, t, r)
                collected.append({"title": t, "author": a, "category": norm_cat, "reason": r})
                ban_titles.append(t)
                if len(collected) >= target:
                    break

        if self.verbose:
            print(f"INFO: Gemini recommendations completed (after exclusions): {len(collected)} items")
        return collected
