"""The three jobs given to the language model, with validation and retries.

1. classify an ambiguous divergence (type, confidence, evidence ids, short
   explanation);
2. write the explanatory paragraphs of a letter to a restaurant;
3. write the weekly executive summary.

Every answer is JSON validated with pydantic. Every text goes through
``checks.check_text``. One retry with the list of problems; after that the
caller falls back to the deterministic path.
"""
from __future__ import annotations

import json
from functools import lru_cache

from pydantic import BaseModel, Field, ValidationError

from .. import config
from ..money import format_brl
from .checks import check_text
from .client import CacheMiss, LLMClient, ProviderError

FAMILY_DESC = {
    "linha_pedido": "linha de pedido com valor líquido diferente do recalculado (extrato legado, só o líquido)",
    "estorno_ausente_dono_indefinido": "estorno sem responsável preenchido que não foi descontado do restaurante",
    "banco_nao_identificado": "pagamento no banco que não foi ligado a um repasse",
}


class ClassificacaoIA(BaseModel):
    tipo: str
    confianca: float = Field(ge=0, le=1)
    evidencias: list[str] = Field(min_length=1, max_length=8)
    explicacao: str = Field(min_length=10, max_length=400)


class DonoEstornoIA(BaseModel):
    responsavel: str
    confianca: float = Field(ge=0, le=1)
    trecho: str = Field(max_length=200)


class CartaIA(BaseModel):
    paragrafos: list[str] = Field(min_length=1, max_length=2)


class ResumoIA(BaseModel):
    titulo: str = Field(min_length=5, max_length=70)
    paragrafos: list[str] = Field(min_length=1, max_length=2)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def _schema_classify(options: list[str], evidence_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "tipo": {"type": "string", "enum": options},
            "confianca": {"type": "number", "minimum": 0, "maximum": 1},
            "evidencias": {"type": "array", "items": {"type": "string", "enum": evidence_ids},
                           "minItems": 1, "maxItems": 6},
            "explicacao": {"type": "string", "minLength": 10, "maxLength": 240},
        },
        "required": ["tipo", "confianca", "evidencias", "explicacao"],
        "additionalProperties": False,
    }


SCHEMA_DONO = {
    "type": "object",
    "properties": {"trecho": {"type": "string", "maxLength": 200},
                   "responsavel": {"type": "string", "enum": ["restaurante", "plataforma", "indefinido"]},
                   "confianca": {"type": "number", "minimum": 0, "maximum": 1}},
    "required": ["trecho", "responsavel", "confianca"], "additionalProperties": False,
}

SCHEMA_CARTA = {
    "type": "object",
    "properties": {"paragrafos": {"type": "array", "items": {"type": "string", "minLength": 20, "maxLength": 700},
                                  "minItems": 1, "maxItems": 2}},
    "required": ["paragrafos"], "additionalProperties": False,
}
SCHEMA_RESUMO = {
    "type": "object",
    "properties": {"titulo": {"type": "string", "minLength": 5, "maxLength": 70},
                   "paragrafos": {"type": "array", "items": {"type": "string", "minLength": 20, "maxLength": 500},
                                  "minItems": 1, "maxItems": 2}},
    "required": ["titulo", "paragrafos"], "additionalProperties": False,
}


def _parse(model_cls, content: str):
    try:
        return model_cls.model_validate_json(content), []
    except ValidationError as exc:
        return None, [f"JSON inválido: {exc.errors()[0].get('msg', 'erro')}"]


def case_payload(d) -> dict:
    payload = {
        "situacao": FAMILY_DESC.get(d.familia, d.familia),
        "restaurante_id": d.restaurante_id, "semana": d.semana,
        "diferenca_no_repasse": format_brl(d.valor_centavos, signed=True),
        "opcoes": d.opcoes,
        "evidencias": d.evidencias,
    }
    if d.hipoteses:
        payload["hipoteses_calculadas"] = [
            {k: h[k] for k in ("tipo", "descricao", "liquido_hipotese_brl", "confere") if k in h} for h in d.hipoteses]
    return payload


def classify_case(client: LLMClient, d) -> dict:
    system = load_prompt("classificacao_sistema.md")
    payload = case_payload(d)
    evidence_ids = [e["id"] for e in d.evidencias]
    schema = _schema_classify(d.opcoes, evidence_ids)
    base_user = "Classifique o caso abaixo.\n\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    user, problems, out = base_user, [], None
    for attempt in (1, 2):
        try:
            resp = client.complete_json("classificacao", system, user, schema)
        except CacheMiss:
            return {"ok": False, "motivo": "sem resposta em cache (modo offline)", "tentativas": attempt - 1}
        except ProviderError as exc:
            return {"ok": False, "motivo": f"servidor local indisponível: {exc}", "tentativas": attempt - 1}
        out, problems = _parse(ClassificacaoIA, resp.content)
        if out is not None:
            if out.tipo not in d.opcoes:
                problems.append(f"tipo fora das opções: {out.tipo}")
            bad_ids = [e for e in out.evidencias if e not in evidence_ids]
            if bad_ids:
                problems.append(f"evidência inexistente: {', '.join(bad_ids)}")
            problems += check_text(out.explicacao, payload)
            fitting = {h["tipo"] for h in d.hipoteses if h.get("confere")}
            if fitting and out.tipo not in fitting and out.tipo != "outro":
                problems.append("tipo escolhido não reproduz o valor do extrato; escolha uma hipótese que confere")
        if not problems:
            return {"ok": True, "tipo": out.tipo, "confianca": round(out.confianca, 2), "evidencias": out.evidencias,
                    "explicacao": out.explicacao, "tentativas": attempt}
        user = base_user + "\n\nSua resposta anterior teve estes problemas: " + "; ".join(problems) + \
            ". Responda de novo corrigindo."
    return {"ok": False, "motivo": "; ".join(problems), "tentativas": 2,
            "tipo": out.tipo if out else None, "confianca": round(out.confianca, 2) if out else None}


