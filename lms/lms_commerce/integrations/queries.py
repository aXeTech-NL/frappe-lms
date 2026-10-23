import frappe

from lms.lms_commerce.integrations.lms import MAX_REQUESTS, decide_many


def lesson_query_conditions(user: str | None = None) -> str:
	"""Protect generic lesson list reads for learners who also hold an author role.

	LMS's document hook protects individual reads, but Frappe get_list does not call
	it for each result. Compose this Commerce condition with the native LMS SQL;
	never replace its publication, enrollment, preview or instructor rules.
	"""
	from lms.lms.permissions import can_author_course

	if not frappe.db.get_single_value("Commerce Settings", "enabled"):
		return ""
	user = user or frappe.session.user
	courses = frappe.get_all(
		"Commerce Offering",
		filters={"enabled": 1, "target_doctype": "LMS Course"},
		pluck="target_name",
	)
	denied = []
	for start in range(0, len(courses), MAX_REQUESTS):
		page = courses[start : start + MAX_REQUESTS]
		decisions = decide_many(
			user=user,
			requests=[
				{"key": course, "resource_type": "course", "resource_name": course, "action": "consume"}
				for course in page
			],
		)
		for course in page:
			decision = decisions[course]
			if decision.get("handled") is False or decision.get("allowed") is True:
				continue
			if not can_author_course(course, user=user):
				denied.append(course)
	if not denied:
		return ""

	# chapter.course is authoritative; Course Lesson.course can be a stale mirror.
	lesson = frappe.qb.DocType("Course Lesson")
	chapter = frappe.qb.DocType("Course Chapter")
	blocked = frappe.qb.from_(chapter).select(chapter.name).where(chapter.course.isin(denied))
	return lesson.chapter.notin(blocked).get_sql(
		with_namespace=True, quote_char="`" if frappe.db.db_type == "mariadb" else '"'
	)
