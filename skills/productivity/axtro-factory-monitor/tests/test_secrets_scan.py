"""
Testes do vigia de segredo vazado (secrets_scan.py). Puro, sem git real.

    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import secrets_scan as ss  # noqa: E402


class LooksLikePlaceholderTestCase(unittest.TestCase):
    def test_example_key_is_placeholder(self):
        self.assertTrue(ss.looks_like_placeholder("ANTHROPIC_API_KEY=your_key_here"))

    def test_real_looking_value_is_not_flagged_as_placeholder(self):
        self.assertFalse(ss.looks_like_placeholder("token: 8f2a9c1e7b3d5f0a"))


class ScanRepoPatternTestCase(unittest.TestCase):
    def test_documentation_placeholder_slack_token_is_ignored(self):
        # Caso real encontrado em teste manual: website/docs/.../slack.md continha
        # "xoxb-your-token-here" — não é vazamento, é exemplo de documentação.
        line = 'website/docs/user-guide/messaging/slack.md:193:token = "xoxb-your-token-here"'
        path = line.split(":", 2)[0]
        self.assertTrue(any(h in path.lower() for h in ss.IGNORE_PATH_HINTS))

    def test_value_placeholder_words_catch_dictionary_words_in_secret(self):
        # segredo de verdade é aleatório; presença de palavra de dicionário no valor
        # casado é sinal de que é exemplo, não vazamento real.
        snippet = "sk-ant-your-key-here"
        self.assertTrue(any(w in snippet.lower() for w in ss.VALUE_PLACEHOLDER_WORDS))

    def test_realistic_random_secret_value_has_no_placeholder_words(self):
        snippet = "sk-ant-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
        self.assertFalse(any(w in snippet.lower() for w in ss.VALUE_PLACEHOLDER_WORDS))

    def test_mask_shortens_long_secret_without_revealing_middle(self):
        masked = ss.mask("sk-ant-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6")
        self.assertTrue(masked.startswith("sk-ant"))
        self.assertNotIn("a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6", masked)

    def test_mask_handles_short_strings_without_crashing(self):
        masked = ss.mask("abc")
        self.assertTrue(masked.startswith("ab"))


if __name__ == "__main__":
    unittest.main()
