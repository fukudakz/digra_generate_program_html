#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EasyChair の投稿一覧 Excel から source/talk.csv を生成する。

データソース:
- source/DiGRA_JAPAN_*.xlsx  （Submissions シート）
- source/DiGRA夏26現場スケジュール案*.xlsx  （所属セッション）
- source/session.csv  （セッションID）

出力:
- source/talk.csv

著者名は 1st_Author_name, 2nd_Author_name, ... を合成する。
EasyChair の Authors 欄より、こちらが正しい日本語名（姓・名の順）になっている。
（1st_Author_afiliation は所属なので使わない）
5人目以降は Authors_and_Affiliation_JP から氏名だけ抜き出して追加する。
所属するセッションは現場スケジュールの発表番号（および企画タイトル・Track）から埋める。

使い方:
    python3 generate_talk_csv.py
    python3 generate_talk_csv.py --xlsx source/foo.xlsx --output source/talk.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

BASE_DIR = Path(__file__).parent
SOURCE_DIR = BASE_DIR / "source"
DEFAULT_OUTPUT = SOURCE_DIR / "talk.csv"
DEFAULT_XLSX_GLOB = "DiGRA_JAPAN_*.xlsx"
DEFAULT_SCHEDULE_GLOB = "*260824*.xlsx"
SESSION_CSV = SOURCE_DIR / "session.csv"
PAPER_ID_RE = re.compile(r"^(\d{1,3})[\s\u3000]")
TALK_CSV_FIELDS = ["発表ID", "easychair_paper_ID", "所属するセッション", "著者", "タイトル"]

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
AUTHOR_NAME_COLUMNS = [
    "1st_Author_name",
    "2nd_Author_name",
    "3rd_Author_name",
    "4th_Author_name",
]
EXTRA_AUTHORS_COLUMN = "Authors_and_Affiliation_JP"
FALLBACK_AUTHORS_COLUMN = "Authors"

# 所属を囲む括弧（全角・半角）を取り除く
_AFFILIATION_RE = re.compile(r"[（(][^）)]*[）)]$")
_WHITESPACE_RE = re.compile(r"[\s\u3000]+")


def col_letters_to_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def split_cell_ref(ref: str) -> tuple[str, int]:
    i = 0
    while i < len(ref) and ref[i].isalpha():
        i += 1
    return ref[:i], int(ref[i:])


def shared_string_text(si: ET.Element) -> str:
    texts = [t.text or "" for t in si.iter(f"{{{NS_MAIN}}}t")]
    return "".join(texts)


def read_xlsx_sheet(path: Path) -> list[list[str]]:
    """xlsx を ZIP/XML として読み、最初のシートを行リストで返す（openpyxl 不要）。"""
    with zipfile.ZipFile(path) as zf:
        ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        shared = [shared_string_text(si) for si in ss_root.findall(f"{{{NS_MAIN}}}si")]
        sheet_root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))

    rows: dict[int, dict[int, str]] = {}
    max_col = 0
    for row_el in sheet_root.find(f"{{{NS_MAIN}}}sheetData").findall(f"{{{NS_MAIN}}}row"):
        row_idx = int(row_el.get("r"))
        cells: dict[int, str] = {}
        for cell in row_el.findall(f"{{{NS_MAIN}}}c"):
            letters, _ = split_cell_ref(cell.get("r"))
            col_idx = col_letters_to_index(letters)
            max_col = max(max_col, col_idx)
            value_el = cell.find(f"{{{NS_MAIN}}}v")
            if value_el is None or value_el.text is None:
                continue
            raw = value_el.text
            if cell.get("t") == "s":
                cells[col_idx] = shared[int(raw)]
            else:
                cells[col_idx] = raw
        rows[row_idx] = cells

    table: list[list[str]] = []
    for r in range(1, (max(rows) if rows else 0) + 1):
        cells = rows.get(r, {})
        table.append([cells.get(c, "") for c in range(max_col + 1)])
    return table


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value)).strip()


def looks_like_name(value: str) -> bool:
    """キーワード等が誤って名前欄に入っている行を除外する。"""
    if not value:
        return False
    if value.count(",") >= 2:
        return False
    return True