def _norm_text(t: str) -> str:
    return " ".join(t.lower().replace('"', "").split())


def classify_refund_owner(client: LLMClient, note: str) -> dict:
    """Who caused the refund, read from the support note. The quoted span must exist in the note."""
    system = load_prompt("dono_estorno_sistema.md")
    base_user = f"Nota do atendimento: \"{note}\""
    user, problems, out = base_user, [], None
    for attempt in (1, 2):
        try:
            resp = client.complete_json("dono_estorno", system, user, SCHEMA_DONO)
        except CacheMiss:
            return {"ok": False, "motivo": "sem resposta em cache (modo offline)", "tentativas": attempt - 1}
        except ProviderError as exc:
            return {"ok": False, "motivo": f"servidor local indisponível: {exc}", "tentativas": attempt - 1}
        out, problems = _parse(DonoEstornoIA, resp.content)
        if out is not None:
            if out.responsavel not in ("restaurante", "plataforma", "indefinido"):
                problems.append(f"responsável fora das opções: {out.responsavel}")
            quote = _norm_text(out.trecho)
            if out.responsavel != "indefinido" and not quote:
                problems.append("faltou o trecho da nota")
            if quote and (quote not in _norm_text(note) or (len(quote.split()) < 2 and len(quote) < 8)):
                problems.append("o trecho citado não está na nota ou é curto demais para justificar a resposta")
        if not problems:
            return {"ok": True, "responsavel": out.responsavel, "confianca": round(out.confianca, 2),
                    "trecho": out.trecho.strip(), "tentativas": attempt}
        user = base_user + "\n\nSua resposta anterior teve estes problemas: " + "; ".join(problems) + \
            ". Copie o trecho exatamente como está na nota."
    return {"ok": False, "motivo": "; ".join(problems), "tentativas": 2}


def write_paragraphs(client: LLMClient, task: str, prompt_file: str, facts: dict, schema: dict, model_cls,
                     instruction: str) -> dict:
    system = load_prompt(prompt_file)
    base_user = instruction + "\n\n" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    user, problems = base_user, []
    for attempt in (1, 2):
        try:
            resp = client.complete_json(task, system, user, schema)
        except CacheMiss:
            return {"ok": False, "motivo": "sem resposta em cache (modo offline)", "tentativas": attempt - 1}
        except ProviderError as exc:
            return {"ok": False, "motivo": f"servidor local indisponível: {exc}", "tentativas": attempt - 1}
        out, problems = _parse(model_cls, resp.content)
        if out is not None:
            text = " ".join(out.paragrafos) + (" " + out.titulo if hasattr(out, "titulo") else "")
            problems += check_text(text, facts)
            if task == "carta" and len(text.split()) > 110:
                problems.append("texto longo demais")
            if task == "resumo" and any(ch.isdigit() for ch in text):
                problems.append("a leitura da semana não deve ter números; eles já estão na tabela")
            if task == "resumo" and len(text.split()) > 80:
                problems.append("texto longo demais")
            if task == "carta" and ("R$" in text or "%" in text):
                problems.append("a carta não deve citar valores nem porcentagens; a tabela já mostra os números")
            if any(not p.rstrip().endswith((".", "!")) for p in out.paragrafos):
                problems.append("parágrafo terminou no meio da frase")
        if not problems:
            result = {"ok": True, "paragrafos": out.paragrafos, "tentativas": attempt}
            if hasattr(out, "titulo"):
                result["titulo"] = out.titulo
            return result
        user = base_user + "\n\nSua resposta anterior teve estes problemas: " + "; ".join(problems) + \
            ". Escreva de novo corrigindo."
    return {"ok": False, "motivo": "; ".join(problems), "tentativas": 2}


def write_letter(client: LLMClient, facts: dict) -> dict:
    return write_paragraphs(client, "carta", "carta_sistema.md", facts, SCHEMA_CARTA, CartaIA,
                            "Escreva os parágrafos explicativos da carta a partir destes fatos.")


def write_summary(client: LLMClient, facts: dict) -> dict:
    return write_paragraphs(client, "resumo", "resumo_sistema.md", facts, SCHEMA_RESUMO, ResumoIA,
                            "Escreva a leitura desta semana a partir destes fatos.")
