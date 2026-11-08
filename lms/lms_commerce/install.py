"""Install the fork's internal Commerce module, without a separate app."""

import frappe
from frappe import _

MODULE = "LMS Commerce"
DOCTYPES = (
	"Commerce Settings",
	"Commerce Tier",
	"Commerce Offering",
	"Commerce Entitlement",
	"Commerce Order",
)
LMS_POLICY_PROVIDER = "lms.lms_commerce.integrations.lms.course_access_policy"


def validate_lms_policy_capability():
	from lms.lms.access_policy import POLICY_ACTIONS, POLICY_HOOK

	if POLICY_HOOK != "lms_course_access_policy" or set(POLICY_ACTIONS) != {"consume", "progress"}:
		frappe.throw(_("The LMS course access policy contract is incompatible."))


def before_migrate():
	if "frappe_lms_commerce" in frappe.get_installed_apps():
		frappe.throw(
			_(
				"This LMS fork includes Commerce. The legacy standalone Commerce app cannot be installed on the same site. Use a fresh site; do not uninstall existing data without a separate migration plan."
			)
		)


def after_sync():
	from lms.lms.utils import get_lms_route

	before_migrate()
	validate_lms_policy_capability()
	create_roles()
	if frappe.db.get_single_value("Commerce Settings", "provider_path") != LMS_POLICY_PROVIDER:
		frappe.db.set_single_value("Commerce Settings", "provider_path", LMS_POLICY_PROVIDER)
	if frappe.db.get_single_value("Commerce Settings", "portal_path") != get_lms_route():
		frappe.db.set_single_value("Commerce Settings", "portal_path", get_lms_route())
	update_workspace()


def create_roles():
	for name in ("Commerce Manager", "Commerce Viewer"):
		if not frappe.db.exists("Role", name):
			frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def update_workspace():
	"""Honor custom LMS base paths without replacing site-edited board content."""
	from lms.lms.utils import get_lms_route

	for name in frappe.get_all("Workspace", filters={"module": MODULE}, pluck="name"):
		workspace = frappe.get_doc("Workspace", name)
		changed = False
		for row in workspace.shortcuts:
			if (
				row.label == "Course Catalog"
				and row.url == "/lms/courses"
				and row.url != get_lms_route("courses")
			):
				row.url = get_lms_route("courses")
				changed = True
		if changed:
			workspace.save(ignore_permissions=True)
