---
description: Blender and bundled Python compatibility for add-on code and tests
applyTo: "**/*.py"
---

Add-on runtime code and bundled tests must support Blender 3.0 through the latest
Blender, including Blender 3.0's Python 3.9. Do not use newer standard-library APIs
such as `unittest.TestCase.assertNoLogs`; Ruff's Python target does not check API availability.
Run affected tests in Blender 3.0 and the latest available Blender before completion.
For extension API changes, also cover the original Blender 4.2.0 API: internal
signatures can differ even between patch releases, so test supported signatures
and use capability detection rather than assuming a minor version fixes the API.
