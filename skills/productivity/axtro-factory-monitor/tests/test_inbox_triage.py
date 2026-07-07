"""
Testes de classify_heuristic (inbox_triage.py). Puro, sem rede/auth.

    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import inbox_triage as it  # noqa: E402


class ClassifyHeuristicTestCase(unittest.TestCase):
    def test_marketing_language_is_spam(self):
        msg = {"from": "promo@loja.com", "subject": "50% off só hoje!", "snippet": "confira nossa oferta"}
        self.assertEqual(it.classify_heuristic(msg), "spam")

    def test_urgent_keyword_in_subject(self):
        msg = {"from": "cliente@empresa.com", "subject": "URGENTE: preciso de resposta hoje", "snippet": ""}
        self.assertEqual(it.classify_heuristic(msg), "urgente")

    def test_legit_system_notification_is_not_spam(self):
        # Caso real encontrado em teste manual: notificação de Drive-share com "noreply"
        # no remetente foi classificada errado como spam antes do ajuste.
        msg = {
            "from": '"Jéssica Petri (via Google Drive)" <drive-shares-dm-noreply@google.com>',
            "subject": 'Pasta compartilhada com você: "Devs_TI"',
            "snippet": "",
        }
        self.assertEqual(it.classify_heuristic(msg), "rotina")

    def test_calendar_invite_is_routine_not_urgent(self):
        msg = {"from": "fernando@axtroai.com", "subject": 'Accept your invitation to join shared calendar: "X"', "snippet": ""}
        self.assertEqual(it.classify_heuristic(msg), "rotina")

    def test_ambiguous_message_defaults_to_precisa_de_voce(self):
        msg = {"from": "alguem@empresa.com", "subject": "Sobre nossa reunião", "snippet": "Podemos conversar?"}
        self.assertEqual(it.classify_heuristic(msg), "precisa_de_voce")

    def test_spam_signal_takes_precedence_over_urgent_wording(self):
        # newsletter que usa linguagem de urgência pra chamar atenção continua sendo spam
        msg = {"from": "newsletter@marketing.com", "subject": "Urgente: cupom expira hoje! Cancelar inscrição no rodapé", "snippet": ""}
        self.assertEqual(it.classify_heuristic(msg), "spam")


if __name__ == "__main__":
    unittest.main()