def extra_author_names(raw: str) -> list[str]:
    """Authors_and_Affiliation_JP から氏名だけ取り出す。"""
    names: list[str] = []
    for part in re.split(r"[,、]", raw):
        name = normalize_text(part)
        name = _AFFILIATION_RE.sub("", name).strip()
        if looks_like_name(name):
            names.append(name)
    return names


def collect_authors(row: dict[str, str]) -> str:
    names: list[str] = []
    for col in AUTHOR_NAME_COLUMNS:
        name = normalize_text(row.get(col, ""))
        if looks_like_name(name):
            names.append(name)

    extra = normalize_text(row.get(EXTRA_AUTHORS_COLUMN, ""))
    if extra:
        names.extend(extra_author_names(extra))

    if not names:
        fallback = normalize_text(row.get(FALLBACK_AUTHORS_COLUMN, ""))
        fallback = fallback.replace(" and ", ", ")
        names = [n.strip() for n in fallback.split(",") if n.strip()]

    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])} and {names[-1]}"


def rows_to_talks(table: list[list[str]]) -> list[dict[str, str]]:
    if not table:
        raise ValueError("Excel が空です")
    headers = [normalize_text(h) for h in table[0]]
    required = {"#", "Title", *AUTHOR_NAME_COLUMNS[:1]}
    missing = required - set(headers)
    if missing:
        raise ValueError(f"必要な列がありません: {', '.join(sorted(missing))}")

    talks: list[dict[str, str]] = []
    talk_id = 1
    for raw in table[1:]:
        row = {headers[i]: (raw[i] if i < len(raw) else "") for i in range(len(headers))}
        paper_id = normalize_text(row.get("#", ""))
        title = normalize_text(row.get("Title", ""))
        if not paper_id and not title:
            continue
        talks.append(
            {
                "発表ID": str(talk_id),
                "easychair_paper_ID": paper_id,
                "所属するセッション": "",
                "著者": collect_authors(row),
                "タイトル": title,
                "_track": normalize_text(row.get("Track", "")),
                "_order": 10_000 + talk_id,
            }
        )
        talk_id += 1
    return talks


def default_schedule_xlsx() -> Path | None:
    matches = sorted(SOURCE_DIR.glob(DEFAULT_SCHEDULE_GLOB))
    return matches[-1] if matches else None


