"""
_call_approval_store.py - store PURO (stdlib only) dos pedidos de ligacao
pendentes de aprovacao one-tap no Telegram.

Cada pedido de ligacao a um terceiro vira um registro persistente aqui ANTES
de qualquer discagem. O dono (Fernando) recebe uma mensagem no Telegram com
botoes Aprovar/Rejeitar; o tap do botao (tratado pelo gateway) grava a
decisao NESTE store via decide_call_request.py; o processo que pediu executa
a ligacao SOMENTE se o pedido estiver aprovado (ver _call_approval_flow.py).

Convencoes (mesmo padrao do crm-connector/connections.json, PR #17):
  - Caminho: $HERMES_HOME/telnyx_voice_sms/call_approvals.json
    (override: TELNYX_CALL_APPROVAL_STORE_PATH)
  - Audit log durvel (append-only JSONL): toda criacao/decisao/execucao vira
    uma linha em $HERMES_HOME/telnyx_voice_sms/call_approval_audit.jsonl
    (override: TELNYX_CALL_APPROVAL_AUDIT_PATH)
  - Arquivos gravados com 0600 (dados de contato/telefone do dono).
  - So stdlib. Sem rede. Toda transicao de estado e ATOMICA sob um lock de
    arquivo (dois processos mexem neste store: o processo da skill que pediu
    a ligacao e o subprocess disparado pelo gateway quando o botao e tocado).

Estados de um pedido: pending -> approved | rejected | expired.
A execucao (discagem) e registrada em separado no proprio pedido
("execution"), com claim de USO UNICO: mesmo com double-tap ou callback
repetido, no maximo UMA discagem por pedido aprovado.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"

DEFAULT_TIMEOUT_SECONDS = 900  # 15 minutos

_LOCK_RETRY_SECONDS = 0.05
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_STALE_SECONDS = 60.0


class CallApprovalStoreError(RuntimeError):
    """Store corrompido/ilegivel ou transicao invalida. Fail-loud por design."""


def _get_hermes_home(env=None) -> Path:
    env = env if env is not None else os.environ
    val = (env.get("HERMES_HOME") or "").strip()
    if val:
        return Path(val)
    try:
        from hermes_constants import get_hermes_home as _ghh
        return _ghh()
    except Exception:
        return Path.home() / ".hermes"


def store_path(env=None) -> Path:
    env = env if env is not None else os.environ
    override = (env.get("TELNYX_CALL_APPROVAL_STORE_PATH") or "").strip()
    if override:
        return Path(override)
    return _get_hermes_home(env) / "telnyx_voice_sms" / "call_approvals.json"


def audit_path(env=None) -> Path:
    env = env if env is not None else os.environ
    override = (env.get("TELNYX_CALL_APPROVAL_AUDIT_PATH") or "").strip()
    if override:
        return Path(override)
    return _get_hermes_home(env) / "telnyx_voice_sms" / "call_approval_audit.jsonl"


def approval_timeout_seconds(env=None) -> int:
    env = env if env is not None else os.environ
    raw = (env.get("TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS") or "").strip()
    try:
        val = int(raw) if raw else DEFAULT_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return val if val > 0 else DEFAULT_TIMEOUT_SECONDS


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class _StoreLock:
    """Lock de arquivo cooperativo, stdlib-only e cross-platform.

    Usa O_CREAT|O_EXCL num arquivo <store>.lock. Lock com idade acima de
    _LOCK_STALE_SECONDS e considerado abandonado (processo morto) e quebrado.
    """

    def __init__(self, path: Path):
        self._lock_file = Path(str(path) + ".lock")
        self._acquired = False

    def __enter__(self):
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self._lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                self._acquired = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self._lock_file.stat().st_mtime
                    if age > _LOCK_STALE_SECONDS:
                        self._lock_file.unlink()
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise CallApprovalStoreError(
                        "timeout esperando o lock do store de aprovacoes: {0}".format(self._lock_file)
                    )
                time.sleep(_LOCK_RETRY_SECONDS)

    def __exit__(self, exc_type, exc, tb):
        if self._acquired:
            try:
                self._lock_file.unlink()
            except OSError:
                pass
        return False


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"requests": {}}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CallApprovalStoreError("nao consegui ler o store em {0}: {1}".format(path, e))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CallApprovalStoreError("store em {0} nao e JSON valido: {1}".format(path, e))
    if not isinstance(data, dict) or not isinstance(data.get("requests"), dict):
        raise CallApprovalStoreError(
            "store em {0} tem formato inesperado (esperado {{'requests': {{...}}}})".format(path)
        )
    return data


def _save(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def append_audit(event: str, request_id: str, env=None, now=None, **fields) -> dict:
    """Grava uma linha no audit log durvel (JSONL, append-only)."""
    rec = {"at": _iso(_now(now)), "event": event, "request_id": request_id}
    for key, value in fields.items():
        if value is not None:
            rec[key] = value
    path = audit_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if not existed:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return rec


def new_request_id() -> str:
    return "cr" + secrets.token_hex(4)


def create_request(contact: str, to: str, purpose: str, message: str,
                   timeout_seconds=None, env=None, now=None) -> dict:
    """Cria um pedido pendente. NAO envia nada e NAO disca nada."""
    contact = (contact or "").strip()
    to = (to or "").strip()
    purpose = (purpose or "").strip()
    message = (message or "").strip() or purpose
    if not contact:
        raise CallApprovalStoreError("contact vazio")
    if not to:
        raise CallApprovalStoreError("numero de destino vazio")
    if not purpose:
        raise CallApprovalStoreError("purpose vazio (todo pedido precisa dizer o objetivo da ligacao)")
    if timeout_seconds is None:
        timeout_seconds = approval_timeout_seconds(env)
    ts = _now(now)
    request = {
        "id": new_request_id(),
        "contact": contact,
        "to": to,
        "purpose": purpose,
        "message": message,
        "requested_at": _iso(ts),
        "expires_at": _iso(ts + timedelta(seconds=int(timeout_seconds))),
        "timeout_seconds": int(timeout_seconds),
        "status": STATUS_PENDING,
        "decided_at": None,
        "decided_by": None,
        "decided_by_name": None,
        "telegram_chat_id": None,
        "telegram_message_id": None,
        "execution": None,
    }
    path = store_path(env)
    with _StoreLock(path):
        data = _load(path)
        data["requests"][request["id"]] = request
        _save(data, path)
    append_audit("created", request["id"], env=env, now=ts,
                 contact=contact, to=to, purpose=purpose,
                 expires_at=request["expires_at"])
    return request


def get_request(request_id: str, env=None):
    data = _load(store_path(env))
    req = data["requests"].get(str(request_id or "").strip())
    return dict(req) if isinstance(req, dict) else None


def record_message_ref(request_id: str, chat_id, message_id, env=None) -> dict:
    """Guarda a referencia da mensagem de aprovacao enviada no Telegram."""
    path = store_path(env)
    with _StoreLock(path):
        data = _load(path)
        req = data["requests"].get(request_id)
        if not req:
            raise CallApprovalStoreError("pedido {0} nao existe".format(request_id))
        req["telegram_chat_id"] = str(chat_id) if chat_id is not None else None
        req["telegram_message_id"] = str(message_id) if message_id is not None else None
        _save(data, path)
        result = dict(req)
    append_audit("telegram_message_sent", request_id, env=env,
                 chat_id=result["telegram_chat_id"],
                 message_id=result["telegram_message_id"])
    return result


def _expire_locked(req: dict, ts: datetime) -> None:
    req["status"] = STATUS_EXPIRED
    req["decided_at"] = _iso(ts)
    req["decided_by"] = "timeout"


def decide_request(request_id: str, decision: str, decided_by=None,
                   decided_by_name=None, env=None, now=None) -> dict:
    """Grava a decisao humana (approve|reject) de forma ATOMICA e idempotente.

    Regras:
      - so um pedido PENDING pode ser decidido; a PRIMEIRA transicao vence;
      - um tap depois do expires_at NUNCA aprova: o pedido vira expired;
      - retorna {"ok", "status", "reason", "request"} sem nunca discar nada.
    """
    request_id = str(request_id or "").strip()
    decision = (decision or "").strip().lower()
    if decision not in ("approve", "reject"):
        return {"ok": False, "status": None, "reason": "invalid_decision", "request": None}
    ts = _now(now)
    path = store_path(env)
    audit_event = None
    with _StoreLock(path):
        data = _load(path)
        req = data["requests"].get(request_id)
        if not req:
            return {"ok": False, "status": None, "reason": "not_found", "request": None}
        if req.get("status") != STATUS_PENDING:
            return {"ok": False, "status": req.get("status"),
                    "reason": "already_decided", "request": dict(req)}
        expires_at = _parse_iso(req.get("expires_at"))
        if expires_at is not None and ts > expires_at:
            _expire_locked(req, ts)
            _save(data, path)
            result = {"ok": False, "status": STATUS_EXPIRED, "reason": "expired",
                      "request": dict(req)}
            audit_event = ("expired", {"detail": "tap depois do prazo"})
        else:
            req["status"] = STATUS_APPROVED if decision == "approve" else STATUS_REJECTED
            req["decided_at"] = _iso(ts)
            req["decided_by"] = str(decided_by) if decided_by is not None else None
            req["decided_by_name"] = str(decided_by_name) if decided_by_name else None
            _save(data, path)
            result = {"ok": True, "status": req["status"], "reason": "decided",
                      "request": dict(req)}
            audit_event = (req["status"],
                           {"decided_by": req["decided_by"],
                            "decided_by_name": req["decided_by_name"]})
    if audit_event:
        event, fields = audit_event
        append_audit(event, request_id, env=env, now=ts, **fields)
    return result


def expire_if_pending(request_id: str, env=None, now=None) -> dict:
    """Marca o pedido como expired se ainda estiver pendente (idempotente)."""
    request_id = str(request_id or "").strip()
    ts = _now(now)
    path = store_path(env)
    expired = False
    with _StoreLock(path):
        data = _load(path)
        req = data["requests"].get(request_id)
        if not req:
            return {"ok": False, "status": None, "reason": "not_found", "request": None}
        if req.get("status") == STATUS_PENDING:
            _expire_locked(req, ts)
            _save(data, path)
            expired = True
        result = {"ok": expired, "status": req.get("status"),
                  "reason": "expired" if expired else "not_pending",
                  "request": dict(req)}
    if expired:
        append_audit("expired", request_id, env=env, now=ts, detail="timeout sem resposta")
    return result


def claim_execution(request_id: str, env=None, now=None) -> dict:
    """Claim ATOMICO de uso unico da execucao de um pedido APROVADO.

    So o primeiro claim de um pedido aprovado retorna ok=True. Qualquer
    replay (double-tap, callback duplicado, retry do processo) recebe
    ok=False e NAO pode discar. Pedido em qualquer status != approved
    tambem recebe ok=False (o unico caminho ate a discagem real passa por
    um pedido aprovado e ainda nao executado).
    """
    request_id = str(request_id or "").strip()
    ts = _now(now)
    path = store_path(env)
    claimed = False
    with _StoreLock(path):
        data = _load(path)
        req = data["requests"].get(request_id)
        if not req:
            return {"ok": False, "status": None, "reason": "not_found", "request": None}
        if req.get("status") != STATUS_APPROVED:
            return {"ok": False, "status": req.get("status"),
                    "reason": "not_approved", "request": dict(req)}
        if req.get("execution"):
            return {"ok": False, "status": req.get("status"),
                    "reason": "already_claimed", "request": dict(req)}
        req["execution"] = {
            "claimed_at": _iso(ts),
            "executed_at": None,
            "sent": None,
            "call_control_id": None,
            "result_reason": None,
        }
        _save(data, path)
        claimed = True
        result = {"ok": True, "status": req["status"], "reason": "claimed",
                  "request": dict(req)}
    if claimed:
        append_audit("execution_claimed", request_id, env=env, now=ts)
    return result


def record_execution_result(request_id: str, sent: bool, call_control_id=None,
                            reason=None, env=None, now=None) -> dict:
    """Registra o resultado da tentativa de discagem do claim ja feito."""
    request_id = str(request_id or "").strip()
    ts = _now(now)
    path = store_path(env)
    with _StoreLock(path):
        data = _load(path)
        req = data["requests"].get(request_id)
        if not req or not req.get("execution"):
            raise CallApprovalStoreError(
                "pedido {0} sem claim de execucao para registrar resultado".format(request_id)
            )
        req["execution"]["executed_at"] = _iso(ts)
        req["execution"]["sent"] = bool(sent)
        req["execution"]["call_control_id"] = call_control_id
        req["execution"]["result_reason"] = reason
        _save(data, path)
        result = dict(req)
    append_audit("executed" if sent else "execution_blocked", request_id,
                 env=env, now=ts, call_control_id=call_control_id, reason=reason)
    return result


def list_requests(days=7, env=None, now=None) -> list:
    """Pedidos dos ultimos N dias, mais recentes primeiro.

    E o que responde "que ligacoes voce pediu essa semana": cada item traz
    contato, numero, motivo, status, quem decidiu, quando, e o resultado da
    execucao (se houve discagem, qual call_control_id).
    """
    ts = _now(now)
    cutoff = ts - timedelta(days=float(days))
    data = _load(store_path(env))
    out = []
    for req in data["requests"].values():
        requested_at = _parse_iso(req.get("requested_at"))
        if requested_at is None or requested_at >= cutoff:
            out.append(dict(req))
    out.sort(key=lambda r: r.get("requested_at") or "", reverse=True)
    return out
