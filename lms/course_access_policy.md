# Course access policy hook

Apps may register one or more dotted Python callables under the
`lms_course_access_policy` hook:

```python
lms_course_access_policy = ["my_app.access.course_access_policy"]
```

Each provider is called with keyword-only arguments `user`, `course`, `action`, and
`context`. Initial actions are `consume` and `progress`. Context is normalized to the
fixed keys `lesson`, `quiz`, and `is_preview`; identifiers are non-empty strings of at
most 140 characters or `None`, and `is_preview` is a boolean or `None`.

A provider returns `None` for unmanaged/no opinion, `True` for no external denial, or
`False` to deny. When every provider returns `None`, the resource remains unmanaged.
Providers compose deny-only: they cannot grant around LMS publication, enrollment,
preview, sequencing, instructor, or moderator rules. Invalid results and provider
failures are logged and deny access. With no providers, native LMS behavior is unchanged.
Results are cached only for the current request and include user, course, action, and
canonical context in the cache key.

## LMS 2.67.1 integration boundaries

- Lesson payloads, individual Course Lesson reads, private lesson media and private SCORM use the existing lesson access gate.
- Course-placed assessments (quizzes, assignments and programming exercises) apply `consume` after native enrollment/sequencing checks. Generic assessment list reads narrow the same native course-member grant. Those course-wide checks have no lesson/quiz context: providers must give their safe course-level answer when context is absent.
- Progress and video-watch writes apply `progress` after native checks. This release already binds explicit progress to `lesson.chapter.course`; that upstream fix is retained rather than reimplemented.
- Quiz follow-up progress is skipped when denied, without rolling back a submission independently authorized through a batch.
- Native staff/authorship and independent batch-assessment channels remain unchanged. Public historical files cannot be protected by Python access hooks.

Enrollment and generic lesson-list constraints can use existing Frappe doc events and permission-query hooks in the extension app. They require no additional LMS contract or frontend changes.
