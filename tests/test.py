# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import os
import sys
import unittest

COLLECT_COVERAGE = os.getenv("COVERAGE") == "1"
if COLLECT_COVERAGE:
    try:
        import coverage as _coverage

        # Measure the add-on *package* as it is actually imported. Blender loads
        # the add-on from its install dir (e.g. .../scripts/addons/blenderkit),
        # NOT from this source checkout, so scoping coverage to the source tree
        # records every add-on module as never-executed (0%). Scoping to the
        # package name follows the imported files; codecov.yml `fixes` then maps
        # the install path back to repo paths.
        _cov = _coverage.Coverage(source=[sys.argv[-1]])
        _cov.start()
    except ImportError:
        COLLECT_COVERAGE = False
        print("WARNING: coverage module not available, skipping coverage collection")

import addon_utils

print(f"----- Tests preparation ----- (mode:{os.getenv('TESTS_TYPE', 'all')})")

# loop over all modules because we are getting tripplets in names now (extension mode)
target_addon = sys.argv[-1]
name_match = None
for add in addon_utils.modules():
    if target_addon == add.__name__.split(".")[-1]:
        name_match = add.__name__
        break
if not name_match:
    print(f"FATAL: addon '{sys.argv[-1]}' does not match any available modules")
    sys.exit(1)

result = addon_utils.enable(name_match, default_set=True)
if result is None:
    print(f"FATAL: addon '{name_match}' failed to load")
    sys.exit(1)
print(f"- addon enabled: {name_match}")

# Run the tests from the INSTALLED add-on, imported as ``<pkg>.tests.*`` submodules
# rather than the source checkout. This makes the test files the same ones
# ``coverage`` measures (source=[<pkg>]), so they report real coverage instead of
# 0% - and genuinely dead test code (an uncollected test, an unused helper) shows
# up as uncovered.
#
# We import each module by its fully-qualified name under ``name_match`` (e.g.
# ``blenderkit.tests.test_upload`` in legacy add-on mode, or
# ``bl_ext.user_default.blenderkit_dev_hl.tests.test_upload`` in extension mode)
# instead of using ``TestLoader.discover``. ``discover`` derives the module name
# from the directory path (``blenderkit_dev_hl.tests.test_upload``), which does NOT
# match the package the add-on is actually loaded under in extension mode, so the
# test files' ``from .. import <module>`` relative imports resolve against the wrong
# parent package and fail. Importing under ``name_match`` makes relative imports
# resolve identically in both modes.
import importlib

runner = unittest.TextTestRunner(buffer=False)
suite = unittest.TestSuite()
testLoader = unittest.TestLoader()

_test_modules = [
    "test_init",
    "test_upload",
    "test_paths",
    "test_utils",
    "test_version_compare",
    "test_client_lib",
    "test_search",
    "test_asset_bar_op",
    "test_global_vars",
    "test_clipboard_x11",
    "test_manifest_toml",
    "test_ui_panels",
    "test_registration",
    "test_smoke",
    "test_upload_bg",
    "test_persistent_preferences",
    "test_timer",
    "test_rating_nudge",
    "test_ratings",
    "test_keymap_utils",
    "test_override_extension_draw",
]

for _modname in _test_modules:
    _module = importlib.import_module(f"{name_match}.tests.{_modname}")
    suite.addTests(testLoader.loadTestsFromModule(_module))
print(f"- {len(suite._tests)} tests discovered and loaded\n")

print(f"----- Running tests --------------------------------------------------")
result = runner.run(suite)
if COLLECT_COVERAGE:
    _cov.stop()
    _cov.xml_report(outfile="coverage-python.xml")
errors = len(result.errors)
failures = len(result.failures)
if errors + failures != 0:
    sys.exit(1)
