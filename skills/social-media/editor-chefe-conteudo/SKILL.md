---
name: editor-chefe-conteudo
description: "FILA_CONTEUDO_DIARIO — o Editor-Chefe da Axtro AI: escolhe a melhor história real do dia, produz carrossel/texto, manda pra aprovação no Telegram antes de qualquer publicação. v1: banco de histórias fixo (dias 1-7), sem HeyGen/Blotato."
platforms: [linux, macos, windows]
---

# Editor-Chefe — Fila de Conteúdo Diário (Axtro AI)

Implementação v1 do protocolo `FILA_CONTEUDO_DIARIO.md`: todo dia às 18h ET,
escolhe uma história real da operação da Axtro AI, produz o roteiro de
conteúdo, e manda pro Fernando aprovar no Telegram. **Nada publica sem
aprovação explícita.**

Esta é a página institucional da **Axtro AI** (a fábrica se documentando —
histórias sobre os agentes e projetos). Não confundir com uma futura fila
pra página pessoal do Fernando, que é conteúdo diferente (sobre ele, não
sobre "a fábrica") e ainda não foi desenhada.

## ⚠️ Pegadinha de ambiente descoberta na prática (leia antes de mexer nos crons)

O parâmetro `workdir` do `hermes cron create/edit` **não é confiável** — mesmo
setado, o terminal do agente numa execução de cron pode abrir em
`/opt/hermes` (pasta do framework, não da skill) com `$HOME` resolvendo pra
um caminho tipo `/opt/data/home`, diferente do que `docker exec --user
hermes` mostra manualmente. Isso já causou 7 tentativas falhas em sequência
(2026-07-29) onde o agente achava que tinha salvo o pacote mas nunca tinha
executado o comando de verdade, ou executava em cwd errado e falhava
silenciosamente sem reportar direito.

**Correção aplicada, sempre fazer assim daqui pra frente:**
1. Nunca confiar em `workdir` sozinho. Sempre usar o **caminho absoluto
   completo** do script no prompt do cron:
   `/opt/hermes/.venv/bin/python3 /opt/data/skills/social-media/editor-chefe-conteudo/scripts/editor_chefe.py <comando>`.
2. `editor_chefe.py` usa `EDITOR_CHEFE_STATE_DIR` (env var, default
   `~/.hermes/conteudo`) — na VPS está fixada em `/opt/data/conteudo` via
   `.env` do container, exatamente pra não depender de qual `$HOME` o
   terminal resolve numa execução de cron.
3. Ao testar manualmente via `docker exec`, sempre `--user hermes` E setar
   `EDITOR_CHEFE_STATE_DIR` explicitamente na chamada, pra bater com o que o
   cron de verdade usa — testar sem isso engana (mostra "sem pendente"
   mesmo quando o cron real já salvou algo, só que em outro `$HOME`).

## Escopo do v1 (o que tem e o que não tem)

**Tem:** banco de histórias fixo dos 7 dias iniciais (`editor_chefe.py` já
embute o texto de cada uma), formato CARROSSEL (roteiro slide a slide em
markdown) + TEXTO derivado (legenda curta), gate de aprovação por Telegram
com ✅/✏️/⏭️, expiração automática se não responder até 21h ET.

**Não tem ainda (fase 2):** mineração de log dos 60+ agentes (Fases 1-2 do
protocolo original — a partir do dia 8 do sprint, precisa ser desenhado
onde ler os logs de verdade), RAISSA_VIDEO via HeyGen, SCREEN_DEMO com
gravação de tela real, publicação via Blotato. `editor_chefe.py` já troca
RAISSA_VIDEO/SCREEN_DEMO por CARROSSEL equivalente nos dias que pediam esses
formatos, até a fase 2 estar pronta.

## O que a skill de estado (`editor_chefe.py`) faz — e o que NÃO faz

Ela só guarda estado (JSON em `~/.hermes/conteudo/estado.json`): qual dia do
sprint, o pacote pendente de aprovação, o histórico de decisões. **Quem
escreve a história/roteiro de verdade é o próprio agente**, na hora do cron,
lendo `banco-entry` pra saber a história do dia e escrevendo o carrossel
seguindo a especificação de formatação abaixo — a lib não gera conteúdo
sozinha.

## Fluxo (dois crons + comportamento de chat)

### Cron 1 — Produção, 18h00 ET todo dia

1. `python editor_chefe.py has-pending` — se já tem pendente sem resposta
   (não devia, o cron das 21h cuida disso), pare e avise no Telegram.
