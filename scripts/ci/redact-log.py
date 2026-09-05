#!/usr/bin/env python3
"""Streaming CI diagnostics: never persist an unredacted intermediate log."""
import os
import re
import sys


def redact(line: str, secrets: tuple[str, ...] = ()) -> str:
    for value in sorted(secrets, key=len, reverse=True):
        if len(value) >= 8:
            line = line.replace(value, "[REDACTED]")
    line = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+", r"\1[REDACTED]", line)
    line = re.sub(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,})", "[REDACTED]", line)
    line = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", line)
    return re.sub(r'''(?i)((?:[\w-]*(?:token|password|secret|api[_-]?key)[\w-]*)["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''', r"\1[REDACTED]", line)


def main() -> None:
    secrets = tuple(v for k, v in os.environ.items()
                    if re.search(r"TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL", k, re.I))
    in_key = False
    for line in sys.stdin:
        if re.search(r"-----BEGIN .*PRIVATE KEY-----", line):
            in_key = True
        if in_key:
            if re.search(r"-----END .*PRIVATE KEY-----", line):
                in_key = False
            print("[REDACTED PRIVATE KEY]", flush=True)
        else:
            print(redact(line, secrets), end="", flush=True)


if __name__ == "__main__":
    main()
