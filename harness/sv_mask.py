"""Shared SystemVerilog comment/string masking, used wherever code needs to be
scanned structurally (mutation site enumeration, submission module extraction)
without a `module` keyword inside a comment or string literal being mistaken
for a real declaration."""

from __future__ import annotations


def mask_code(source: str) -> str:
    """Blank comments and string literals while preserving source offsets."""
    chars = list(source)
    index = 0
    mode = "code"
    while index < len(chars):
        if mode == "code" and chars[index : index + 2] == ["/", "/"]:
            mode = "line"
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        if mode == "code" and chars[index : index + 2] == ["/", "*"]:
            mode = "block"
            chars[index] = chars[index + 1] = " "
            index += 2
            continue
        if mode == "code" and chars[index] == '"':
            mode = "string"
            chars[index] = " "
            index += 1
            continue
        if mode == "code":
            index += 1
            continue
        if mode == "line":
            if chars[index] == "\n":
                mode = "code"
            else:
                chars[index] = " "
            index += 1
            continue
        if mode == "block":
            if chars[index : index + 2] == ["*", "/"]:
                chars[index] = chars[index + 1] = " "
                index += 2
                mode = "code"
            else:
                if chars[index] != "\n":
                    chars[index] = " "
                index += 1
            continue
        if mode == "string":
            if chars[index] == "\\":
                chars[index] = " "
                if index + 1 < len(chars):
                    chars[index + 1] = " "
                index += 2
            elif chars[index] == '"':
                chars[index] = " "
                index += 1
                mode = "code"
            else:
                chars[index] = " "
                index += 1
    return "".join(chars)
