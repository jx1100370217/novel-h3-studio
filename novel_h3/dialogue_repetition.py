"""Detect repeated spoken lines and duplicated exposition.

A take can pass ASR line-by-line and still repeat the previous shot's line. This
module checks the screenplay/shot plan *before* GPU time: near-identical lines
inside one scene, across adjacent scenes, or a long shared phrase that repeats
the same story information in different words.

It is deliberately conservative: short lines (under six characters) are not
compared, and similarity in the 0.55-0.72 band is a warning rather than a hard
failure. A repeated eight-character phrase is an issue because that is usually
the same exposition said twice, not a deliberate refrain.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

PUNCT_RE = re.compile(r"[\s，。！？；：、“”‘’（）()《》〈〉—…,.!?;:\-]")
LINE_RE = re.compile(r"^\s*([^：:\n]{1,16})[：:]\s*(.+?)\s*$")
NON_SPEAKER = {
    "insert", "cut", "shot", "visual", "montage", "transition", "sound", "note",
    "action", "close", "wide", "medium", "title", "card",
    "场景", "画面", "动作", "光", "声", "连续", "镜头", "转场", "插入",
    "特写", "中景", "全景", "近景", "远景", "构图", "调度", "字幕",
}


def normalize(text: str) -> str:
    return PUNCT_RE.sub("", str(text or ""))


def longest_common_substring(a: str, b: str) -> str:
    """Return the longest common contiguous substring (lines are short)."""
    if not a or not b:
        return ""
    previous = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i, ca in enumerate(a, 1):
        current = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                current[j] = previous[j - 1] + 1
                if current[j] > best_len:
                    best_len = current[j]
                    best_end = i
        previous = current
    return a[best_end - best_len:best_end]


def lines_from_sections(sections: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse ``speaker: line`` rows out of enhanced screenplay sections."""
    rows: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        sid = str(section.get("id") or f"section-{index + 1}")
        for raw in str(section.get("text") or "").splitlines():
            match = LINE_RE.match(raw)
            if not match:
                continue
            speaker, text = match.group(1).strip(), match.group(2).strip()
            if speaker.lower() in NON_SPEAKER or speaker in NON_SPEAKER:
                continue
            norm = normalize(text)
            if len(norm) < 6:
                continue
            rows.append({"section": sid, "section_index": index, "speaker": speaker,
                         "text": text, "norm": norm})
    return rows


def audit_lines(
    lines: Iterable[dict[str, Any]],
    *,
    section_window: int = 3,
    ratio_issue: float = 0.72,
    ratio_warning: float = 0.55,
    shared_issue: int = 8,
) -> dict[str, Any]:
    """Return repeated-line issues/warnings for dialogue rows.

    Each row needs ``section``/``section_index``, ``speaker``, ``text`` and
    optionally ``norm``. ``section_window`` limits comparisons to nearby
    scenes; a duplicate 20 scenes apart is a callback, not accidental
    exposition.
    """
    rows = list(lines)
    issues: list[str] = []
    warnings: list[str] = []
    pairs: list[dict[str, Any]] = []
    for i, first in enumerate(rows):
        a = first.get("norm") or normalize(first.get("text", ""))
        for second in rows[i + 1:]:
            if int(second.get("section_index", 0)) - int(first.get("section_index", 0)) > section_window:
                break
            b = second.get("norm") or normalize(second.get("text", ""))
            if not a or not b:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            shared = longest_common_substring(a, b)
            if ratio < ratio_warning and len(shared) < shared_issue:
                continue
            row = {
                "first": f"{first.get('section')}:{first.get('text')}",
                "second": f"{second.get('section')}:{second.get('text')}",
                "ratio": round(ratio, 3),
                "shared": shared,
            }
            pairs.append(row)
            if ratio >= ratio_issue:
                issues.append(
                    f"duplicate dialogue: {row['first']} / {row['second']} "
                    f"(similarity {ratio:.2f})")
            elif len(shared) >= shared_issue and ratio >= 0.35:
                issues.append(
                    f"repeated exposition: {row['first']} / {row['second']} "
                    f"(shared phrase {shared!r})")
            else:
                warnings.append(
                    f"near-duplicate dialogue: {row['first']} / {row['second']} "
                    f"(similarity {ratio:.2f})")
    return {
        "status": "pass" if not issues else "revise",
        "issues": issues,
        "warnings": warnings,
        "pairs": pairs,
        "metrics": {"lines": len(rows), "pairs": len(pairs)},
    }
