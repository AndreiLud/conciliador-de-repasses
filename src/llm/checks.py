"""Checks applied to every text written by the model before it is shown.

* every number in the text must exist in the facts given to the model;
* no forbidden expressions (robotic phrasing, dashes used as pauses, emojis);
* no questions (letters and summaries state facts, they do not ask).
"""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation

NUMBER_TOKEN = re.compile(r"\d[\d.]*(?:,\d+)?")

FORBIDDEN_TERMS = [
    "vale ressaltar", "vale destacar", "é importante destacar", "é importante ressaltar", "em suma",
    "mergulh", "desvend", "jornada", "crucial", "robust", "não é apenas", "não apenas",
    "no cenário", "fique tranquilo", "não hesite", "estamos à disposição para", "prezado cliente",
    "gostaríamos de informar", "venho por meio", "vimos por meio",
]
DASHES = ["\u2014", "\u2013", " - ", "->"]
LIST_MARKER = re.compile(r"(^|\n)\s*[-*\u2022]\s")
NUMBER_WORDS = ["dois", "duas", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
                "treze", "catorze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove", "vinte",
                "trinta", "quarenta", "cinquenta", "cem", "cento", "mil", "metade", "dobro", "triplo"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")


def _to_decimal(token: str) -> Decimal | None:
    t = token.rstrip(".")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") >= 1 and all(len(p) == 3 for p in t.split(".")[1:]):
        t = t.replace(".", "")  # thousands separator: 1.234
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    out = set()
    for tok in NUMBER_TOKEN.findall(text):
        d = _to_decimal(tok)
        if d is not None:
            out.add(d.normalize())
    return out


def numbers_in_facts(facts) -> set[Decimal]:
    return numbers_in(json.dumps(facts, ensure_ascii=False))


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-zà-ú]+", text.lower()))


def check_numbers(text: str, facts) -> list[str]:
    allowed = numbers_in_facts(facts)
    extra = sorted(str(n) for n in numbers_in(text) - allowed)
    problems = [f"número que não está nos dados: {', '.join(extra)}"] if extra else []
    fact_words = _words(json.dumps(facts, ensure_ascii=False))
    spelled = sorted(w for w in _words(text) & set(NUMBER_WORDS) if w not in fact_words)
    if spelled:
        problems.append(f"quantidade por extenso que não está nos dados: {', '.join(spelled)}; use algarismos")
    return problems


def _plain(text: str) -> str:
    return unicodedata.normalize("NFC", text.lower())


def check_style(text: str) -> list[str]:
    problems = []
    low = _plain(text)
    for term in FORBIDDEN_TERMS:
        if term in low:
            problems.append(f"expressão proibida: {term}")
    for dash in DASHES:
        if dash in text:
            problems.append("travessão ou hífen usado como pausa")
            break
    if LIST_MARKER.search(text):
        problems.append("marcador de lista no texto")
    if EMOJI.search(text):
        problems.append("emoji")
    if "?" in text:
        problems.append("pergunta no texto")
    if low.count("cenário") > 1:
        problems.append("palavra 'cenário' repetida")
    return problems


def check_text(text: str, facts) -> list[str]:
    return check_numbers(text, facts) + check_style(text)
