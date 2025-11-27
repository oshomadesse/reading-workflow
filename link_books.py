#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Books notes linker with partial title match and strict author match.

Behavior:
- Scan 100_Inbox/Books-*.md
- Extract Title (from '## 【 ... 】') and Author (from '- 著者:...')
- In '### 📚 関連書籍' section, for segments like 'Title（Author）: ...',
  if Author matches an existing note's author (normalized), and Title is a
  substring match (either direction) after normalization, link it as
  [[path|Title]] and add reciprocal link on the target note.

No logs written to disk; prints concise summary to stdout only.
"""

from __future__ import annotations
import re
import sys
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

import os

ROOT = Path(__file__).resolve().parent
if os.getenv("GITHUB_ACTIONS"):
    INBOX = ROOT / '100_Inbox'
else:
    # Try to find vault root from env or assume parent of parent if in a subfolder, 
    # but here we are likely in 11_Engineering/books-summary.
    # If we want to target the main vault inbox:
    VAULT_ROOT = Path(os.getenv("VAULT_ROOT", "/Users/seihoushouba/Documents/Oshomadesse-pc")).resolve()
    INBOX = Path(os.getenv("INBOX_DIR", str(VAULT_ROOT / "100_Inbox"))).resolve()

def nfkc(s: str) -> str:
    return unicodedata.normalize('NFKC', s)

PUNCT_RE = re.compile(r"[\s\-‐‑–—―〜~:：、。・,.;/\\()（）\[\]{}【】「」『』\"'!！?？·•°]+")

EDITION_RE = re.compile(r"(新版|改訂|増補|決定版|図解|完全版|要約|入門)$")

def norm_author(s: str) -> str:
    s = nfkc(s).lower()
    s = PUNCT_RE.sub("", s)
    return s

def strip_subtitle(title: str) -> str:
    t = nfkc(title)
    # cut at common subtitle separators
    for sep in [":", "：", "-", "ー", "—", "―", "–", "〜", "~"]:
        if sep in t:
            t = t.split(sep, 1)[0]
    # remove bracketed suffixes
    t = re.sub(r"[（(].*?[）)]$", "", t)
    # drop common edition postfixes
    t = EDITION_RE.sub("", t)
    return t.strip()

def norm_title(s: str) -> str:
    s = strip_subtitle(s)
    s = s.lower()
    s = PUNCT_RE.sub("", s)
    return s

TITLE_RE = re.compile(r"^##\s*【\s*.*?\s*(?P<title>.+?)\s*】\s*$")
AUTHOR_RE = re.compile(r"^\s*[-*]\s*[^\n]*?著者\s*[:：]\s*(?P<author>.+?)\s*$")

def parse_title(lines):
    for line in lines:
        m = TITLE_RE.match(line)
        if m:
            return m.group('title').strip()
    return None

def parse_author(lines):
    for line in lines:
        m = AUTHOR_RE.match(line)
        if m:
            return m.group('author').strip()
    return None

def find_related_section(lines):
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith('###') and '関連書籍' in line:
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start+1, len(lines)):
        if lines[j].strip().startswith('### '):
            end = j
            break
    return start, end

def ensure_related_section(lines):
    s, e = find_related_section(lines)
    if s is None:
        if lines and lines[-1] and not lines[-1].endswith('\n'):
            lines[-1] = lines[-1] + '\n'
        lines.extend(["\n", "### 📚 関連書籍\n"])  # header only
        s = len(lines) - 1
        e = len(lines)
    return s, e

def split_segments(bullet_line: str):
    s = bullet_line.strip()
    if s.startswith(('-', '*')):
        s = s[1:].strip()
    if not s:
        return []
    return re.split(r"\s*/\s*", s)

def join_segments(segments):
    return "- " + " / ".join(segments) + "\n"

def paren_span(seg: str):
    jp_o, jp_c = seg.rfind('（'), seg.rfind('）')
    en_o, en_c = seg.rfind('('), seg.rfind(')')
    if jp_o != -1 and jp_c != -1 and jp_o < jp_c:
        return jp_o, jp_c
    if en_o != -1 and en_c != -1 and en_o < en_c:
        return en_o, en_c
    return -1, -1

def parse_seg_title_author(seg: str):
    o, c = paren_span(seg)
    if o == -1:
        return None, None, None
    title = seg[:o].strip()
    author = seg[o+1:c].strip()
    tail = seg[c+1:]
    return title, author, tail

def already_linked(seg: str) -> bool:
    return '[["' in seg or '[[' in seg

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def title_match(a_norm: str, b_norm: str) -> bool:
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True
    # substring either way (handles short alias vs long official)
    if a_norm in b_norm or b_norm in a_norm:
        return True
    # fuzzy fallback
    return similar(a_norm, b_norm) >= 0.85

def author_match(a_norm: str, b_norm: str) -> bool:
    """Match authors robustly without overmatching common short names.
    Rules:
    - Exact normalized equality -> match
    - Else, substring allowed only if min(len(a_norm), len(b_norm)) >= 6
      and length ratio >= 0.8
    - Else, fuzzy ratio >= 0.93 and both lengths >= 6
    This treats variations like ジョン・マルケス vs ジョンマルケス as equal,
    while avoiding 'ジョン' alone matching everything.
    """
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True
    la, lb = len(a_norm), len(b_norm)
    lmin = min(la, lb)
    lmax = max(la, lb)
    ratio = lmin / lmax if lmax else 0.0
    if lmin >= 6 and ratio >= 0.8 and (a_norm in b_norm or b_norm in a_norm):
        return True
    if lmin >= 6 and similar(a_norm, b_norm) >= 0.93:
        return True
    return False

def load_notes():
    notes = []
    for p in sorted(INBOX.glob('Books-*.md')):
        text = p.read_text(encoding='utf-8')
        lines = text.splitlines(True)
        title = parse_title(lines)
        author = parse_author(lines)
        notes.append({
            'path': p,
            'rel': p.relative_to(ROOT),
            'rel_no_ext': str(p.relative_to(ROOT)).rsplit('.', 1)[0],
            'title': title,
            'author': author,
            'title_norm': norm_title(title) if title else None,
            'author_norm': norm_author(author) if author else None,
            'lines': lines,
        })
    return notes

def build_author_index(notes):
    # Keep for potential fast path, though currently we scan all for robustness
    idx = {}
    for n in notes:
        if not n['author_norm'] or not n['title_norm']:
            continue
        idx.setdefault(n['author_norm'], []).append(n)
    return idx

def clean_display_title(title: str) -> str:
    if not title:
        return title
    t = nfkc(title)
    t = t.lstrip('🧠 ').strip()
    return t

def link_all():
    notes = load_notes()
    author_idx = build_author_index(notes)
    rel_map = {str(n['rel']): n for n in notes}
    written = set()
    matched = 0
    for n in notes:
        lines = n['lines']
        s, e = find_related_section(lines)
        if s is None:
            continue
        i = s + 1
        while i < e:
            line = lines[i]
            if line.lstrip().startswith(('-', '*')):
                segs = split_segments(line)
                changed = False
                for si, seg in enumerate(segs):
                    if not seg.strip() or already_linked(seg):
                        continue
                    t, a, tail = parse_seg_title_author(seg)
                    if not t or not a:
                        continue
                    a_key = norm_author(a)
                    # robust author matching: scan all notes and test author_match
                    candidates = [cand for cand in notes if cand is not n and author_match(a_key, cand['author_norm'] or "")]
                    t_norm = norm_title(t)
                    best = None
                    best_score = 0.0
                    for cand in candidates:
                        if title_match(t_norm, cand['title_norm']):
                            # prefer closer title similarity
                            score = similar(t_norm, cand['title_norm'])
                            if score > best_score:
                                best = cand
                                best_score = score
                    if best is None:
                        continue
                    # Build linked segment
                    link = f"[[{best['rel_no_ext']}|{t}]]"
                    new_seg = f"{link}（{a}）{tail}"
                    segs[si] = new_seg
                    changed = True
                    matched += 1
                    # Reciprocal on target note
                    b = best
                    b_lines = b['lines']
                    bs, be = ensure_related_section(b_lines)
                    block = ''.join(b_lines[bs:be])
                    if f"[[{n['rel_no_ext']}|" not in block:
                        disp_title = clean_display_title(n['title'] or t)
                        disp_author = n['author'] or a
                        b_lines.insert(be, f"- [[{n['rel_no_ext']}|{disp_title}]]（{disp_author}）\n")
                        b['lines'] = b_lines
                        rel_map[str(b['rel'])] = b
                        written.add(str(b['rel']))
                if changed:
                    lines[i] = join_segments(segs)
                    n['lines'] = lines
                    written.add(str(n['rel']))
            i += 1
    # write back
    for rel in written:
        rel_map[rel]['path'].write_text(''.join(rel_map[rel]['lines']), encoding='utf-8')
    print(f"Linked segments: {matched}; files written: {len(written)}")

if __name__ == '__main__':
    link_all()
