# -*- coding: utf-8 -*-
# chatgpt_research.py (hardened JSON-first version)
# - Responses APIのJSONを直接パース（テキスト経由を最小化）
# - 空dictは不正扱い→原文から再パース
# - キー正規化（core_message / executive_summary / related_books / practical_actions）
# - 実ノート用に文字列整形（related_booksは行→テキスト、actionsは3件→" / "）
# - 最終直前にJSONっぽい文字列なら再パース→抽出の保険

import os, re, json, datetime, time, random, unicodedata
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv
from openai import OpenAI

# === Paths / Client ===========================================================
# === Paths / Client ===========================================================
# プロジェクトルート（srcの親ディレクトリ）
PROJECT_DIR = Path(__file__).resolve().parent.parent
if os.getenv("GITHUB_ACTIONS"):
    VAULT_ROOT = Path(PROJECT_DIR).resolve()
    INBOX_DIR = VAULT_ROOT / "100_Inbox"
else:
    VAULT_ROOT = Path(os.getenv("VAULT_ROOT", "/Users/seihoushouba/Documents/Oshomadesse-pc")).resolve()
    INBOX_DIR = Path(os.getenv("INBOX_DIR", str(VAULT_ROOT / "100_Inbox"))).resolve()

DATA_DIR    = PROJECT_DIR / "data"
for d in (DATA_DIR, INBOX_DIR): d.mkdir(parents=True, exist_ok=True)

load_dotenv(os.path.join(PROJECT_DIR, ".env"))
client = None

def _get_client():
    global client
    if client is None:
        client = OpenAI()
    return client

# --- モデル/料金設定 ---
PRO_MODEL = os.getenv("GPT5_MODEL", "gpt-5")
MAX_OUT   = int(os.getenv("GPT5_MAX_OUTPUT_TOKENS", os.getenv("GEMINI_PRO_MAX_TOKENS", "8192")))
PRO_CFG   = {"max_output_tokens": max(MAX_OUT, 256)}

# 料金
GPT5_PRICE_INPUT_PER_MTOK        = float(os.getenv("GPT5_PRICE_INPUT_PER_MTOK", "1.25"))
GPT5_PRICE_CACHED_INPUT_PER_MTOK = float(os.getenv("GPT5_PRICE_CACHED_INPUT_PER_MTOK", "0.125"))
GPT5_PRICE_OUTPUT_PER_MTOK       = float(os.getenv("GPT5_PRICE_OUTPUT_PER_MTOK", "10.0"))

# === Utils ===================================================================
def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

def _strip_code_fences(text: str) -> str:
    if not isinstance(text, str): return ""
    return re.sub(r"```.*?```", "", text, flags=re.S)

