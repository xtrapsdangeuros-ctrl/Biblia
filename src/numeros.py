"""Interpreta números falados depois de "Capítulo": 12, XII, doze, vinte e um, décimo primeiro."""

import re

from comum import normalizar

_UNIDADES = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
}
_DEZ_A_DEZENOVE = {
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
    "quinze": 15, "dezesseis": 16, "dezasseis": 16, "dezessete": 17, "dezassete": 17,
    "dezoito": 18, "dezenove": 19, "dezanove": 19,
}
_DEZENAS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60,
    "setenta": 70, "oitenta": 80, "noventa": 90,
}
_CENTENAS = {
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200, "trezentos": 300,
    "trezentas": 300, "quatrocentos": 400, "quinhentos": 500, "seiscentos": 600,
    "setecentos": 700, "oitocentos": 800, "novecentos": 900,
}
_CARDINAIS = {**_UNIDADES, **_DEZ_A_DEZENOVE, **_DEZENAS, **_CENTENAS}

_ORDINAIS = {
    "primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "quinto": 5, "sexto": 6,
    "setimo": 7, "oitavo": 8, "nono": 9, "decimo": 10, "vigesimo": 20, "trigesimo": 30,
    "quadragesimo": 40, "quinquagesimo": 50, "sexagesimo": 60, "septuagesimo": 70,
    "setuagesimo": 70, "octogesimo": 80, "nonagesimo": 90, "centesimo": 100,
}

_ROMANOS = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
_PADRAO_ROMANO = re.compile(r"^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")


def limpar_token(texto: str) -> str:
    """Normaliza e tira pontuação das pontas: ' Capítulo,' -> 'capitulo'."""
    return normalizar(texto).strip(" \t.,;:!?\"'()[]«»“”-–—…")


def _romano(token: str) -> int | None:
    if not token or not _PADRAO_ROMANO.match(token):
        return None
    total = 0
    for atual, prox in zip(token, token[1:] + " "):
        valor = _ROMANOS[atual]
        total += -valor if prox != " " and _ROMANOS[prox] > valor else valor
    return total


def _ordinal(token: str) -> int | None:
    # "primeira", "décima" -> forma masculina
    if token in _ORDINAIS:
        return _ORDINAIS[token]
    if token.endswith("a") and token[:-1] + "o" in _ORDINAIS:
        return _ORDINAIS[token[:-1] + "o"]
    return None


def ler_numero(tokens: list[str]) -> tuple[int, int] | None:
    """Lê um número no começo da lista de tokens já limpos.

    Retorna (valor, quantos tokens foram usados) ou None se não houver número.
    """
    if not tokens or not tokens[0]:
        return None
    primeiro = tokens[0]

    if primeiro.isdigit():
        return int(primeiro), 1

    if primeiro in _CARDINAIS:
        total, usados = 0, 0
        while usados < len(tokens):
            tok = tokens[usados]
            if tok in _CARDINAIS:
                total += _CARDINAIS[tok]
                usados += 1
            elif tok == "e" and usados + 1 < len(tokens) and tokens[usados + 1] in _CARDINAIS:
                usados += 1
            else:
                break
        return total, usados

    if _ordinal(primeiro) is not None:
        total, usados = 0, 0
        while usados < len(tokens) and (valor := _ordinal(tokens[usados])) is not None:
            total += valor
            usados += 1
        return total, usados

    valor = _romano(primeiro)
    if valor:
        return valor, 1
    return None
