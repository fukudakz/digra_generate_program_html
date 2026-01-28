#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日本デジタルゲーム学会 年次大会プログラム HTML 生成スクリプト

データソース:
- source/session.csv  （セッション情報）
- source/talk.csv     （各セッション内の発表）

出力:
- output/program.html （プログラムページ HTML）

使い方:
    cd digra_program_page
    python3 generate_program_html.py
"""

import csv
import os
import re
from pathlib import Path
from collections import defaultdict, OrderedDict
from datetime import datetime

BASE_DIR = Path(__file__).parent
SOURCE_DIR = BASE_DIR / "source"
OUTPUT_DIR = BASE_DIR / "output"

SESSION_CSV = SOURCE_DIR / "session.csv"
TALK_CSV = SOURCE_DIR / "talk.csv"
OUTPUT_HTML = OUTPUT_DIR / "program.html"
CONFERENCE_NAME_TXT = SOURCE_DIR / "conference_name.txt"


def read_sessions(path: Path):
    """session.csv を読み込んで辞書にする"""
    sessions = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # セッションIDは文字列のまま扱う（CSV内のIDと一致させるため）
            sessions.append(
                {
                    "id": row["セッションID"].strip(),
                    "name": row["セッション名"].strip(),
                    "date": row["日付"].strip(),
                    "time": row["時間"].strip(),
                    "chair": row["座長"].strip(),
                    "room": row["会場"].strip(),
                }
            )
    return sessions


def read_talks(path: Path):
    """talk.csv を読み込んでセッションIDごとにグループ化"""
    talks_by_session = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            session_id = row["所属するセッション"].strip()
            talks_by_session[session_id].append(
                {
                    "id": row["発表ID"].strip(),
                    "easychair_id": row["easychair_paper_ID"].strip(),
                    "authors": row["著者"].strip(),
                    "title": row["タイトル"].strip(),
                }
            )

    # 各セッション内の発表を発表IDでソート
    for sid, talks in talks_by_session.items():
        talks.sort(key=lambda t: int(t["id"]) if t["id"].isdigit() else t["id"])

    return talks_by_session


def format_date_jp(date_str: str) -> str:
    """YYYY-M-D または YYYY-MM-DD 形式の日付を「YYYY年M月D日(曜)」に整形"""
    try:
        # ハイフン区切りを想定（例: 2026-2-21）
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # フォーマットが不明な場合はそのまま返す
            return date_str

    weekday_map = ["月", "火", "水", "木", "金", "土", "日"]
    youbi = weekday_map[dt.weekday()]
    return f"{dt.year}年{dt.month}月{dt.day}日（{youbi}）"


_TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2})")


def room_sort_key(room: str):
    """
    タイムテーブル用の教室ソートキー。
    「受付」「懇親会」「昼食」を含む列は右側（後ろ）に寄せる。
    """
    special_keywords = ("受付", "懇親会", "昼食")
    is_special = any(k in room for k in special_keywords)
    # is_special が False (0) の部屋が左側、True (1) が右側
    return (1 if is_special else 0, room)


def start_time_key(time_str: str):
    """時間文字列から開始時刻を (hour, minute) のタプルで返す"""
    # 区切り記号（全角/半角の波ダッシュなど）で開始時刻部分を取り出す
    for sep in ("〜", "～", "-", "―", "−"):
        if sep in time_str:
            time_str = time_str.split(sep)[0]
            break
    m = _TIME_PATTERN.search(time_str)
    if not m:
        # パースできない場合は末尾に回す
        return (99, 99)
    h = int(m.group(1))
    mi = int(m.group(2))
    return (h, mi)


def group_sessions_by_date(sessions):
    """日付ごとにセッションをグループ化して、日付・時間順にソート"""
    grouped = defaultdict(list)
    for s in sessions:
        grouped[s["date"]].append(s)

    # 日付順にソートされた OrderedDict を返す
    def sort_key_date(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            return d

    ordered = OrderedDict()
    for date in sorted(grouped.keys(), key=sort_key_date):
        # 各日付内で開始時刻順にソート
        grouped[date].sort(key=lambda s: start_time_key(s["time"]))
        ordered[date] = grouped[date]
    return ordered


def generate_html(sessions, talks_by_session, conference_name: str):
    """HTML文字列を生成"""
    grouped = group_sessions_by_date(sessions)

    html = []
    html.append("<!DOCTYPE html>")
    html.append('<html lang="ja">')
    html.append("<head>")
    html.append('  <meta charset="UTF-8">')
    html.append("  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    html.append(f"  <title>{conference_name}</title>")
    # スタイル（サンプルページ風の見た目）
    html.append("  <style>")
    html.append("    body {")
    html.append("      font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, 'Hiragino Kaku Gothic ProN', 'Meiryo', sans-serif;")
    html.append("      line-height: 1.7;")
    html.append("      font-size: 15px;")
    html.append("      color: #333;")
    html.append("      background: #f5f5f5;")
    html.append("      margin: 0;")
    html.append("      padding: 0;")
    html.append("    }")
    html.append("    .page-wrap {")
    html.append("      max-width: 960px;")
    html.append("      margin: 0 auto;")
    html.append("      padding: 32px 16px 64px;")
    html.append("      background: #fff;")
    html.append("    }")
    html.append("    h1 {")
    html.append("      font-size: 26px;")
    html.append("      margin-top: 0;")
    html.append("      margin-bottom: 24px;")
    html.append("      border-bottom: 2px solid #e5e5e5;")
    html.append("      padding-bottom: 8px;")
    html.append("    }")
    html.append("    h2 {")
    html.append("      font-size: 20px;")
    html.append("      margin-top: 32px;")
    html.append("      margin-bottom: 12px;")
    html.append("      border-left: 4px solid #0073a8;")
    html.append("      padding-left: 8px;")
    html.append("    }")
    html.append("    h3 {")
    html.append("      font-size: 17px;")
    html.append("      margin-top: 20px;")
    html.append("      margin-bottom: 8px;")
    html.append("      color: #0073a8;")
    html.append("    }")
    html.append("    .date-block {")
    html.append("      margin-top: 24px;")
    html.append("    }")
    html.append("    .session {")
    html.append("      margin: 8px 0 14px;")
    html.append("      padding: 8px 12px 10px;")
    html.append("      border: 1px solid #e1e1e1;")
    html.append("      border-radius: 3px;")
    html.append("      background: #fafafa;")
    html.append("    }")
    html.append("    .session-header {")
    html.append("      margin-bottom: 4px;")
    html.append("    }")
    html.append("    .session-location {")
    html.append("      font-size: 13px;")
    html.append("      color: #555;")
    html.append("    }")
    html.append("    .session-title {")
    html.append("      font-size: 16px;")
    html.append("      font-weight: 600;")
    html.append("      color: #0073a8;")
    html.append("      margin-top: 2px;")
    html.append("    }")
    html.append("    .session-meta {")
    html.append("      font-size: 13px;")
    html.append("      color: #666;")
    html.append("      margin-bottom: 4px;")
    html.append("    }")
    html.append("    .talk-list {")
    html.append("      margin: 6px 0 0 1.5em;")
    html.append("      padding: 0;")
    html.append("    }")
    html.append("    .talk-list li {")
    html.append("      margin-bottom: 6px;")
    html.append("    }")
    html.append("    .talk-title {")
    html.append("      font-weight: 600;")
    html.append("    }")
    html.append("    .talk-authors {")
    html.append("      font-size: 13px;")
    html.append("      color: #555;")
    html.append("    }")
    html.append("    .schedule-table-wrap {")
    html.append("      margin-top: 8px;")
    html.append("      margin-bottom: 18px;")
    html.append("    }")
    html.append("    .schedule-table {")
    html.append("      border-collapse: collapse;")
    html.append("      width: 100%;")
    html.append("      table-layout: fixed;")
    html.append("      font-size: 13px;")
    html.append("    }")
    html.append("    .schedule-table th, .schedule-table td {")
    html.append("      border: 1px solid #ddd;")
    html.append("      padding: 4px 6px;")
    html.append("      text-align: center;")
    html.append("      vertical-align: top;")
    html.append("    }")
    html.append("    .schedule-table thead th {")
    html.append("      background: #f0f4f8;")
    html.append("      font-weight: 600;")
    html.append("    }")
    html.append("    .schedule-time {")
    html.append("      white-space: nowrap;")
    html.append("      background: #f9fafb;")
    html.append("    }")
    html.append("    .schedule-table td {")
    html.append("      font-size: 12px;")
    html.append("    }")
    html.append("    .schedule-table a {")
    html.append("      color: #0073a8;")
    html.append("      text-decoration: none;")
    html.append("    }")
    html.append("    .schedule-table a:hover {")
    html.append("      text-decoration: underline;")
    html.append("    }")
    html.append("    @media screen and (max-width: 600px) {")
    html.append("      .page-wrap { padding: 16px 8px 40px; }")
    html.append("      h1 { font-size: 22px; }")
    html.append("      h2 { font-size: 18px; }")
    html.append("      h3 { font-size: 16px; }")
    html.append("    }")
    html.append("  </style>")
    html.append("</head>")
    html.append("<body>")
    html.append('<div class="page-wrap">')

    html.append(f"<h1>{conference_name}</h1>")

    # まず全日程のタイムテーブルをまとめて表示
    html.append("<h2>タイムテーブル</h2>")
    for date_str, sess_list in grouped.items():
        html.append('<div class="date-block">')
        html.append(f"  <h3>{format_date_jp(date_str)}</h3>")

        # タイムテーブルの列順:
        # セルの値（セッション名）に「受付」「懇親会」「昼食」が含まれる部屋を右側に寄せる
        all_rooms = {s["room"] for s in sess_list}
        special_keywords = ("受付", "懇親会", "昼食")
        special_rooms = {
            s["room"]
            for s in sess_list
            if any(k in s["name"] for k in special_keywords)
        }
        rooms = sorted(all_rooms, key=lambda r: (1 if r in special_rooms else 0, r))
        times = sorted({s["time"] for s in sess_list}, key=start_time_key)

        if rooms and times:
            time_room_index = defaultdict(list)
            for s in sess_list:
                time_room_index[(s["time"], s["room"])].append(s)

            html.append('  <div class="schedule-table-wrap">')
            html.append('    <table class="schedule-table">')
            html.append("      <thead>")
            html.append("        <tr>")
            html.append('          <th class="schedule-time">時間</th>')
            for room in rooms:
                html.append(f"          <th>{room}</th>")
            html.append("        </tr>")
            html.append("      </thead>")
            html.append("      <tbody>")
            for t in times:
                html.append("        <tr>")
                html.append(f'          <th class="schedule-time">{t}</th>')
                for room in rooms:
                    cell_sessions = time_room_index.get((t, room), [])
                    if cell_sessions:
                        # セッション詳細へのページ内リンク
                        links = "<br>".join(
                            f'<a href="#session-{ses["id"]}">{ses["name"]}</a>'
                            for ses in cell_sessions
                        )
                        html.append(f"          <td>{links}</td>")
                    else:
                        html.append("          <td></td>")
                html.append("        </tr>")
            html.append("      </tbody>")
            html.append("    </table>")
            html.append("  </div>")

        html.append("</div>")  # .date-block

    # 続いてプログラム詳細を表示
    html.append("<h2>プログラム詳細</h2>")

    for date_str, sess_list in grouped.items():
        html.append('<div class="date-block">')
        html.append(f"  <h3>{format_date_jp(date_str)}</h3>")

        # 同じ時間帯のセッションをまとめる（詳細リスト）
        sessions_by_time = defaultdict(list)
        for s in sess_list:
            sessions_by_time[s["time"]].append(s)

        # 時間順に出力（開始時刻でソート）
        for time_str in sorted(sessions_by_time.keys(), key=start_time_key):
            html.append(f'  <h4>{time_str}</h4>')

            # 同じ時間帯のセッションは教室名（room）でソート
            for s in sorted(sessions_by_time[time_str], key=lambda x: x["room"]):
                sid = s["id"]
                anchor_id = f"session-{sid}"
                html.append('  <div class="session">')
                # セッションヘッダ: 場所とセッション名を分けて表示
                html.append('    <div class="session-header">')
                html.append(f'      <div class="session-location">{s["room"]}</div>')
                html.append(f'      <div class="session-title" id="{anchor_id}">{s["name"]}</div>')
                html.append("    </div>")
                # 座長などメタ情報
                if s["chair"]:
                    html.append(f'    <div class="session-meta">座長：{s["chair"]}</div>')

                # 発表一覧（登録がある場合のみ表示）
                talks = talks_by_session.get(sid, [])
                if talks:
                    html.append('    <ol class="talk-list">')
                    for t in talks:
                        html.append("      <li>")
                        title = t["title"]
                        authors = t["authors"]
                        html.append(f'        <div class="talk-title">{title}</div>')
                        if authors:
                            html.append(f'        <div class="talk-authors">{authors}</div>')
                        html.append("      </li>")
                    html.append("    </ol>")

                html.append("  </div>")  # .session

        html.append("</div>")  # .date-block

    html.append("</div>")  # .page-wrap
    html.append("</body>")
    html.append("</html>")

    return "\n".join(html)


def main():
    if not SESSION_CSV.exists():
        print(f"エラー: {SESSION_CSV} が見つかりません")
        return
    if not TALK_CSV.exists():
        print(f"エラー: {TALK_CSV} が見つかりません")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("セッション情報を読み込み中...")
    sessions = read_sessions(SESSION_CSV)
    print(f"  セッション数: {len(sessions)}")

    print("発表情報を読み込み中...")
    talks_by_session = read_talks(TALK_CSV)
    total_talks = sum(len(v) for v in talks_by_session.values())
    print(f"  発表数: {total_talks}")

    # 大会名の読み込み（なければデフォルト値）
    if CONFERENCE_NAME_TXT.exists():
        conference_name = CONFERENCE_NAME_TXT.read_text(encoding="utf-8").strip()
    else:
        conference_name = "日本デジタルゲーム学会 年次大会 プログラム"

    print("HTMLを生成中...")
    html = generate_html(sessions, talks_by_session, conference_name)

    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"完了: {OUTPUT_HTML} を生成しました")


if __name__ == "__main__":
    main()