def _soft_json_fix(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = re.sub(r",\s*([\]\}])", r"\1", s)
    return s

def _norm_key(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[0-9_]+", "", s)
    s = re.sub(r"[ -/:-@\[-`{-~]", "", s)
    return s

def _dig(d: Dict[str, Any], keys: List[str]) -> Any:
    if not isinstance(d, dict): return None
    targets = [_norm_key(k) for k in keys]
    for k, v in d.items():
        nk = _norm_key(k)
        for t in targets:
            if t and t in nk:
                return v
        if isinstance(v, dict):
            r = _dig(v, keys)
            if r is not None: return r
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    r = _dig(it, keys)
                    if r is not None: return r
    return None

def _as_text(x) -> str:
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, (list, tuple)):
        buf=[]
        for v in x:
            s=_as_text(v)
            if s: buf.append(s)
        return " / ".join(buf)
    if isinstance(x, dict):
        for k in ("text","value","content","概要","要約","summary","message"):
            v = x.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        try:    return json.dumps(x, ensure_ascii=False)
        except: return str(x)
    return "" if x is None else str(x).strip()

def _usage_from_chat(resp) -> Dict[str,int]:
    try:
        u=getattr(resp,"usage",None)
        if not u: return {}
        def _g(k):
            return getattr(u,k,None) if hasattr(u,k) else (u.get(k) if isinstance(u,dict) else None)
        inp  = _g("input_tokens") or _g("prompt_tokens") or 0
        out  = _g("output_tokens") or _g("completion_tokens") or 0
        cinp = _g("cached_input_tokens") or 0
        tot  = _g("total_tokens") or (int(inp or 0)+int(out or 0))
        return {
            "input_tokens": int(inp or 0),
            "output_tokens": int(out or 0),
            "cached_input_tokens": int(cinp or 0),
            "total_tokens": int(tot or 0)
        }
    except Exception:
        return {}

def _cost_from_usage(usage: Dict[str,int]) -> float:
    inp  = int(usage.get("input_tokens",0) or 0)
    out  = int(usage.get("output_tokens",0) or 0)
    cinp = int(usage.get("cached_input_tokens",0) or 0)
    bill_in = max(inp - cinp, 0)
    return ((bill_in*GPT5_PRICE_INPUT_PER_MTOK) + (cinp*GPT5_PRICE_CACHED_INPUT_PER_MTOK) + (out*GPT5_PRICE_OUTPUT_PER_MTOK)) / 1_000_000.0

# === JSON取り出し（Responses直取りを最優先） =====================================
def _json_from_responses(resp) -> Optional[dict]:
    """
    Responses APIの戻りからJSONオブジェクトを直接取得。
    - output_text がJSON文字列のことが多い → まずこれを試す
    - それ以外は output / message / content を走査し、最初に解釈できるJSONを返す
    """
    # 1) 公式ショートカット
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        s = t.strip()
        try:
            data = json.loads(s)
            if isinstance(data, dict) and data: return data
            if isinstance(data, list) and data and isinstance(data[0], dict): return data[0]
        except Exception:
            pass

    # 2) 任意走査（最初に取れるJSON文字列をパース）
    def _walk(o, hits: List[str]):
        if o is None: return
        if isinstance(o, str):
            s = o.strip()
            if s.startswith("{") or s.startswith("["): hits.append(s)
            return
        if isinstance(o, dict):
            # textフィールド優先で拾う
            v = o.get("text")
            if isinstance(v, str) and (v.strip().startswith("{") or v.strip().startswith("[")):
                hits.append(v.strip())
            for vv in o.values():
                _walk(vv, hits)
            return
        if isinstance(o, (list, tuple, set)):
            for it in o:
                _walk(it, hits)
            return
        # pydantic系
        for name in ("text", "output_text", "content", "message", "value"):
            if hasattr(o, name):
                _walk(getattr(o, name), hits)

    candidates: List[str] = []
    for attr in ("output", "message", "content"):
        if hasattr(resp, attr):
            _walk(getattr(resp, attr), candidates)

    for s in candidates:
        try:
            data = json.loads(_soft_json_fix(_strip_code_fences(s)))
            if isinstance(data, dict) and data: return data
            if isinstance(data, list) and data and isinstance(data[0], dict): return data[0]
        except Exception:
            continue
    return None

# --- テキストからJSON（最終保険） ------------------------------------------------
def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    if not text: return None
    # フェンス除去してそのまま
    s = _soft_json_fix(_strip_code_fences(text))
    # 先頭末尾がJSONっぽい場合
    if (s.strip().startswith("{") and s.strip().endswith("}")) or (s.strip().startswith("[") and s.strip().endswith("]")):
        try:
            data=json.loads(s)
            if isinstance(data, dict): return data
            if isinstance(data, list) and data and isinstance(data[0], dict): return data[0]
        except Exception:
            pass
    # 最後の手段：貪欲一致
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", s)
    if m:
        try:
            data = json.loads(_soft_json_fix(m.group(1)))
            if isinstance(data, dict): return data
            if isinstance(data, list) and data and isinstance(data[0], dict): return data[0]
        except Exception:
            return None
    return None

# --- 本文ブロック抽出（フォールバック） ------------------------------------------
def _grab_block(label_patterns: List[str], text: str) -> str:
    head = r"(?:\d+[\.\)]\s*)?"
    labels = "|".join([re.escape(lp) for lp in label_patterns])
    pat = rf"(?ms)^\s*{head}(?:{labels})(?:（.*?）)?\s*[:：]?\s*\n?(?P<body>.+?)(?=^\s*{head}(核心的メッセージ|核心メッセージ|エグゼクティブ・サマリー|エグゼクティブサマリー|Executive Summary|Core Message|関連書籍|Related Books)\b|\Z)"
    m = re.search(pat, text or "")
    return re.sub(r"^[\-\*\•・]\s*", "", m.group("body"), flags=re.M).strip() if m else ""

def _extract_sections_from_text(text: str) -> Tuple[str, str, str]:
    t = _strip_code_fences((text or "").replace("\r\n","\n"))
    core = _grab_block(["核心的メッセージ","核心メッセージ","Core Message"], t)
    execs = _grab_block(["エグゼクティブ・サマリー","エグゼクティブサマリー","Executive Summary","要約","概要","まとめ"], t)
    related_block = _grab_block(["関連書籍","Related Books","参考文献","関連文献"], t)
    related_lines = [re.sub(r"^[\-\*\•・]\s*", "", l).strip() for l in related_block.split("\n") if l.strip()]
    related = " / ".join(related_lines) if related_lines else related_block.strip()
    return core.strip(), execs.strip(), related.strip()

# --- 今日できるアクション抽出 -----------------------------------------------------
def _split_candidate_lines(text: str) -> List[str]:
    if not isinstance(text, str) or not text.strip(): return []
    t = text.replace("\r\n","\n")
    lines = re.split(r"\n+", t)
    out=[]
    for ln in lines:
        ln = re.sub(r"^\s*[\-\*\•・\d\.\)\]]+\s*", "", ln).strip()
        if ln: out.append(ln)
    return out

def _is_today_scope(s: str) -> bool:
    s = s.strip()
    if not s: return False
    if any(b in s for b in ("来週","来月","来年","半年","四半期","年間","長期計画")): return False
    return len(s) <= 36

def _normalize_action(s: str) -> str:
    s = re.sub(r"[「」『』“”\"'\s]+$", "", s).strip()
    s = re.sub(r"^[「」『』“”\"'\s]+", "", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s.rstrip("。.")

def _actions_from_parsed(parsed: Dict[str, Any], raw_text: str) -> List[str]:
    keys_priority = [
        "今日できるアクション","今日できる行動","今日行えるアクション",
        "todayactions","today_action","immediateactions",
        "実践","アクション","具体行動","actions","recommendations"
    ]
    bucket = _dig(parsed, keys_priority)
    items: List[str] = []
    if isinstance(bucket, list):
        for it in bucket:
            if isinstance(it, str) and it.strip(): items.append(it.strip())
            elif isinstance(it, dict):
                cand = it.get("action") or it.get("アクション") or it.get("行動") or it.get("todo") or it.get("内容")
                if isinstance(cand, str) and cand.strip(): items.append(cand.strip())
    elif isinstance(bucket, dict):
        for k in ("action","アクション","行動","todo","内容","1","2","3"):
            v=bucket.get(k)
            if isinstance(v, str) and v.strip(): items.append(v.strip())
            elif isinstance(v, list):
                for s in v:
                    if isinstance(s, str) and s.strip(): items.append(s.strip())
    elif isinstance(bucket, str):
        items += _split_candidate_lines(bucket)

    if not items and raw_text:
        raw_block = _grab_block(
            ["今日できるアクション","今日行えるアクション","実践への示唆","実践","アクション"],
            raw_text
        )
        if raw_block: items += _split_candidate_lines(raw_block)

    out=[]
    for a in items:
        a = _normalize_action(a)
        if a and _is_today_scope(a) and a not in out:
            out.append(a)
        if len(out) >= 3: break
    return out

# === Responses API helpers =====================================================
def _responses_create_safe(**kwargs):
    try:
        return _get_client().responses.create(**kwargs)
    except TypeError as e:
        msg = str(e)
        if "response_format" in msg:
            kwargs.pop("response_format", None)
            return _get_client().responses.create(**kwargs)
        if "max_output_tokens" in msg:
            kwargs.pop("max_output_tokens", None)
            return _get_client().responses.create(**kwargs)
        raise

def _should_use_responses(model: str) -> bool:
    flag = (os.getenv("OPENAI_USE_RESPONSES","1").strip().lower() in ("1","true"))
    return flag or (str(model).lower().startswith("gpt-5"))

# === Connector =================================================================
class GeminiConnector:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.model = PRO_MODEL

    def deep_research_prompt(self, title: str, author: str) -> str:
        return f"""\
あなたは熟練した書籍アナリストです。以下の書籍について、指定された項目に従って詳細な調査レポートを日本語で作成してください。

書籍名: {title}
著者名: {author}

出力は有効なJSONオブジェクト1つのみ。説明文やマークダウンは禁止です。

キーは下記8つに限定してください（順不同可）:
1) 核心的メッセージ
2) エグゼクティブ・サマリー（「要約=問い×答え×根拠（Why＝なぜそうなのか？&How=そのためには？）」の形式で、そこさえ見れば本を読まずとも理解できるようにまとめる）
3) 主要概念の説明（各概念を1〜2文で定義。可能なら一言要約も）
4) 概念間の関係性や因果関係（箇条書きや簡易図式テキストで可）
5) 構造と論理展開（章構成の要点や議論の流れを説明）
6) 重要な引用（原文/要旨＋なぜ重要か1文で）
7) 今日できるアクション（読後すぐに15〜30分で実行できるもの）
8) 関連書籍（各要素は {{ "書名": "...", "著者": "...", "関連性": "なぜ関連するか" }} の配列）

重要: 「今日できるアクション」は“本を読んで今日行えるアクション”の提示に限定してください。
- 日本語、動詞で始める命令形/箇条書きスタイル
- 1件あたり30文字以内、所要15〜30分を想定
- ちょうど3件の配列（例: ["○○を5分間実践","□□を1ページ読む","△△を設定する"]）
"""

    def _chat_once(self, prompt: str):
        if _should_use_responses(self.model):
            r = _responses_create_safe(
                model=self.model,
                input=[
                    {"role":"system","content":"出力は有効なJSONのみ。余計な文字や説明は禁止。必ず単一のJSONオブジェクト。"},
                    {"role":"user","content":prompt}
                ],
                response_format={"type":"json_object"},
                max_output_tokens=PRO_CFG["max_output_tokens"]
            )
           # デバッグログ保存
            try:
                log_dir = os.path.join(PROJECT_DIR, "data", "modules", "chatgpt_research")
                os.makedirs(log_dir, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Extract content for openai_chat_dbg_{ts}.txt
                content_for_chat_dbg = getattr(r, "output_text", None)
                if not isinstance(content_for_chat_dbg, str):
                    content_for_chat_dbg = str(r) # Fallback if output_text is not a string
                
                with open(os.path.join(log_dir, f"openai_chat_dbg_{ts}.txt"), "w", encoding="utf-8") as f:
                    f.write(f"--- PROMPT ---\n{prompt}\n\n--- RESPONSE ---\n{content_for_chat_dbg}\n")
                    
                # Extract JSON for openai_responses_dbg_{ts}.json
                response_json_data = None
                try:
                    response_json_data = r.model_dump_json() if hasattr(r, "model_dump_json") else str(r)
                    # If it's a string, try to parse it to ensure it's valid JSON for dumping
                    if isinstance(response_json_data, str):
                        response_json_data = json.loads(response_json_data)
                except Exception:
                    response_json_data = str(r) # Fallback to string if not JSON serializable
                
                with open(os.path.join(log_dir, f"openai_responses_dbg_{ts}.json"), "w", encoding="utf-8") as f:
                    if isinstance(response_json_data, dict) or isinstance(response_json_data, list):
                        json.dump(response_json_data, f, ensure_ascii=False, indent=2)
                    else:
                        f.write(str(response_json_data)) # Write as string if not dict/list
                    
            except Exception as e:
                print(f"Debug log save failed: {e}")
            # JSON直取りを最優先
            parsed = _json_from_responses(r)
            raw_text = getattr(r, "output_text", None)
            raw_text = raw_text if isinstance(raw_text, str) else ""
            return r, parsed, raw_text

        # Fallback: Chat Completions
        r = _get_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role":"system","content":"出力は有効なJSONのみ。余計な文字や説明は禁止。必ず単一のJSONオブジェクト。"},
                {"role":"user","content":prompt}
            ],
            max_completion_tokens=PRO_CFG["max_output_tokens"]
        )
        msg = r.choices[0].message if (r and getattr(r,"choices",None)) else None
        t = ""
        if msg is not None:
            c = getattr(msg, "content", None)
            if isinstance(c, str) and c.strip():
                t = c.strip()
            elif isinstance(c, list):
                parts = []
                for part in c:
                    txt = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                    if isinstance(txt, str) and txt.strip(): parts.append(txt.strip())
                if parts: t = "\n".join(parts).strip()
            else:
                ref = getattr(msg, "refusal", None)
                if isinstance(ref, str) and ref.strip(): t = ref.strip()
        parsed = extract_json_from_text(t)
        return r, parsed, t or ""

    def get_deep_research_json(self, title: str, author: str, category: Optional[str] = None) -> Dict[str, Any]:
        _ensure_dirs()
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        prompt = self.deep_research_prompt(title, author)

        resp=None; parsed=None; raw_text=""; usage={}
        last_err=None
        # 3回試行（モデル側断続的失敗に備える）
        for i in range(1,4):
            try:
                if self.verbose: print(f"{self.model} chat attempt {i}/3")
                r, p, t = self._chat_once(prompt)
                resp, parsed, raw_text = r, (p or {}), (t or "")
                usage = _usage_from_chat(r)
                if isinstance(parsed, dict) and parsed:  # 空dictは不正
                    break
            except Exception as e:
                last_err = e
                time.sleep(min(1*(2**(i-1)), 8) + random.random()*0.2)

        # まだ空なら raw_text から最終再パース
        if not (isinstance(parsed, dict) and parsed):
            parsed = extract_json_from_text(raw_text) or {}

        # デバッグ保存
        # data/modules/chatgpt_research/ には保存済みなので、data/直下への重複保存は削除
        # dbg = DATA_DIR / f"openai_chat_dbg_{ts}.txt" ... (removed)

        if not (isinstance(parsed, dict) and parsed) and not raw_text:
            raise RuntimeError("no text from OpenAI (check model/endpoint/API key)")

        # --- 正規化（キーゆれ→正規キー） ----------------------------------------
        def first_nonempty(*vals) -> str:
            for v in vals:
                s = _as_text(v)
                if s: return s
            return ""

        core_p    = _dig(parsed, ["核心的メッセージ","核心メッセージ","coremessage","core_message"])
        execs_p   = _dig(parsed, ["エグゼクティブサマリー","エグゼクティブ・サマリー","executivesummary","executive_summary","execsummary"])
        related_p = _dig(parsed, ["関連書籍","relatedbooks","related_books","参考文献","関連文献"])

        core_t, execs_t, related_t = _extract_sections_from_text(raw_text)
        actions_list = _actions_from_parsed(parsed, _strip_code_fences(raw_text))
        practical_actions = " / ".join(actions_list) if actions_list else ""

        core_message       = first_nonempty(core_p,  core_t)   or (_strip_code_fences(raw_text)[:350].strip() if raw_text else "")
        executive_summary  = first_nonempty(execs_p, execs_t)  or (_strip_code_fences(raw_text)[:600].strip() if raw_text else "")
        # relatedは配列/辞書も来うる → 表示用文字列に整形
        if isinstance(related_p, list):
            buf=[]
            for it in related_p:
                if isinstance(it, str) and it.strip():
                    buf.append(it.strip())
                elif isinstance(it, dict):
                    t = it.get("書名") or it.get("title") or it.get("name") or ""
                    a = it.get("著者") or it.get("author") or it.get("authors") or ""
                    r = it.get("関連性") or it.get("reason") or it.get("説明") or ""
                    t = str(t).strip(); a = str(a).strip(); r = str(r).strip()
                    base = f"{t}（{a}）" if (t and a) else (t or a)
                    s = f"{base}: {r}" if r and base else (base or r)
                    if s: buf.append(s)
                else:
                    s = _as_text(it)
                    if s: buf.append(s)
            related_books = " / ".join(buf) if buf else related_t
        else:
            related_books = first_nonempty(related_p, related_t)

        # --- JSONっぽい文字列が残っていたら、ここで再抽出して上書き（最終保険） ----
        def _maybe_json_fix(s: str, keys: List[str], fallback: str) -> str:
            if not isinstance(s, str): return fallback
            ss = s.strip()
            if ss.startswith("{") or ss.startswith("["):
                try:
                    j = json.loads(_soft_json_fix(_strip_code_fences(ss)))
                    v = _dig(j, keys)
                    return _as_text(v) or fallback
                except Exception:
                    return fallback
            return s

        core_message      = _maybe_json_fix(core_message, ["核心的メッセージ","核心メッセージ","core_message","coremessage"], core_message)
        executive_summary = _maybe_json_fix(executive_summary, ["エグゼクティブ・サマリー","エグゼクティブサマリー","executive_summary","execsummary","executivesummary"], executive_summary)
        related_books     = _maybe_json_fix(related_books, ["関連書籍","related_books","relatedbooks","参考文献","関連文献"], related_books)

        # --- Researchノート保存＆URL（Vault相対） --------------------------------
        research_url=""
        try:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            note_path = INBOX_DIR / f"Research-{date_str}.md"
            md=["---","tags: [research, books]","---","```", (raw_text or json.dumps(parsed, ensure_ascii=False)), "```"]
            note_path.write_text("\n".join(md), encoding="utf-8")
            research_url = str(note_path.resolve().relative_to(VAULT_ROOT)).replace("\\","/")
            if self.verbose: print("saved note:", research_url)
        except Exception:
            pass

        start_credit = os.getenv("CHATGPT_START_CREDIT") or os.getenv("chatgpt_start_credit") or "0"
        try: start_credit = float(start_credit)
        except Exception: start_credit = 0.0

        cost_usd = _cost_from_usage(usage)
        credit_left = float(start_credit) - float(cost_usd)

        result = {
            "title": (title or "").strip(),
            "author": (author or "").strip(),
            "category": (category or "").strip(),
            "research_url": research_url,
            "core_message": core_message,
            "executive_summary": executive_summary,
            "related_books": related_books,
            "practical_actions": practical_actions,
            "raw": str(raw_text or json.dumps(parsed, ensure_ascii=False)),
            "parsed": parsed if isinstance(parsed, dict) else {},
            "usage": usage,
            "chatgpt_usaget": int(usage.get("total_tokens", (usage.get("prompt_tokens",0) or 0)+(usage.get("completion_tokens",0) or 0))),
            "chatgpt_credit": credit_left,
            "chatgpt_credit_str": f"${credit_left:.2f}",
            "model": self.model
        }

        try:
            print("=== GPT Deep Research result ===")
            for k in ("title","author","category","research_url"):
                print(k+":", result[k] or "(empty)")
            print("chatgpt_usaget:", result["chatgpt_usaget"])
            print("chatgpt_credit:", f"{result['chatgpt_credit']:.6f}")
        except Exception:
            pass
        return result

# 互換のため公開
extract_json_from_text_public = extract_json_from_text
_extract_sections_from_text_public = _extract_sections_from_text
ChatGPTConnector = GeminiConnector
__all__ = ["GeminiConnector","ChatGPTConnector","extract_json_from_text_public","_extract_sections_from_text_public"]
