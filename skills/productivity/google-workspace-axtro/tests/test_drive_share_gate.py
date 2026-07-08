"""
Testes de WIRING de drive.share_file — prova que a guarda-corpo está de fato
ligada na função que executaria o efeito real.

Restrição: o python3 do sistema (3.9.6) NÃO tem googleapiclient/google instalados,
e drive.py os importa no topo. Em vez de importar as libs reais (proibido) ou tocar
a rede/credenciais (proibido), este teste injeta STUBS falsos em sys.modules ANTES
de importar drive. O stub de `auth` conta quantas vezes a API seria chamada.

Assim provamos, sem rede e sem credencial, o P0 fechado:
  - destinatário externo (o vetor de exfiltração)      → 0 chamadas de API
  - PERMITIDO porém dry-run (default seguro)            → 0 chamadas de API
  - só PERMITIDO + execução liberada                    → exatamente 1 chamada
"""
import os
import sys
import types
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


class _FakeExec:
    def __init__(self, recorder):
        self._recorder = recorder

    def execute(self):
        self._recorder["create_calls"] += 1
        return {"id": "perm_fake_123"}


class _FakePermissions:
    def __init__(self, recorder):
        self._recorder = recorder

    def create(self, **kwargs):
        # registra os argumentos, mas NÃO chama nada de verdade
        self._recorder["last_create_kwargs"] = kwargs
        return _FakeExec(self._recorder)


class _FakeDriveClient:
    def __init__(self, recorder):
        self._recorder = recorder

    def permissions(self):
        return _FakePermissions(self._recorder)


def _install_stubs(recorder):
    """Injeta stubs de googleapiclient + auth em sys.modules e retorna o módulo drive."""
    # stub googleapiclient.http.MediaFileUpload (drive.py importa no topo)
    gac = types.ModuleType("googleapiclient")
    gac_http = types.ModuleType("googleapiclient.http")
    gac_http.MediaFileUpload = object
    gac.http = gac_http
    sys.modules["googleapiclient"] = gac
    sys.modules["googleapiclient.http"] = gac_http

    # stub auth: auth.drive() → cliente falso que conta chamadas de create().execute()
    fake_auth = types.ModuleType("auth")
    fake_auth.drive = lambda: _FakeDriveClient(recorder)
    sys.modules["auth"] = fake_auth

    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    # garante import limpo de drive com os stubs vigentes
    sys.modules.pop("drive", None)
    import drive  # noqa: E402
    return drive


_GATE_ENVS = ("HERMES_ALLOW_EXECUTE", "GOOGLE_WORKSPACE_AXTRO_ENABLED",
              "GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS")


