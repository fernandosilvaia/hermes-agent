---
name: safe-diagnostic
description: Diagnóstico read-only da fábrica (exemplo de skill SEGURA do Autonomy Core).
version: 1.0.0
metadata:
  hermes:
    risk_class: safe
    autonomy_ring: 0
---

# safe-diagnostic (exemplo — skill SEGURA)

Skill de **Ring 0 / risk_class=safe**: observa, lê e relata. Não muta nada, não
chama rede, não gasta. O Autonomy Core deixa rodar **sozinha**.

## Como rodar (via executor oficial)
```bash
python3 axtro/skill_runner.py axtro/skill_examples/safe-diagnostic scripts/run.py
```
Resultado esperado: executa em modo `production`, `ação real` (read-only), log gravado.
