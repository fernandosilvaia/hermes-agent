"""
editor_chefe.py — Estado persistente da FILA_CONTEUDO_DIARIO (protocolo
"Editor-Chefe" da Axtro AI). Guarda o pacote de conteudo pendente de
aprovacao, o historico de decisoes, e o progresso no banco de historias
fixo dos primeiros 7 dias (v1: sem mineracao de log, sem HeyGen, sem
Blotato — carrossel + texto, roteiro em markdown, Fernando publica manual).

Esta e uma skill de ESTADO (le/escreve um JSON), nao de geracao de
conteudo — quem escreve a historia/roteiro e o proprio agente (LLM) na
hora do cron, usando esta lib so pra persistir o pacote e registrar a
decisao depois. Ver SKILL.md pro fluxo completo.

Uso como biblioteca:
    from editor_chefe import (
        get_sprint_day, get_banco_entry, has_pending, save_pending_package,
        load_pending_package, record_decision, expire_if_unactioned,
    )

Uso como CLI:
    python editor_chefe.py sprint-day
    python editor_chefe.py banco-entry --day 3
    python editor_chefe.py has-pending
    python editor_chefe.py save-pending --file pacote.json
    python editor_chefe.py get-pending
    python editor_chefe.py decide --decision aprovado
    python editor_chefe.py decide --decision editar --instrucao "troca o gancho do slide 1"
    python editor_chefe.py decide --decision pular
    python editor_chefe.py expire-check
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_DIR = Path(os.environ.get("EDITOR_CHEFE_STATE_DIR", os.path.expanduser("~/.hermes/conteudo")))
STATE_FILE = STATE_DIR / "estado.json"
TZ = ZoneInfo("America/New_York")

BANCO_DE_HISTORIAS = {
    1: {
        "historia": "Agente ligou pra ADP, 40 min de espera, cancelou serviço e recuperou reembolso. Custo: centavos.",
        "formato": "CARROSSEL",
        "recibo_necessario": "log da ligação + valor",
    },
    2: {
        "historia": "Raissa atende lead em 4 minutos após cadastro e agenda reunião.",
        "formato": "RAISSA_VIDEO",
        "recibo_necessario": "log de tempo real",
    },
    3: {
        "historia": "Software de visagismo construído em uma tarde pelos agentes.",
        "formato": "SCREEN_DEMO",
        "recibo_necessario": "gravação de tela",
    },
    4: {
        "historia": "Raissa poliglota: a mesma agente atendendo em chinês e grego.",
        "formato": "RAISSA_VIDEO",
        "recibo_necessario": "trecho da demo da live",
    },
    5: {
        "historia": "A fábrica às 3h da manhã: dashboard dos agentes trabalhando enquanto todos dormem.",
        "formato": "SCREEN_DEMO",
        "recibo_necessario": "print com timestamp",
    },
    6: {
        "historia": "Software de colorimetria: da ideia ao funcionando.",
        "formato": "CARROSSEL",
        "recibo_necessario": "prints antes/depois",
    },
    7: {
        "historia": "Sistema de gestão de Airbnb entregue por agentes.",
        "formato": "CARROSSEL",
        "recibo_necessario": "prints (anonimizar dados)",
    },
}

# v1 so cobre formatos que nao dependem de HeyGen/Blotato (RAISSA_VIDEO fica
# pra fase 2). Dias 2 e 4 do banco original usam RAISSA_VIDEO — v1 troca por
# CARROSSEL equivalente ate a fase 2 estar pronta.
V1_FORMATO_FALLBACK = {"RAISSA_VIDEO": "CARROSSEL", "SCREEN_DEMO": "CARROSSEL"}


def _now() -> datetime:
    return datetime.now(TZ)


def _today_str() -> str:
    return _now().date().isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {
            "sprint_start_date": _today_str(),
            "banco_de_historias_usado": [],
            "historico": [],
            "pendente": None,
        }
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    _atomic_write(STATE_FILE, state)


def get_sprint_day() -> int:
    """Dia do sprint (1-indexado). A partir do dia 8, a FILA passa a minerar
    log em vez de usar o banco fixo (fora do escopo do v1 desta lib)."""
    state = load_state()
    start = datetime.fromisoformat(state["sprint_start_date"]).date()
    delta = (_now().date() - start).days
    return delta + 1


def get_banco_entry(day: int, v1_only: bool = True) -> dict:
    entry = BANCO_DE_HISTORIAS.get(day)
    if not entry:
        raise ValueError(f"Dia {day} fora do banco de histórias (1-7).")
    out = dict(entry)
    if v1_only and out["formato"] in V1_FORMATO_FALLBACK:
        out["formato_original"] = out["formato"]
        out["formato"] = V1_FORMATO_FALLBACK[out["formato"]]
        out["nota"] = f"formato original {out['formato_original']} precisa de HeyGen (fase 2); v1 usa {out['formato']}."
    return out


def has_pending() -> bool:
    return load_state().get("pendente") is not None


def load_pending_package() -> dict:
    pendente = load_state().get("pendente")
    if not pendente:
        raise RuntimeError("Não há pacote pendente de aprovação.")
    return pendente


def save_pending_package(dia_sprint: int, historia: str, formato_principal: str,
                          formato_derivado: str, pacote: dict, score: int = None) -> dict:
    """Salva o pacote de conteudo do dia como pendente de aprovacao. So
    chame DEPOIS de montar o roteiro completo (Fase 4) — este passo nao
    publica nada, so guarda estado pra Fase 5 (aprovacao) achar depois."""
    state = load_state()
    if state.get("pendente") is not None:
        raise RuntimeError(
            "Já existe um pacote pendente (dia "
            f"{state['pendente'].get('dia_sprint')}). Resolva-o (decide/expire-check) antes de criar outro."
        )
    pendente = {
        "data": _today_str(),
        "dia_sprint": dia_sprint,
        "historia": historia,
        "score": score,
        "formato_principal": formato_principal,
        "formato_derivado": formato_derivado,
        "pacote": pacote,
        "enviado_em": _now().isoformat(),
        "status": "aguardando",
    }
    state["pendente"] = pendente
    if dia_sprint not in state["banco_de_historias_usado"]:
        state["banco_de_historias_usado"].append(dia_sprint)
    save_state(state)
    return pendente


def record_decision(decision: str, instrucao: str = None) -> dict:
    """decision: 'aprovado' | 'editar' | 'pular'.
    'editar' MANTEM o pendente (so registra a instrucao, quem aplica o ajuste
    e o agente na hora, reenviando um pacote atualizado). 'aprovado' e 'pular'
    movem o pendente pro historico e liberam o slot."""
    if decision not in ("aprovado", "editar", "pular"):
        raise ValueError("decision deve ser 'aprovado', 'editar' ou 'pular'.")
    state = load_state()
    pendente = state.get("pendente")
    if not pendente:
        raise RuntimeError("Não há pacote pendente pra decidir.")

    if decision == "editar":
        pendente["status"] = "editando"
        pendente["instrucao_edicao"] = instrucao
        state["pendente"] = pendente
        save_state(state)
        return pendente

    pendente["status"] = "aprovado" if decision == "aprovado" else "pulado"
    pendente["decidido_em"] = _now().isoformat()
    state["historico"].append(pendente)
    state["pendente"] = None
    save_state(state)
    return pendente


def expire_if_unactioned() -> dict:
    """Chamado pelo cron das 21h: se o pendente de HOJE ainda nao foi
    decidido, marca como nao publicado (silencio nunca e aprovacao) e libera
    o slot pra amanha. Retorna {'expirou': bool, ...}."""
    state = load_state()
    pendente = state.get("pendente")
    if not pendente:
        return {"expirou": False, "motivo": "nao ha pendente"}
    if pendente["data"] != _today_str():
        return {"expirou": False, "motivo": "pendente nao e de hoje"}
    if pendente["status"] not in ("aguardando",):
        return {"expirou": False, "motivo": f"status já é {pendente['status']}"}

    pendente["status"] = "nao_publicado_sem_resposta"
    pendente["decidido_em"] = _now().isoformat()
    state["historico"].append(pendente)
    state["pendente"] = None
    save_state(state)
    return {"expirou": True, "dia_sprint": pendente["dia_sprint"], "historia": pendente["historia"]}


def _cli():
    p = argparse.ArgumentParser(description="Estado da FILA_CONTEUDO_DIARIO (Editor-Chefe)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("sprint-day", help="Dia atual do sprint (1-indexado)")

    s = sub.add_parser("banco-entry", help="Consultar entrada do banco de histórias")
    s.add_argument("--day", type=int, required=True)

    sub.add_parser("has-pending", help="Há pacote pendente de aprovação?")

    s = sub.add_parser("save-pending", help="Salvar pacote pendente (JSON via --file ou --json)")
    s.add_argument("--dia-sprint", type=int, required=True)
    s.add_argument("--historia", required=True)
    s.add_argument("--formato-principal", required=True)
    s.add_argument("--formato-derivado", required=True)
    s.add_argument("--file", help="Path pra um JSON com o campo 'pacote'")
    s.add_argument("--json", dest="json_str", help="JSON inline com o campo 'pacote'")
    s.add_argument("--score", type=int, default=None)

    sub.add_parser("get-pending", help="Ler o pacote pendente")

    s = sub.add_parser("decide", help="Registrar decisão sobre o pendente")
    s.add_argument("--decision", required=True, choices=["aprovado", "editar", "pular"])
    s.add_argument("--instrucao", default=None)

    sub.add_parser("expire-check", help="Checar e expirar pendente sem resposta (cron 21h)")

    args = p.parse_args()

    try:
        if args.command == "sprint-day":
            out = {"dia_sprint": get_sprint_day()}
        elif args.command == "banco-entry":
            out = get_banco_entry(args.day)
        elif args.command == "has-pending":
            out = {"has_pending": has_pending()}
        elif args.command == "save-pending":
            if args.file:
                pacote = json.loads(Path(args.file).read_text(encoding="utf-8"))
            elif args.json_str:
                pacote = json.loads(args.json_str)
            else:
                raise ValueError("Informe --file ou --json com o conteúdo do pacote.")
            out = save_pending_package(
                args.dia_sprint, args.historia, args.formato_principal,
                args.formato_derivado, pacote, args.score,
            )
        elif args.command == "get-pending":
            out = load_pending_package()
        elif args.command == "decide":
            out = record_decision(args.decision, args.instrucao)
        elif args.command == "expire-check":
            out = expire_if_unactioned()
        else:
            p.error("comando desconhecido")
            return
    except (RuntimeError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
