import os
import tempfile
from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

from lms.lms.api import delete_scorm_package
from lms.patches.v2_0.prepare_subscription_entitlements import move_public_scorm_packages


class TestSubscriptionPatch(UnitTestCase):
	def test_public_scorm_is_moved_without_overwriting_private_copy(self):
		original_site_path = frappe.local.site_path
		with tempfile.TemporaryDirectory() as site_path:
			frappe.local.site_path = site_path
			try:
				public = Path(site_path) / "public" / "scorm" / "course" / "chapter"
				private = Path(site_path) / "private" / "scorm" / "course" / "chapter"
				public.mkdir(parents=True)
				private.mkdir(parents=True)
				(public / "launch.html").write_text("legacy")
				(public / "asset.js").write_text("asset")
				(private / "launch.html").write_text("current")

				move_public_scorm_packages()

				self.assertEqual((private / "launch.html").read_text(), "current")
				self.assertEqual((private / "asset.js").read_text(), "asset")
				self.assertFalse(os.path.exists(Path(site_path) / "public" / "scorm"))
			finally:
				frappe.local.site_path = original_site_path

	def test_scorm_delete_removes_private_and_legacy_public_extractions(self):
		original_site_path = frappe.local.site_path
		with tempfile.TemporaryDirectory() as site_path:
			frappe.local.site_path = site_path
			try:
				for visibility in ("private", "public"):
					package = Path(site_path) / visibility / "scorm" / "course" / "chapter"
					package.mkdir(parents=True)
					(package / "launch.html").write_text(visibility)

				delete_scorm_package("/scorm/course/chapter")

				self.assertFalse(Path(site_path, "private", "scorm", "course", "chapter").exists())
				self.assertFalse(Path(site_path, "public", "scorm", "course", "chapter").exists())
			finally:
				frappe.local.site_path = original_site_path

	def test_scorm_delete_rejects_paths_outside_scorm_root(self):
		with self.assertRaises(frappe.ValidationError):
			delete_scorm_package("/scorm/course/../secrets")
