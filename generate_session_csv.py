#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
現場スケジュール Excel から source/session.csv を生成する。

データソース:
- source/DiGRA夏26現場スケジュール案*.xlsx  （Sheet1 の時間割）

出力:
- source/session.csv

セッションID:
- 口頭セッションN → N
- 企画N → 14+N （15〜18）
- 全体行事（受付・オープニング等） → 19 以降

会場:
- 並列セッションは Excel の列順で トラック1〜3
- 全体行事は 全体

使い方:
    python3 generate_session_csv.py
    python3 generate_session_csv.py --xlsx source/foo.xlsx --output source/session.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from generate_talk_csv import SOURCE_DIR, normalize_text, read_xlsx_sheet

YEAR = 2026
DEFAULT_OUTPUT = SOURCE_DIR / "session.csv"
DEFAULT_XLSX_GLOB = "*260824*.xlsx"

TRACK_ROOMS = {3: "トラック1", 4: "トラック2", 5: "トラック3"}
PLENARY_ROOM = "全体"
KIKAKU_ID_OFFSET = 14
SPECIAL_ID_START = 19

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
TIME_RE = re.compile(r"(\d{1,2})時(半)?")
MINUTES_RE = re.compile(r"(\d+)\s*分")
SESSION_HEADER_RE = re.compile(r"^セッション(\d+)")
KIKAKU_HEADER_RE = re.compile(r"^企画(\d+)")
TALK_CELL_RE = re.compile(r"^\d{1,3}[\s\u3000]")


def cell(row: list[str], idx: int) -> str:
    if idx >= len(row):
        return ""
    return normalize_text(row[idx])


def parse_date(text: str) -> str | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    return f"{YEAR}-{int(m.group(1))}-{int(m.group(2))}"


def parse_time(text: str) -> tuple[int, int] | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    return int(m.group(1)), 30 if m.group(2) else 0


def fmt_time(hm: tuple[int, int]) -> str:
    h, m = hm
    return f"{h}:{m:02d}"


def add_minutes(hm: tuple[int, int], minutes: int) -> tuple[int, int]:
    total = hm[0] * 60 + hm[1] + minutes
    return divmod(total, 60)


def extract_minutes(*texts: str) -> int | None:
    blob = " ".join(t for t in texts if t)
    found = [int(x) for x in MINUTES_RE.findall(blob)]
    return sum(found) if found else None


def clean_session_name(name: str) -> str:
    name = name.replace("eSpoerts", "eSports")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def clean_chair(name: str) -> str:
    name = name.strip()
    if "（" in name and name.endswith(")"):
        name = name[:-1] + "）"
    return name


def plenary_name(raw: str) -> str:
    if raw.startswith("ライトニング"):
        return "ライトニングトーク・ファストフォワード"
    name = re.sub(r"\s+\d+\s*分.*$", "", raw)
    return clean_session_name(name)


def is_parallel_header(text: str) -> bool:
    return bool(SESSION_HEADER_RE.match(text) or KIKAKU_HEADER_RE.match(text))


def session_id_from_header(header: str) -> str | None:
    m = SESSION_HEADER_RE.match(header)
    if m:
        return m.group(1)
    m = KIKAKU_HEADER_RE.match(header)
    if m:
        return str(KIKAKU_ID_OFFSET + int(m.group(1)))
    return None


def kikaku_title(table: list[list[str]], header_row: int, col: int) -> str:
    """企画列の、発表番号で始まらない最初の本文をタイトルとみなす。"""
    for r in range(header_row + 1, min(header_row + 8, len(table))):
        value = cell(table[r], col)
        if not value:
            continue
        if TALK_CELL_RE.match(value):
            continue
        if is_parallel_header(value):
            break
        # 座長行（括弧や「・」を含む短い行）はスキップ
        if r == header_row + 1:
            continue
        return value
    return ""


def make_session(
    sid: str,
    name: str,
    date: str,
    start: tuple[int, int],
    end: tuple[int, int],
    chair: str,
    room: str,
) -> dict[str, str]:
    return {
        "セッションID": sid,
        "セッション名": clean_session_name(name),
        "日付": date,
        "時間": f"{fmt_time(start)}〜{fmt_time(end)}",
        "座長": clean_chair(chair),
        "会場": room,
    }


