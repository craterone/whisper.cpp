#!/usr/bin/env python3

import re
import sys
from pathlib import Path

TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)

def parse_time(t):
    m = TIME_RE.match(t.strip())
    if not m:
        raise ValueError(f"Invalid timestamp: {t}")

    h, m_, s, ms = map(int, m.groups())
    return (((h * 60) + m_) * 60 + s) * 1000 + ms


def parse_srt(path):
    subtitles = []

    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = block.splitlines()

        if len(lines) < 2:
            continue

        if "-->" not in lines[1]:
            continue

        start_str, end_str = [
            x.strip() for x in lines[1].split("-->")
        ]

        subtitles.append({
            "index": lines[0].strip(),
            "start": parse_time(start_str),
            "end": parse_time(end_str),
            "time_line": lines[1]
        })

    return subtitles


def check_srt(path):
    subs = parse_srt(path)

    errors = []

    # 规则1: end > start
    for sub in subs:
        if sub["end"] <= sub["start"]:
            errors.append(
                f"Line {sub['index']}: end <= start "
                f"({sub['time_line']})"
            )

    # 规则2: next.start > prev.end
    for prev, curr in zip(subs, subs[1:]):
        if curr["start"] < prev["end"]:
            errors.append(
                f"Overlap: line {curr['index']} start <= "
                f"line {prev['index']} end"
                f" ({curr['start']} <= {prev['end']})"
            )

    if errors:
        print(f"Found {len(errors)} error(s):")
        for err in errors:
            print(err)
        return 1

    print(f"OK: {len(subs)} subtitles checked")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} file.srt")
        sys.exit(1)

    sys.exit(check_srt(sys.argv[1]))