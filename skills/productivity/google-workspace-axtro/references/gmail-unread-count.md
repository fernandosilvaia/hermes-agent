
# Fetching Unread Email Count and Details

This document details the successful procedure for checking unread email counts using the `google-workspace-axtro` skill.

## Prerequisites

1.  **Authentication:** Ensure the `auth.py` script has been successfully run, confirming authentication with the Google Workspace account (`axtro@axtroai.com` in this case). The output should indicate:
    ```
    [auth] OK — autenticação funcionando
      impersonating: axtro@axtroai.com
      emailAddress: axtro@axtroai.com
      messagesTotal: <number>  # Total messages in the inbox
      service_account_email: <service_account_email>
    ```
2.  **Dependencies:** The necessary Python packages (`google-api-python-client`, `google-auth`, `google-auth-httplib2`) must be available. The `uv run` command is used to ensure this:
    ```bash
    uv run --with google-api-python-client --with google-auth --with google-auth-httplib2 python <script_name>.py ...
    ```

## Procedure

To retrieve a list of unread emails, execute the `gmail.py` script with the `search` command and the `is:unread` query:

```bash
cd /opt/data/skills/productivity/google-workspace-axtro/scripts && uv run --with google-api-python-client --with google-auth --with google-auth-httplib2 python gmail.py search --query "is:unread"
```

## Output Format

The command returns a JSON list of email objects. Each object contains:
- `id`: Unique message ID.
- `threadId`: ID of the thread the message belongs to.
- `from`: Sender's name and email address.
- `subject`: Subject of the email.
- `date`: Date and time the email was sent (RFC 2822 format).
- `snippet`: A short preview of the email's content.
- `unread`: Boolean indicating if the email is unread (will be `true` for results from this query).

**Example Output Snippet:**

```json
[
  {
    "id": "19e70cf4987b4dc4",
    "threadId": "19e70cf4987b4dc4",
    "from": "Contato Axtro AI <contato@inbox.axtroai.com>",
    "subject": "🚨 AVISO FINAL: Nós estamos AO VIVO (Não fique de fora)",
    "date": "Thu, 28 May 2026 22:58:12 +0000",
    "snippet": "🔴 AO VIVO: O link foi liberado (A sala está enchendo rápido) O jogo começou. A nossa live sobre a Profissão Mais Bem Paga do Mundo está começando e o link oficial para a sala fechada acaba de ser",
    "unread": true
  },
  // ... more emails
]
```

## Post-processing

The JSON output can be parsed and presented in a more human-readable format, such as a table, displaying key information like sender, subject, and date.
