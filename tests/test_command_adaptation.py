import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from command_adaptation import enrich_recipe, search_recipes  # noqa: E402


class TestCommandAdaptation(unittest.TestCase):
    def test_enrich_recipe_adds_tags(self):
        recipe = enrich_recipe({
            "issue": "Python missing",
            "explanation": "Install Python 3 for development.",
            "command": "sudo apt install python3",
            "risk": "Low",
        })
        self.assertIn("python", recipe["tags"])
        self.assertIn("python", recipe["keywords"].lower())

    def test_search_recipes_matches_tags(self):
        recipes = [
            enrich_recipe({"issue": "Git missing", "explanation": "Install git", "command": "sudo apt install git", "risk": "Low"}),
            enrich_recipe({"issue": "Docker missing", "explanation": "Install docker", "command": "sudo apt install docker.io", "risk": "Low"}),
        ]
        results = search_recipes(recipes, "version-control")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["issue"], "Git missing")


if __name__ == "__main__":
    unittest.main()
