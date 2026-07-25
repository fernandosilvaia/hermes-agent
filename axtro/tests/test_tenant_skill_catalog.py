"""Prova que o catálogo de skills por-conector nunca expõe skill interna da
Axtro a um perfil-cliente — fail-closed by construction, não por checklist."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tenant_skill_catalog as catalog


class TestTenantSkillCatalog(unittest.TestCase):
    def test_internal_only_skills_never_reachable_from_base(self):
        overlap = set(catalog.TENANT_BASE_SKILLS) & catalog.INTERNAL_ONLY_SKILLS
        self.assertEqual(overlap, set())

    def test_internal_only_skills_never_reachable_from_any_connector(self):
        all_connector_skills = {
            skill
            for skills in catalog.CONNECTOR_SKILL_MAP.values()
            for skill in skills
        }
        overlap = all_connector_skills & catalog.INTERNAL_ONLY_SKILLS
        self.assertEqual(overlap, set())

    def test_eligible_skills_for_no_connectors_is_just_base(self):
        self.assertEqual(
            set(catalog.eligible_skills_for_connectors(())),
            set(catalog.TENANT_BASE_SKILLS),
        )

    def test_eligible_skills_never_includes_internal_only(self):
        all_connector_keys = tuple(catalog.CONNECTOR_SKILL_MAP.keys())
        result = set(catalog.eligible_skills_for_connectors(all_connector_keys))
        self.assertEqual(result & catalog.INTERNAL_ONLY_SKILLS, set())

    def test_google_connector_maps_to_generic_skill_never_axtro_variant(self):
        google_skills = catalog.CONNECTOR_SKILL_MAP["google"]
        self.assertIn("google-workspace", google_skills)
        self.assertNotIn("google-workspace-axtro", google_skills)

    def test_unknown_connector_key_is_ignored_not_an_error(self):
        result = catalog.eligible_skills_for_connectors(("not_a_real_connector",))
        self.assertEqual(set(result), set(catalog.TENANT_BASE_SKILLS))


if __name__ == "__main__":
    unittest.main()
