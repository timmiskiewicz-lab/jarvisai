"""Small parser for Valve's KeyValues text format."""

from __future__ import annotations


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "{}":
            tokens.append(char)
            index += 1
            continue
        if char == '"':
            index += 1
            buffer: list[str] = []
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    buffer.append(text[index + 1])
                    index += 2
                    continue
                if text[index] == '"':
                    index += 1
                    break
                buffer.append(text[index])
                index += 1
            tokens.append("".join(buffer))
            continue
        index += 1
    return tokens


def parse_vdf(text: str) -> dict:
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    tokens = _tokenize(text)
    position = 0

    def peek() -> str | None:
        if position >= len(tokens):
            return None
        return tokens[position]

    def take() -> str:
        nonlocal position
        token = tokens[position]
        position += 1
        return token

    def parse_value():
        token = take()
        if token != "{":
            return token
        node: dict = {}
        while peek() not in (None, "}"):
            key = take()
            if key in "{}":
                continue
            node[key] = parse_value()
        if peek() == "}":
            take()
        return node

    root: dict = {}
    while peek() is not None:
        key = take()
        if key in "{}":
            continue
        root[key] = parse_value()
    return root
