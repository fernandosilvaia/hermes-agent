---
name: charge-customer
description: Cobrança de cliente (exemplo de skill BLOQUEADA sem aprovação humana).
version: 1.0.0
metadata:
  hermes:
    risk_class: financial_sensitive
    autonomy_ring: 3
---

# charge-customer (exemplo — skill BLOQUEADA)

Skill **financial_sensitive / Ring 3**. Sem `HERMES_HUMAN_APPROVAL`, o Autonomy
Core deixa rodar só em **dry-run** (simula, nenhuma cobrança). É a demonstração de
que dinheiro **nunca** sai por acidente.

Além disso, o próprio `charge.py` tem gate de dupla-env fail-closed: mesmo rodado
DIRETO (burlando o runner), não cobra nada real sem os 3 gates + aprovação.

## Como rodar (via executor oficial)
```bash
python3 axtro/skill_runner.py axtro/skill_examples/charge-customer scripts/charge.py
# → DRY-RUN, cobranca_real=false (sem aprovação)
```
