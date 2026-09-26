"""Text utilities: find the bibliography, split it into entries, find DOIs, normalise words."""

from __future__ import annotations

import re
import unicodedata

# A DOI is "10." + registrant code + "/" + suffix. Trailing punctuation is stripped afterwards.
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)[a-z]?\b")
_HEADING = re.compile(
    r"^\s*#*\s*(references|bibliography|works cited|sources|références|bibliographie|"
    r"referencias|bibliografía|bibliografia|riferimenti bibliografici)\s*:?\s*$",
    re.IGNORECASE,
)
_ENTRY_MARKER = re.compile(r"^\s*(\[\d+\]|\d+[.)]|[-*•])\s+")

# Function words of the languages that multilingual policy bibliographies often mix.
_STOPWORDS_BY_LANGUAGE = {
    "en": "a an and are as at by for from in into is of on or the to with",
    "fr": "de des du et la le les l d en un une pour dans sur au aux",
    "es": "el los las y del para por con",
    "it": "il lo gli i e di da per con su nel della delle",
    "de": "der die das und von zu mit im",
}
STOPWORDS = frozenset(w for words in _STOPWORDS_BY_LANGUAGE.values() for w in words.split())


def find_dois(text: str) -> list[str]:
    return [m.rstrip(".,;:)]}'").lower() for m in _DOI.findall(text)]


_QUOTED = re.compile(r"[\"“”«»]\s*([^\"“”«»]{10,300}?)\s*[\"“”«»]")


def find_quoted_title(text: str) -> str | None:
    """Many styles put the title in quotes: 'Gebru, T. (2021), "Datasheets for datasets", ...'."""
    match = _QUOTED.search(text)
    return match.group(1).strip(" ,.") if match else None


def find_year(text: str) -> int | None:
    match = _YEAR.search(text)
    return int(match.group(1)) if match else None


def normalise(text: str) -> str:
    """Lower case, no accents, no punctuation, single spaces."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def content_words(text: str) -> set[str]:
    return {w for w in normalise(text).split() if w not in STOPWORDS and len(w) > 1}


def bibliography_section(text: str) -> str:
    """The text after a references heading, up to the next Markdown heading; else all text."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            body = []
            for following in lines[i + 1 :]:
                if following.lstrip().startswith("#"):
                    break
                body.append(following)
            return "\n".join(body)
    return text


def split_entries(section: str) -> list[str]:
    """Split a bibliography into one string per reference.

    Handles numbered or bulleted lists, entries separated by blank lines, and one entry per
    line. Lines that wrap inside an entry are joined back together.
    """
    lines = [line.rstrip() for line in section.splitlines()]
    entries: list[list[str]] = []

    if any(_ENTRY_MARKER.match(line) for line in lines):
        for line in lines:
            if _ENTRY_MARKER.match(line):
                entries.append([_ENTRY_MARKER.sub("", line, count=1)])
            elif line.strip() and entries:
                entries[-1].append(line.strip())
    elif any(not line.strip() for line in lines[1:-1]):
        current: list[str] = []
        for line in lines:
            if line.strip():
                current.append(line.strip())
            elif current:
                entries.append(current)
                current = []
        if current:
            entries.append(current)
    else:
        entries = [[line.strip()] for line in lines if line.strip()]

    joined = [" ".join(parts).strip() for parts in entries]
    return [entry for entry in joined if len(entry) >= 15]