2. `python editor_chefe.py sprint-day` — descobre o dia do sprint.
3. Se dia ≤ 7: `python editor_chefe.py banco-entry --day N` pra pegar a
   história e o formato do dia.
4. Escreva o roteiro do CARROSSEL (ver especificação abaixo) + a legenda do
   TEXTO derivado.
5. `python editor_chefe.py save-pending --dia-sprint N --historia "..." --formato-principal CARROSSEL --formato-derivado TEXTO --json '{"slides": [...], "legenda": "...", "hashtags": [...]}'`
6. Responda no formato do pacote de aprovação (ver "Mensagem de aprovação"
   abaixo) — o cron entrega isso automaticamente pro Telegram.

### Cron 2 — Expiração, 21h00 ET todo dia

`python editor_chefe.py expire-check`. Se `expirou: true`, avise em 1 linha
curta que o conteúdo de hoje não teve resposta e ficou de fora (silêncio
nunca é aprovação — regra inegociável do protocolo original). Se
`expirou: false`, fique em silêncio (`[SILENT]`).

### Comportamento de chat (fora dos crons)

Quando o Fernando responder no chat algo que pareça decisão sobre o pacote
pendente (✅/"aprovar"/"pode publicar", ✏️/"editar: ...", ⏭️/"pular"/"passa
esse"):

1. `python editor_chefe.py get-pending` pra confirmar que existe pendente e
   ver do que se trata (nunca assuma, sempre confirme o conteúdo antes de
   agir numa resposta ambígua).
2. `python editor_chefe.py decide --decision aprovado` (ou `pular`, ou
   `editar --instrucao "..."`).
3. Se foi "editar": aplique o ajuste pedido no roteiro, gere o pacote
   atualizado, e rode `save-pending` de novo (o `decide --decision editar`
   deixa o pendente em status `editando`, então antes de salvar de novo
   você precisa de um jeito de limpar esse pendente — hoje o fluxo simples é
   rodar `decide --decision pular` nele e criar um pendente novo já
   corrigido, documentando a instrução recebida).
4. Se foi "aprovado": confirme no chat que ficou registrado. **v1 não
   publica sozinho** — o pacote aprovado fica pronto pro Fernando postar
   manualmente (Fase 6 v1 do protocolo original). Ofereça o roteiro/legenda
   formatados pra copiar e colar.

## Especificação do CARROSSEL (Fase 4.2 do protocolo original)

- Slide 1 (gancho): número ou tensão real. Ex.: "Meu funcionário passou 40
  minutos no telefone com a ADP. Custou 6 centavos."
- Slides 2-8: a história em passos, 1 ideia por slide, frases curtas.
- Slide 9: o recibo (descreva o print/log real disponível; se não tiver o
  arquivo em mãos, diga isso no pacote de aprovação em vez de inventar).
- Slide 10 (CTA): "Quer ver o diagnóstico disso no seu negócio? Link na bio."
- Identidade visual pretendida: fundo preto ou branco, destaque **#E30613**,
  tipografia limpa. v1 entrega só o roteiro em markdown (texto de cada
  slide) — a arte final (imagem/PNG) ainda não é gerada automaticamente.

## Mensagem de aprovação (Fase 5, formato exato)

```
🗞️ CONTEÚDO DO DIA — AAAA-MM-DD
História: [1 frase]
Formato: CARROSSEL + TEXTO

[roteiro completo: os 10 slides + a legenda do texto derivado]

Responda:
✅ APROVAR — fica pronto pra você postar
✏️ EDITAR: [instrução] — ajusto e reenvio
⏭️ PULAR — arquivo a história pra outro dia
```

## Regras inegociáveis (herdadas do protocolo original, sem exceção)

1. Nada é considerado aprovado sem ✅ explícito. Silêncio até 21h ET = não
   publica, expira sozinho.
2. Nenhum número inventado, estimado ou arredondado pra cima — só o que
   está descrito na história do banco (ou, na fase 2, confirmado em log).
3. Projetos internos da Axtro (as 7 histórias do banco) são liberados por
   padrão — não precisam de autorização de cliente porque não citam cliente
   identificável.
4. Nenhum gasto de mídia/impulsionamento é executado pelo agente — fora do
   escopo do v1 de qualquer forma.
5. Não citar preço de produto no conteúdo.

## Autonomia

Anel 0 pra produção do rascunho (`save-pending`, escrever o roteiro) —
nunca publica nada sozinho. `decide --decision aprovado` só roda depois de
confirmação explícita do Fernando na conversa.