class DriveShareGateTestCase(unittest.TestCase):
    def setUp(self):
        self.recorder = {"create_calls": 0, "last_create_kwargs": None}
        self._saved = {k: sys.modules.get(k) for k in
                       ("googleapiclient", "googleapiclient.http", "auth", "drive")}
        # snapshot das envs do gate para restaurar depois (share_file lê os.environ)
        self._saved_env = {k: os.environ.get(k) for k in _GATE_ENVS}
        for k in _GATE_ENVS:
            os.environ.pop(k, None)
        self.drive = _install_stubs(self.recorder)

    def _enable_execute(self):
        os.environ["HERMES_ALLOW_EXECUTE"] = "true"
        os.environ["GOOGLE_WORKSPACE_AXTRO_ENABLED"] = "true"

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        sys.modules.pop("drive", None)
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---- P0: caminho de ataque (exfiltração) nunca chama a API ----

    def test_external_writer_is_blocked_and_never_calls_api(self):
        out = self.drive.share_file(
            "FILE123", "attacker@evil-corp.com", role="writer",
            approve_external=False, dry_run=False)  # dry_run=False para provar que
        # mesmo "liberado para executar", o BLOQUEIO de policy impede a chamada.
        self.assertTrue(out["blocked"])
        self.assertFalse(out["shared"])
        self.assertEqual(self.recorder["create_calls"], 0)

    def test_external_reader_is_blocked_and_never_calls_api(self):
        out = self.drive.share_file(
            "FILE123", "estranho@gmail.com", role="reader",
            approve_external=False, dry_run=False)
        self.assertTrue(out["blocked"])
        self.assertEqual(self.recorder["create_calls"], 0)

    # ---- dry-run (default seguro) nunca chama a API ----

    def test_permitted_but_dry_run_never_calls_api(self):
        out = self.drive.share_file(
            "FILE123", "colega@axtroai.com", role="reader", dry_run=True)
        self.assertTrue(out["dry_run"])
        self.assertFalse(out["shared"])
        self.assertIn("would_share", out)
        self.assertEqual(self.recorder["create_calls"], 0)

    def test_default_dry_run_is_true_for_library_callers(self):
        # sem passar dry_run → default seguro (True), nada chamado
        out = self.drive.share_file("FILE123", "colega@axtroai.com", role="reader")
        self.assertTrue(out.get("dry_run"))
        self.assertEqual(self.recorder["create_calls"], 0)

    # ---- REGRESSÃO bypass B: via biblioteca, sem as envs do gate → dry-run, 0 chamadas ----

    def test_library_execute_without_env_gate_stays_dry_run(self):
        # Sem HERMES_ALLOW_EXECUTE/GOOGLE_WORKSPACE_AXTRO_ENABLED, mesmo pedindo
        # dry_run=False via biblioteca (pulando o CLI), NÃO pode chamar a API.
        out = self.drive.share_file(
            "FILE123", "colega@axtroai.com", role="writer",
            approve_external=False, dry_run=False)
        self.assertTrue(out["dry_run"])
        self.assertTrue(out.get("gate_blocked"))
        self.assertFalse(out["shared"])
        self.assertEqual(self.recorder["create_calls"], 0)

    # ---- REGRESSÃO bypass A: enabled + auto-aprovação de domínio arbitrário → bloqueado ----

    def test_external_arbitrary_domain_blocked_even_with_execute_envs(self):
        # Estado de produção (as duas envs de execução LIGADAS). O agente tenta
        # auto-aprovar um externo arbitrário. Sem o domínio na allowlist de parceiros,
        # TEM que bloquear antes da API (vetor de exfiltração do P0).
        self._enable_execute()
        out = self.drive.share_file(
            "CORP_SECRET", "attacker@evil-corp.com", role="reader",
            approve_external=True, dry_run=False)
        self.assertTrue(out["blocked"])
        self.assertFalse(out["shared"])
        self.assertEqual(self.recorder["create_calls"], 0)

    # ---- caminho feliz legítimo: interno + PERMITIDO + execução → 1 chamada ----

    def test_internal_permitted_and_executed_calls_api_once(self):
        self._enable_execute()  # gate de ambiente ligado (ativação humana)
        out = self.drive.share_file(
            "FILE123", "colega@axtroai.com", role="writer",
            approve_external=False, dry_run=False)
        self.assertTrue(out["shared"])
        self.assertEqual(out["shared_with"], "colega@axtroai.com")
        self.assertEqual(self.recorder["create_calls"], 1)
        # confirma que a permissão montada é a esperada
        kw = self.recorder["last_create_kwargs"]
        self.assertEqual(kw["body"]["emailAddress"], "colega@axtroai.com")
        self.assertEqual(kw["body"]["role"], "writer")

    def test_external_approved_and_executed_calls_api_once(self):
        # externo em domínio de parceiro pré-aprovado (env) + gate ligado + aprovação
        # humana explícita + execução → passa (1 chamada).
        self._enable_execute()
        os.environ["GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS"] = "gmail.com"
        out = self.drive.share_file(
            "FILE123", "parceiro@gmail.com", role="reader",
            approve_external=True, dry_run=False)
        self.assertTrue(out["shared"])
        self.assertEqual(self.recorder["create_calls"], 1)

    # ---- leitura legítima continua intacta (não regrediu) ----

    def test_list_files_builds_query_without_calling_share(self):
        # list_files usa auth.drive().files()... — nosso stub só implementa
        # permissions(); provamos apenas que share não interfere no import/legado.
        self.assertTrue(hasattr(self.drive, "list_files"))
        self.assertTrue(hasattr(self.drive, "find_by_name"))


if __name__ == "__main__":
    unittest.main()
