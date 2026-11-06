"""Name normalization used to compare bank descriptions with the registry.

Banks print payee names in upper case, without accents and with their own
abbreviations. This dictionary was built from the descriptions seen in the
bank statement; it is part of the matching rules and is documented in
project_docs/methodology.md.
"""
from __future__ import annotations

import unicodedata

BANK_STYLE_ABBREVIATIONS = [
    ("NOSSA SENHORA", "N SRA"), ("SENHORA", "SRA"), ("RESTAURANTE", "REST"), ("PIZZARIA", "PIZZ"),
    ("LANCHONETE", "LANCH"), ("COMERCIO DE ALIMENTOS", "COM ALIM"), ("ALIMENTOS", "ALIM"),
    ("HAMBURGUERIA", "HAMB"), ("CHURRASCARIA", "CHURR"), ("CONFEITARIA", "CONF"), ("PANIFICADORA", "PANIF"),
    ("MARMITARIA", "MARMIT"), ("TEMAKERIA", "TEMAK"), ("GASTRONOMIA", "GASTR"), ("REFEICOES", "REFEIC"),
    ("SANTO", "STO"), ("SANTA", "STA"), ("SAO", "S"), (" DA ", " "), (" DO ", " "), (" DE ", " "),
]
COMPANY_SUFFIXES = [" LTDA EPP", " LTDA ME", " LTDA", " EIRELI", " SLU", " ME "]


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def bank_style(name: str) -> str:
    t = " " + strip_accents(str(name)).upper().replace(".", "").replace(",", "") + " "
    for long, short in BANK_STYLE_ABBREVIATIONS:
        t = t.replace(long, short)
    for suffix in COMPANY_SUFFIXES:
        t = t.replace(suffix, " ")
    return " ".join(t.split())