def collect_timed_rows(table: list[list[str]]) -> list[dict]:
    current_date = ""
    timed: list[dict] = []

    for i, row in enumerate(table):
        date_text = cell(row, 0)
        parsed_date = parse_date(date_text)
        if parsed_date:
            current_date = parsed_date

        start = parse_time(cell(row, 1))
        if start:
            timed.append(
                {
                    "row_idx": i,
                    "date": current_date,
                    "start": start,
                    "row": row,
                }
            )

    # 時刻なし行（インタラクティブセッション）を直前スロットの続きとして保持
    for item in timed:
        item["follow_rows"] = []
    timed_by_row = {item["row_idx"]: item for item in timed}
    last = None
    for i, row in enumerate(table):
        if i in timed_by_row:
            last = timed_by_row[i]
            continue
        if last is not None and cell(row, 2) and not parse_time(cell(row, 1)):
            # 次の時刻行の手前まで
            last["follow_rows"].append(row)
    return timed


def rows_to_sessions(table: list[list[str]]) -> list[dict[str, str]]:
    timed = collect_timed_rows(table)
    sessions: list[dict[str, str]] = []
    special_id = SPECIAL_ID_START

    for idx, item in enumerate(timed):
        row = item["row"]
        date = item["date"]
        start = item["start"]
        label = cell(row, 2)
        next_start = timed[idx + 1]["start"] if idx + 1 < len(timed) else None
        same_day_next = (
            next_start
            if idx + 1 < len(timed) and timed[idx + 1]["date"] == date
            else None
        )

        headers = [cell(row, col) for col in TRACK_ROOMS]
        if any(is_parallel_header(h) for h in headers):
            duration = extract_minutes(label) or 90
            end = add_minutes(start, duration)
            chair_row = table[item["row_idx"] + 1] if item["row_idx"] + 1 < len(table) else []
            for col, room in TRACK_ROOMS.items():
                header = cell(row, col)
                if not header:
                    continue
                sid = session_id_from_header(header) or str(special_id)
                if sid == str(special_id):
                    special_id += 1
                name = header
                if KIKAKU_HEADER_RE.match(header):
                    title = kikaku_title(table, item["row_idx"], col)
                    if title:
                        name = f"{header}：{title}"
                chair = cell(chair_row, col)
                sessions.append(make_session(sid, name, date, start, end, chair, room))
            continue

        duration = extract_minutes(label, cell(row, 3), cell(row, 7))
        if duration:
            end = add_minutes(start, duration)
        elif same_day_next:
            end = same_day_next
        else:
            end = add_minutes(start, 30)

        name = plenary_name(label)
        sessions.append(
            make_session(str(special_id), name, date, start, end, "", PLENARY_ROOM)
        )
        special_id += 1

        # 同じ時刻枠の続き（インタラクティブセッション）
        follow_start = end
        for follow in item.get("follow_rows", []):
            follow_label = cell(follow, 2)
            if not follow_label:
                continue
            if is_parallel_header(follow_label) or parse_time(cell(follow, 1)):
                continue
            follow_end = same_day_next if same_day_next else add_minutes(follow_start, 60)
            sessions.append(
                make_session(
                    str(special_id),
                    plenary_name(follow_label),
                    date,
                    follow_start,
                    follow_end,
                    "",
                    PLENARY_ROOM,
                )
            )
            special_id += 1
            follow_start = follow_end

    return sessions


def default_xlsx() -> Path:
    matches = sorted(SOURCE_DIR.glob(DEFAULT_XLSX_GLOB))
    if not matches:
        raise FileNotFoundError(f"{SOURCE_DIR / DEFAULT_XLSX_GLOB} が見つかりません")
    return matches[-1]


def write_session_csv(sessions: list[dict[str, str]], path: Path) -> None:
    fieldnames = ["セッションID", "セッション名", "日付", "時間", "座長", "会場"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sessions)


def main() -> None:
    parser = argparse.ArgumentParser(description="現場スケジュール Excel から session.csv を生成する")
    parser.add_argument("--xlsx", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    xlsx_path = args.xlsx if args.xlsx is not None else default_xlsx()
    if not xlsx_path.exists():
        raise SystemExit(f"エラー: {xlsx_path} が見つかりません")

    print(f"Excel を読み込み中: {xlsx_path}")
    table = read_xlsx_sheet(xlsx_path)
    sessions = rows_to_sessions(table)
    write_session_csv(sessions, args.output)
    print(f"完了: {args.output} に {len(sessions)} 件を書き出しました")
    for s in sessions:
        print(
            f"  {s['セッションID']:>3} {s['日付']} {s['時間']} {s['会場']} "
            f"{s['セッション名']} 座長={s['座長'] or '-'}"
        )


if __name__ == "__main__":
    main()