def load_sessions(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def session_id_containing(sessions: list[dict[str, str]], keyword: str) -> str:
    for s in sessions:
        if keyword in s.get("セッション名", ""):
            return s["セッションID"].strip()
    return ""


def normalize_title(text: str) -> str:
    return normalize_text(text).replace("✕", "×").replace(" ", "")


def collect_schedule_assignments(
    schedule_table: list[list[str]],
) -> tuple[dict[str, str], list[tuple[str, str]], dict[str, int]]:
    """現場スケジュールから paper_id → session_id と企画タイトル、枠内順を返す。"""
    from generate_session_csv import (
        KIKAKU_HEADER_RE,
        TRACK_ROOMS,
        cell,
        collect_timed_rows,
        is_parallel_header,
        kikaku_title,
        session_id_from_header,
    )

    paper_to_session: dict[str, str] = {}
    paper_order: dict[str, int] = {}
    kikaku_titles: list[tuple[str, str]] = []
    timed = collect_timed_rows(schedule_table)

    for idx, item in enumerate(timed):
        row = item["row"]
        headers = [cell(row, col) for col in TRACK_ROOMS]
        if not any(is_parallel_header(h) for h in headers):
            continue
        end_row = timed[idx + 1]["row_idx"] if idx + 1 < len(timed) else len(schedule_table)
        start_row = item["row_idx"]
        for col in TRACK_ROOMS:
            header = cell(row, col)
            if not header:
                continue
            sid = session_id_from_header(header)
            if not sid:
                continue
            if KIKAKU_HEADER_RE.match(header):
                title = kikaku_title(schedule_table, start_row, col)
                if title:
                    kikaku_titles.append((sid, title))
            order = 0
            for r in range(start_row + 2, end_row):
                value = cell(schedule_table[r], col)
                m = PAPER_ID_RE.match(value)
                if not m:
                    continue
                paper_id = m.group(1)
                paper_to_session[paper_id] = sid
                paper_order[paper_id] = order
                order += 1
    return paper_to_session, kikaku_titles, paper_order


def match_kikaku_talk(title: str, talks: list[dict[str, str]]) -> dict[str, str] | None:
    needle = normalize_title(title)
    if not needle:
        return None
    best = None
    best_score = 0.0
    for talk in talks:
        if talk["所属するセッション"]:
            continue
        hay = normalize_title(talk["タイトル"])
        if needle in hay or hay in needle:
            return talk
        score = SequenceMatcher(None, needle, hay[: max(len(needle) * 2, 1)]).ratio()
        if score > best_score:
            best_score = score
            best = talk
    if best is not None and best_score >= 0.35:
        return best
    return None


def assign_sessions(
    talks: list[dict[str, str]],
    schedule_table: list[list[str]],
    sessions: list[dict[str, str]],
) -> None:
    paper_to_session, kikaku_titles, paper_order = collect_schedule_assignments(schedule_table)
    session_order = {s["セッションID"].strip(): i for i, s in enumerate(sessions)}
    lightning_id = session_id_containing(sessions, "ライトニング")
    interactive_id = session_id_containing(sessions, "インタラクティブセッション")

    for talk in talks:
        sid = paper_to_session.get(talk["easychair_paper_ID"], "")
        if sid:
            talk["所属するセッション"] = sid
            talk["_order"] = session_order.get(sid, 999) * 100 + paper_order.get(
                talk["easychair_paper_ID"], 50
            )

    for sid, title in kikaku_titles:
        talk = match_kikaku_talk(title, talks)
        if talk is None:
            print(f"警告: 企画タイトルに対応する発表が見つかりません: {title}")
            continue
        talk["所属するセッション"] = sid
        talk["_order"] = session_order.get(sid, 999) * 100

    for talk in talks:
        if talk["所属するセッション"]:
            continue
        track = talk.get("_track", "")
        if "インタラクティブ" in track and interactive_id:
            talk["所属するセッション"] = interactive_id
            talk["_order"] = session_order.get(interactive_id, 999) * 100 + int(
                talk["easychair_paper_ID"] or 0
            )
        elif "ライトニング" in track and lightning_id:
            talk["所属するセッション"] = lightning_id
            talk["_order"] = session_order.get(lightning_id, 999) * 100 + int(
                talk["easychair_paper_ID"] or 0
            )

    talks.sort(key=lambda t: (t.get("_order", 10_000), int(t["easychair_paper_ID"] or 0)))
    for i, talk in enumerate(talks, start=1):
        talk["発表ID"] = str(i)

    unassigned = [t for t in talks if not t["所属するセッション"]]
    if unassigned:
        ids = ", ".join(t["easychair_paper_ID"] for t in unassigned)
        print(f"警告: セッション未割当が {len(unassigned)} 件あります: {ids}")


def default_xlsx() -> Path:
    matches = sorted(SOURCE_DIR.glob(DEFAULT_XLSX_GLOB))
    if not matches:
        raise FileNotFoundError(
            f"{SOURCE_DIR / DEFAULT_XLSX_GLOB} が見つかりません"
        )
    return matches[-1]


def write_talk_csv(talks: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=TALK_CSV_FIELDS,
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(talks)


def main() -> None:
    parser = argparse.ArgumentParser(description="EasyChair Excel から talk.csv を生成する")
    parser.add_argument("--xlsx", type=Path, default=None, help="入力 Excel（省略時は source/DiGRA_JAPAN_*.xlsx）")
    parser.add_argument("--schedule", type=Path, default=None, help="現場スケジュール Excel")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="出力 CSV")
    args = parser.parse_args()

    xlsx_path = args.xlsx if args.xlsx is not None else default_xlsx()
    if not xlsx_path.exists():
        raise SystemExit(f"エラー: {xlsx_path} が見つかりません")

    print(f"Excel を読み込み中: {xlsx_path}")
    table = read_xlsx_sheet(xlsx_path)
    talks = rows_to_talks(table)

    schedule_path = args.schedule if args.schedule is not None else default_schedule_xlsx()
    if schedule_path and schedule_path.exists() and SESSION_CSV.exists():
        print(f"スケジュールを読み込み中: {schedule_path}")
        assign_sessions(talks, read_xlsx_sheet(schedule_path), load_sessions(SESSION_CSV))
    else:
        print("警告: スケジュールまたは session.csv がないため、所属セッションは空欄です")

    write_talk_csv(talks, args.output)
    print(f"完了: {args.output} に {len(talks)} 件を書き出しました")


if __name__ == "__main__":
    main()
