# -*- coding: utf-8 -*-
import os, json, requests
from dotenv import load_dotenv
from pathlib import Path

# プロジェクトルート（srcの親ディレクトリ）
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"

# Prefer menu-workflow/.env (directory of key files) over root .env
# If menu-workflow is not found (e.g. in CI or new location), this will just fail gracefully in _read_env_file_value
MW_ENV_DIR = os.path.join(PROJECT_DIR, "menu-workflow", ".env")

def _read_env_file_value(name: str) -> str | None:
    try:
        path = os.path.join(MW_ENV_DIR, name)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            v = f.read().strip()
        # Defensive cleanup for accidental "14:KEY=value" or "KEY=value" forms
        if ":" in v:
            left, right = v.split(":", 1)
            if left.isdigit():
                v = right
        if "=" in v:
            k, vv = v.split("=", 1)
            if k.strip() in {"LINE_ENABLED", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_TO"}:
                v = vv
        return v.strip()
    except Exception:
        return None

# 1) Force-load LINE_* from menu-workflow/.env (override any pre-set values)
for _k in ("LINE_ENABLED", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_TO"):
    _v = _read_env_file_value(_k)
    if _v:
        os.environ[_k] = _v

# 2) Then load root .env as fallback (do NOT override values set above)
load_dotenv(os.path.join(PROJECT_DIR, ".env"), override=False)

LINE_API_PUSH = "https://api.line.me/v2/bot/message/push"

def line_push_text(text: str, to: str|None=None) -> dict:
    if os.getenv("LINE_ENABLED","0") != "1":
        return {"ok": False, "reason": "disabled"}
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "reason": "no_token"}
    target = to or os.getenv("LINE_TO")
    if not target:
        return {"ok": False, "reason": "no_target"}

    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json; charset=UTF-8"}
    payload = {"to": target, "messages": [{"type": "text", "text": text[:5000]}]}
    try:
        r = requests.post(LINE_API_PUSH, headers=headers, data=json.dumps(payload), timeout=10)
        return {"ok": 200 <= r.status_code < 300, "status": r.status_code, "text": r.text}
    except Exception as e:
        return {"ok": False, "reason": f"exception:{e}"}

def line_push_flex(flex_obj: dict, alt_text: str = "Flex Message", to: str|None=None) -> dict:
    if os.getenv("LINE_ENABLED","0") != "1":
        return {"ok": False, "reason": "disabled"}
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        return {"ok": False, "reason": "no_token"}
    target = to or os.getenv("LINE_TO")
    if not target:
        return {"ok": False, "reason": "no_target"}

    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json; charset=UTF-8"}
    
    payload = {
        "to": target,
        "messages": [
            {
                "type": "flex",
                "altText": alt_text,
                "contents": flex_obj
            }
        ]
    }
    try:
        r = requests.post(LINE_API_PUSH, headers=headers, data=json.dumps(payload), timeout=10)
        return {"ok": 200 <= r.status_code < 300, "status": r.status_code, "text": r.text}
    except Exception as e:
        return {"ok": False, "reason": f"exception:{e}"}
