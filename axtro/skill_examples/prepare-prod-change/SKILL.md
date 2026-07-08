---
name: prepare-prod-change
description: Prepara mudança de produção; aplica só com aprovação humana (exemplo).
version: 1.0.0
metadata:
  hermes:
    risk_class: production_sensitive
    autonomy_ring: 3
---

# prepare-prod-change (exemplo — production_sensitive)

Skill **production_sensitive / Ring 3**. Sem `HERMES_HUMAN_APPROVAL`, o Autonomy
Core deixa só montar o **plano** (dry-run). Com aprovação, sobe para `staging`
(neste build de segurança, produção real fica protegida mesmo com aprovação).

## Como rodar (via executor oficial)
```bash
# sem aprovação → plano em dry-run, aplicou=false
python3 axtro/skill_runner.py axtro/skill_examples/prepare-prod-change scripts/prepare.py

# com aprovação humana (setada FORA do daemon) → staging
HERMES_HUMAN_APPROVAL=true python3 axtro/skill_runner.py \
    axtro/skill_examples/prepare-prod-change scripts/prepare.py
```
