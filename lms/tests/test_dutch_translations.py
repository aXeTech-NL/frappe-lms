"""Dutch catalog checks; runnable without a database using Python + Babel.

python -m unittest lms.tests.test_dutch_translations
"""

import ast
import gettext
import io
import re
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import Mock

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

ROOT = Path(__file__).resolve().parents[2]
LOCALE = ROOT / "lms" / "locale"
PLACEHOLDERS = re.compile(r"\{\d+\}|\{\{.*?\}\}|%\([^)]+\)[sdf]")


class TestDutchTranslations(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		with (LOCALE / "nl.po").open("rb") as source:
			cls.catalog = read_po(source, locale="nl", abort_invalid=True)
		with (LOCALE / "main.pot").open("rb") as source:
			cls.template = read_po(source, abort_invalid=True)
		# Babel mistakes the literal "% c" in "% correct" for printf syntax.
		# This Vue message uses numbered braces, checked separately below.
		cls.catalog["You got {0}% correct answers with a score of {1} out of {2}"].flags.discard(
			"python-format"
		)

	def test_every_catalog_message_is_translated_and_not_fuzzy(self):
		for message in self.catalog:
			if not message.id:
				continue
			with self.subTest(message=message.id):
				self.assertTrue(message.string.strip())
				self.assertNotIn("fuzzy", message.flags)
				self.assertEqual(message.check(self.catalog), [])

	def test_no_duplicate_message_ids_are_silently_dropped(self):
		# Babel merges duplicate ids on read. Count active PO records too,
		# subtracting the header, so an accidental duplicate cannot pass.
		raw = (LOCALE / "nl.po").read_text(encoding="utf-8")
		self.assertEqual(len(self.catalog), len(re.findall(r"^msgid ", raw, re.MULTILINE)) - 1)

	def test_covers_the_upstream_template(self):
		for message in self.template:
			if message.id:
				with self.subTest(message=message.id):
					self.assertIn(message.id, self.catalog)

	def test_preserves_interpolation_and_email_template_variables(self):
		for message in self.catalog:
			if not message.id:
				continue
			with self.subTest(message=message.id):
				self.assertEqual(
					Counter(PLACEHOLDERS.findall(message.id)),
					Counter(PLACEHOLDERS.findall(message.string)),
				)

	def test_compiles_and_loads_as_a_dutch_gettext_catalog(self):
		binary = io.BytesIO()
		write_mo(binary, self.catalog)
		binary.seek(0)
		translations = gettext.GNUTranslations(binary)
		for source, expected in {
			"Courses": "Cursussen",
			"Batches": "Lesgroepen",
			"Programs": "Leertrajecten",
			"Settings": "Instellingen",
			"Save": "Opslaan",
			"My access": "Mijn toegang",
			"Continue your course": "Ga verder met je cursus",
			"Start Quiz": "Toets starten",
			"Checkout is currently unavailable.": "Afrekenen is momenteel niet beschikbaar.",
			"{0} of {1} lessons completed": "{0} van {1} lessen afgerond",
		}.items():
			with self.subTest(message=source):
				self.assertEqual(translations.gettext(source), expected)
		self.assertEqual(translations.gettext("An unknown message"), "An unknown message")

	def test_api_uses_the_same_language_resolver_as_the_shell(self):
		# Execute the actual endpoint body without importing the Frappe app or
		# opening a database. User/system fallback belongs to get_user_lang;
		# the endpoint must not reimplement it with a nullable User.language.
		tree = ast.parse((ROOT / "lms" / "lms" / "api.py").read_text())
		endpoint = next(
			node
			for node in tree.body
			if isinstance(node, ast.FunctionDef) and node.name == "get_translations"
		)
		endpoint.decorator_list = []
		module = ast.Module(body=[endpoint], type_ignores=[])
		for language in ("nl", "en", "nl-NL"):
			with self.subTest(language=language):
				resolver = Mock(return_value=language)
				loader = Mock(return_value={"Courses": "Cursussen"})
				namespace = {"get_user_lang": resolver, "get_all_translations": loader}
				exec(compile(module, "api.py", "exec"), namespace)
				self.assertEqual(namespace["get_translations"](), loader.return_value)
				resolver.assert_called_once_with()
				loader.assert_called_once_with(language)


if __name__ == "__main__":
	unittest.main()
