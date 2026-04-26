import argparse
import re
from pathlib import Path
from typing import Optional, Tuple


DEFAULT_ASS_HEADER = """[Script Info]
; This is an Advanced Sub Station Alpha v4+ script.
Title:
ScriptType: v4.00+
Collisions: Normal
PlayDepth: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SubStyle,Arial,20,&H0300FFFF,&H00FFFFFF,&H00000000,&H02000000,-1,0,0,0,100,100,0,0,3,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text"""


def _read_text_with_fallback(path: str) -> Tuple[str, str]:
    encodings = ["utf-32", "utf-16", "utf-8", "cp1252", "gb2312", "gbk", "big5"]
    last_error: Optional[Exception] = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as fd:
                return fd.read(), enc
        except Exception as exc:
            last_error = exc
            continue
    raise UnicodeError(f"Failed to decode {path!r} with supported encodings") from last_error


def _normalize_lines(raw_text: str) -> list[str]:
    text = raw_text.replace("\ufeff", "").replace("\r", "")
    return [line.strip() for line in text.split("\n") if line.strip()]


def _build_dialogue_lines(lines: list[str]) -> str:
    sub_lines = ""
    tmp_lines = ""
    line_count = 0
    for idx, line in enumerate(lines):
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        if line.isdigit() and re.match(r"-?\d\d:\d\d:\d\d", next_line):
            if tmp_lines:
                sub_lines += tmp_lines + "\n"
            tmp_lines = ""
            line_count = 0
            continue

        if re.match(r"-?\d\d:\d\d:\d\d", line):
            line = line.replace("-0", "0")
            tmp_lines += "Dialogue: 0," + line + ",SubStyle,,0,0,0,,"
        else:
            if line_count < 2:
                tmp_lines += line
            else:
                tmp_lines += "\n" + line
        line_count += 1

    sub_lines += tmp_lines + "\n"
    return sub_lines


def _apply_srt_to_ass_transform(text: str) -> str:
    text = re.sub(r"\d(\d:\d{2}:\d{2}),(\d{2})\d", r"\1.\2", text)
    text = re.sub(r"\s+-->\s+", ",", text)
    text = re.sub(r"<([ubi])>", r"{\\\g<1>1}", text)
    text = re.sub(r"</([ubi])>", r"{\\\g<1>0}", text)
    text = re.sub(r'<font\s+color="?#(\w{2})(\w{2})(\w{2})"?>', r"{\\c&H\3\2\1&}", text)
    text = re.sub(r"</font>", "", text)
    return text


def srt2ass(input_file: str) -> Optional[str]:
    if input_file.lower().endswith(".ass"):
        return input_file

    input_path = Path(input_file)
    if not input_path.is_file():
        print(f"{input_file} not exist")
        return None

    raw_text, encoding = _read_text_with_fallback(input_file)
    utf8bom = "\ufeff" if "\ufeff" in raw_text else ""
    lines = _normalize_lines(raw_text)
    dialogue_lines = _build_dialogue_lines(lines)
    dialogue_lines = _apply_srt_to_ass_transform(dialogue_lines)

    output_path = input_path.with_suffix(".ass")
    output_text = utf8bom + DEFAULT_ASS_HEADER + "\n" + dialogue_lines

    with open(output_path, "wb") as output:
        output.write(output_text.encode(encoding))

    return str(output_path).replace("\\", "\\\\").replace("/", "//")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert SRT subtitles to ASS.")
    parser.add_argument("inputs", nargs="+", help="Input subtitle files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for name in args.inputs:
        srt2ass(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
