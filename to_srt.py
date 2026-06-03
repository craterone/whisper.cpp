#!/usr/bin/env python3
"""Convert Whisper JSON output to token-level SRT."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Whisper JSON to token-level SRT.")
    parser.add_argument("input", help="Input JSON file path")
    parser.add_argument("output", nargs="?", help="Output SRT file path (default: same name as input with .srt)")
    parser.add_argument("--keep-special", action="store_true", help="Keep special tokens like [_BEG_] or [_TT_94]")
    return parser.parse_args()


def parse_timestamp(ts: str) -> str:
    # Ensure proper SRT formatting with comma-separated milliseconds.
    if "." in ts:
        ts = ts.replace(".", ",")
    if "," not in ts:
        ts = f"{ts},000"
    return ts


def ms_to_timestamp(ms: int) -> str:
    """Convert milliseconds to SRT timestamp format."""
    if ms < 0:
        return "00:00:00,000"
    hours = ms // 3600000
    remainder = ms % 3600000
    minutes = remainder // 60000
    remainder = remainder % 60000
    seconds = remainder // 1000
    milliseconds = remainder % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def is_special_token(text: str) -> bool:
    cleaned = text.strip()
    return cleaned.startswith("[_") and cleaned.endswith("]")


def is_punctuation(text: str) -> bool:
    """Check if token is pure punctuation."""
    return bool(text) and all(not c.isalnum() and not c.isspace() for c in text)


def should_merge_with_previous(text: str) -> bool:
    """Check if token should be merged with previous (first char is not space)."""
    return text and not text[0].isspace()


def build_srt_entries(data: Dict[str, Any], keep_special: bool) -> List[Dict[str, str]]:
    """Build SRT entries from transcription segments, handling space-less segments as single lines."""
    if "transcription" not in data or not isinstance(data["transcription"], list):
        return []
    
    entries = []
    
    for seg_idx, segment in enumerate(data["transcription"]):
        segment_ts = segment.get("timestamps", {})
        segment_from = segment_ts.get("from") if segment_ts else None
        segment_to = segment_ts.get("to") if segment_ts else None
        
        # Parse segment timestamps
        time_from = parse_timestamp(segment_from) if segment_from else "00:00:00,000"
        time_to = parse_timestamp(segment_to) if segment_to else "00:00:00,000"
        
        # Get tokens for this segment
        seg_tokens = segment.get("tokens", [])
        filtered_tokens = []
        for token_idx, token in enumerate(seg_tokens):
            token_text = token.get("text", "")
            if not keep_special and is_special_token(token_text):
                continue
            filtered_tokens.append({
                "text": token_text,
                "t_dtw": token.get("t_dtw", -1),
                "seg_idx": seg_idx,
                "tok_idx": token_idx,
            })
            
        if not filtered_tokens:
            continue
            
        # Reconstruct the cleaned segment text from filtered tokens
        cleaned_seg_text = "".join(tok["text"] for tok in filtered_tokens)
        
        # Check if the segment text has no spaces after stripping whitespace
        stripped_text = cleaned_seg_text.strip()
        has_no_space = not any(c.isspace() for c in stripped_text)
        
        if has_no_space:
            # Directly use segment start and end, and the entire segment is one SRT entry
            entry = {
                "from": time_from,
                "to": time_to,
                "text": cleaned_seg_text,
            }
            # Print the source of timestamps and final text for each line
            line_num = len(entries) + 1
            # print(f"Line {line_num:03d} | Text: {cleaned_seg_text!r:30} | From Source: segment_from={segment_from:<13} ({time_from}) | To Source: segment_to={segment_to:<22} ({time_to})")
            entries.append(entry)
        else:
            # 检查是否存在重复的 t_dtw 值
            # t_dtws = [tok["t_dtw"] for tok in filtered_tokens if tok["t_dtw"] >= 0]
            # seen = set()
            # duplicates = set(x for x in t_dtws if x in seen or seen.add(x))
            # if duplicates:
            #     print(f"Segment: {cleaned_seg_text!r}")
            #     for tok in filtered_tokens:
            #         print(f"  text: {tok['text']!r}, t_dtw: {tok['t_dtw']}")

            # Process using token-level merging logic within this segment
            i = 0
            while i < len(filtered_tokens):
                current = filtered_tokens[i]
                merged_text = current["text"]
                merged_tokens = [current]
                
                # Collect consecutive tokens that should be merged (non-space start)
                j = i + 1
                while j < len(filtered_tokens):
                    next_tok = filtered_tokens[j]
                    if not should_merge_with_previous(next_tok["text"]):
                        break
                    merged_text += next_tok["text"]
                    merged_tokens.append(next_tok)
                    j += 1
                
                # Determine "from" time
                # First entry of the segment: use segment's "from"
                # Other entries: use previous token's t_dtw
                if i == 0:
                    entry_from = time_from
                    from_source = f"segment_from={segment_from}"
                else:
                    prev_tok = filtered_tokens[i - 1]
                    prev_t_dtw = prev_tok["t_dtw"]
                    entry_from = ms_to_timestamp(prev_t_dtw * 10) if prev_t_dtw >= 0 else "00:00:00,000"
                    from_source = f"prev_tok_t_dtw={prev_t_dtw}"
                
                # Determine "to" time
                last_merged = merged_tokens[-1]
                if len(merged_tokens) > 1 and is_punctuation(last_merged["text"]):
                    # Use second-to-last token's t_dtw
                    end_t_dtw = merged_tokens[-2]["t_dtw"]
                    to_source = f"second_to_last_tok_t_dtw={end_t_dtw}"
                else:
                    # Use last token's t_dtw
                    end_t_dtw = last_merged["t_dtw"]
                    to_source = f"last_tok_t_dtw={end_t_dtw}"
                
                entry_to = ms_to_timestamp(end_t_dtw * 10) if end_t_dtw >= 0 else "00:00:00,000"
                
                # 如果 entry 位于 segment 的结尾，且 segment 的 end > entry end，使用 segment 的 end 修复 entry 的 end
                if j == len(filtered_tokens):
                    if time_to > entry_to:
                        entry_to = time_to
                
                # Print the source of timestamps and final text for each line
                line_num = len(entries) + 1
                # print(f"Line {line_num:03d} | Text: {merged_text!r:30} | From Source: {from_source:<25} ({entry_from}) | To Source: {to_source:<35} ({entry_to})")
                
                entries.append({
                    "from": entry_from,
                    "to": entry_to,
                    "text": merged_text,
                })
                
                if entry_to <= entry_from:
                    from datetime import datetime
                    log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"[{log_time}] 警告: 发现 end <= start ({entry_to} <= {entry_from})，组词: '{merged_text}' | "
                        f"对应 Segment {seg_idx}: 时间 ({time_from} --> {time_to}), 文本: '{segment.get('text', '').strip()}'"
                    )
                
                i = j
    
    return entries


def format_srt(entries: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for idx, entry in enumerate(entries, start=1):
        lines.append(str(idx))
        lines.append(f"{entry['from']} --> {entry['to']}")
        lines.append(entry["text"].replace("\n", " "))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(".srt")

    with input_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    entries = build_srt_entries(data, args.keep_special)

    if not entries:
        raise SystemExit("No token entries were found in the JSON input.")

    output_text = format_srt(entries)
    output_path.write_text(output_text, encoding="utf-8")
    print(f"Wrote {len(entries)} SRT entries to {output_path}")


if __name__ == "__main__":
    main()
