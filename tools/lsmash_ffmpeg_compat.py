"""Adapt L-SMASH-Works uses of the two libavcodec APIs removed in FFmpeg 9."""

import argparse
from pathlib import Path
import re

HEADER = "bluraysubtitle_ffmpeg_compat.h"
COMPATIBILITY_API = """\
#ifndef BLURAYSUBTITLE_FFMPEG_COMPAT_H
#define BLURAYSUBTITLE_FFMPEG_COMPAT_H
#include <libavcodec/avcodec.h>
#include <libavcodec/version.h>

typedef int (*lw_split_callback)(AVCodecContext *, const uint8_t *, int);

static inline lw_split_callback lw_get_split_callback(const AVCodecParserContext *ctx)
{
#if LIBAVCODEC_VERSION_MAJOR < 63
    return ctx->parser->split;
#else
    /* The caller already has paths for parsers without a split callback. */
    (void)ctx;
    return NULL;
#endif
}

static inline const enum AVPixelFormat *lw_supported_pix_fmts(const AVCodec *codec)
{
#if LIBAVCODEC_VERSION_MAJOR < 63
    return codec->pix_fmts;
#else
    const void *formats = NULL;
    if (avcodec_get_supported_config(NULL, codec, AV_CODEC_CONFIG_PIX_FORMAT, 0, &formats, NULL) < 0)
        return NULL;
    return (const enum AVPixelFormat *)formats;
#endif
}
#endif
"""
# Mask comments and literals without moving the positions of the surrounding C tokens.
NON_CODE = re.compile(r"""/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'""", re.S)
MEMBER = re.compile(r"\b(?P<context>\w+(?:\s*(?:->|\.)\s*\w+)*?)\s*->\s*parser\s*->\s*split\b"
                    r"|\b(?P<codec>\w+)\s*->\s*pix_fmts\b")


def active_code(code, major):
    """Skip obsolete API fallbacks already guarded by the upstream libavcodec version."""
    lines = []
    conditions = []
    active = True
    for line in code.splitlines(keepends=True):
        directive = re.match(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", line)
        if directive:
            kind, expression = directive.groups()
            if kind in ("if", "ifdef", "ifndef", "elif"):
                test = re.fullmatch(r"LIBAVCODEC_VERSION_MAJOR\s*(<=|>=|==|!=|<|>)\s*(\d+)", expression.strip())
                enabled = None
                if test:
                    limit = int(test[2])
                    enabled = {"<": major < limit, "<=": major <= limit, ">": major > limit,
                               ">=": major >= limit, "==": major == limit, "!=": major != limit}[test[1]]
                parent, possible = conditions.pop() if kind == "elif" else (active, active)
                conditions.append((parent, possible and enabled is not True))
                active = possible and enabled is not False
            elif kind == "else":
                active = conditions[-1][1]
            else:
                active, _ = conditions.pop()
        lines.append(line if active and not directive else re.sub(r"[^\r\n]", " ", line))
    return "".join(lines)


def adapt_file(text, avcodec_major=63):
    masked = NON_CODE.sub(lambda m: re.sub(r"[^\r\n]", " ", m[0]), text)
    code = active_code(masked, avcodec_major)
    codecs = set(re.findall(r"\bAVCodec\s*(?:const\s*)?\*\s*(\w+)\b", code))
    edits = []
    for match in MEMBER.finditer(code):
        if code[:match.start()].rstrip().endswith(("->", ".")):
            continue
        if match["context"]:
            replacement = f"lw_get_split_callback({text[match.start('context'):match.end('context')]})"
        elif match["codec"] in codecs:
            replacement = f"lw_supported_pix_fmts({match['codec']})"
        else:
            continue
        edits.append((match.start(), match.end(), replacement))
    if not edits:
        return text
    for start, stop, replacement in reversed(edits):
        text = text[:start] + replacement + text[stop:]
    if f'#include "{HEADER}"' not in text:
        # Insert at file scope, after feature-test definitions and before the existing includes.
        depth = 0
        for directive in re.finditer(r"(?m)^[ \t]*#[ \t]*(if|ifdef|ifndef|endif|include)\b", masked):
            if depth == 0:
                start = directive.start()
            kind = directive[1]
            if kind == "include":
                break
            depth += -1 if kind == "endif" else 1
        else:
            raise ValueError("Cannot locate L-SMASH-Works includes")
        text = text[:start] + f'#include "{HEADER}"\n' + text[start:]
    return text


def adapt_sources(source: Path, avcodec_major: int) -> None:
    if avcodec_major < 63:
        return
    for directory in (source / "common", source / "VapourSynth"):
        for path in sorted(directory.rglob("*")):
            if path.suffix not in (".c", ".cpp"):
                continue
            original = path.read_bytes()
            text = original.decode("utf-8", errors="surrogateescape")
            updated = adapt_file(text, avcodec_major)
            if updated != text:
                header = path.with_name(HEADER)
                header.write_text(COMPATIBILITY_API, encoding="utf-8")
                if b"\r\n" in original:
                    updated = updated.replace("\r\n", "\n").replace("\n", "\r\n")
                path.write_bytes(updated.encode("utf-8", errors="surrogateescape"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("avcodec_major", type=int)
    args = parser.parse_args()
    adapt_sources(args.source, args.avcodec_major)
