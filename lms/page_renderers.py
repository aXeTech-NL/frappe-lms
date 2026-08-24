"""Custom page renderers for LMS app.

Handles rendering of profile pages.
"""

import mimetypes
import os
import shutil
from urllib.parse import unquote

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response
from werkzeug.wsgi import wrap_file


def protect_legacy_scorm_packages() -> int:
	"""Move legacy public SCORM bytes behind the permission-aware renderer.

	The standard production nginx config serves ``public/scorm`` before Python,
	so no runtime hook can protect those bytes. Preserve unmanaged sites exactly:
	the relocation runs only when an external entitlement provider is installed.
	Provider apps should call this after installation; LMS also calls it after
	migrate for already-installed providers. Stored ``/scorm/...`` URLs do not
	change because the renderer resolves private storage first.
	"""
	from lms.entitlements import has_provider

	if not has_provider():
		return 0

	public_root = frappe.get_site_path("public", "scorm")
	private_root = frappe.get_site_path("private", "scorm")
	if not os.path.isdir(public_root):
		return 0

	os.makedirs(private_root, exist_ok=True)
	moved = 0
	for root, directories, files in os.walk(public_root, topdown=False, followlinks=False):
		relative = os.path.relpath(root, public_root)
		destination_root = private_root if relative == "." else os.path.join(private_root, relative)
		os.makedirs(destination_root, exist_ok=True)
		for filename in files:
			source = os.path.join(root, filename)
			destination = os.path.join(destination_root, filename)
			if os.path.islink(source):
				os.unlink(source)
			elif os.path.exists(destination):
				os.unlink(source)
			else:
				shutil.move(source, destination)
			moved += 1
		for directory in directories:
			path = os.path.join(root, directory)
			if os.path.islink(path):
				os.unlink(path)
			elif os.path.isdir(path) and not os.listdir(path):
				os.rmdir(path)
	if os.path.isdir(public_root) and not os.listdir(public_root):
		os.rmdir(public_root)
	return moved


class SCORMRenderer(BaseRenderer):
	def can_render(self):
		return "scorm/" in self.path

	# Disk roots tried in order. New packages use private/scorm. Public is retained
	# only as an unmanaged legacy fallback; protect_legacy_scorm_packages relocates
	# it before an entitlement provider can manage access.
	_DISK_ROOTS = ("private", "public")

	def _check_permission(self):
		from lms.lms.permissions import can_access_lesson, get_locked_lessons

		parts = self.path.strip("/").split("/")
		# scorm/<course>/<title>/...
		if len(parts) < 3 or parts[0] != "scorm":
			raise frappe.PermissionError
		course, title = unquote(parts[1]), unquote(parts[2])

		chapter = frappe.db.get_value(
			"Course Chapter",
			{"course": course, "title": title, "is_scorm_package": 1},
			"name",
		)
		if not chapter:
			raise frappe.PermissionError

		# SCORM chapters are created with exactly one lesson (upsert_chapter invariant
		# in api.py). order_by keeps the access check deterministic if that ever changes.
		lesson = frappe.db.get_value("Lesson Reference", {"parent": chapter}, "lesson", order_by="idx asc")
		# can_access_lesson answers "is this course yours or are you enrolled", which is
		# lock-unaware. Sequential courses gate the bytes too, otherwise the SCORM page
		# is a route around the gate that never touches get_lesson.
		if not lesson or not can_access_lesson(lesson) or lesson in get_locked_lessons(course):
			frappe.logger("lms.security").warning(
				"SCORM resource access denied: user=%s path=%s",
				frappe.session.user,
				self.path,
			)
			raise frappe.PermissionError

	def _is_safe_path(self, path):
		resolved = os.path.realpath(path)
		for base in self._DISK_ROOTS:
			scorm_root = os.path.realpath(os.path.join(frappe.local.site_path, base, "scorm"))
			if resolved == scorm_root or resolved.startswith(scorm_root + os.sep):
				return True
		return False

	def _serve_file(self, path):
		f = open(path, "rb")
		response = Response(wrap_file(frappe.local.request.environ, f), direct_passthrough=True)
		response.mimetype = mimetypes.guess_type(path)[0]
		return response

	def render(self):
		self._check_permission()
		# Try private/scorm first (new, gated), then public/scorm (legacy).
		for base in self._DISK_ROOTS:
			response = self._render_from_root(base)
			if response is not None:
				return response

	def _render_from_root(self, base):
		path = os.path.join(frappe.local.site_path, base, self.path.lstrip("/"))

		if not self._is_safe_path(path):
			raise frappe.PermissionError

		extension = os.path.splitext(path)[1]
		if not extension:
			path = f"{path}.html"

		# check if path exists and is actually a file and not a folder
		if os.path.exists(path) and os.path.isfile(path):
			return self._serve_file(path)
		else:
			path = path.replace(".html", "")
			if os.path.exists(path) and os.path.isdir(path):
				index_path = os.path.join(path, "index.html")
				if os.path.exists(index_path):
					return self._serve_file(index_path)
			elif not os.path.exists(path):
				chapter_folder = "/".join(self.path.split("/")[:3])
				chapter_folder_path = os.path.realpath(frappe.get_site_path(base, chapter_folder))
				file = path.split("/")[-1]
				correct_file_path = None

				if not self._is_safe_path(chapter_folder_path):
					raise frappe.PermissionError

				for root, _dirs, files in os.walk(chapter_folder_path):
					if file in files:
						correct_file_path = os.path.join(root, file)
						break

				if correct_file_path and self._is_safe_path(correct_file_path):
					return self._serve_file(correct_file_path)
		return None
