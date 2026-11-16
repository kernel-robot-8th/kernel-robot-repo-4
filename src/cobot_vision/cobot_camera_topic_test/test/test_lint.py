# Copyright 2026 Pinky_Team4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run the repository's Python style and license checks when ament is available."""

from pathlib import Path
import unittest


class TestLint(unittest.TestCase):
    """Check only this standalone test package."""

    def test_flake8(self):
        """Apply ament's Python lint settings."""
        try:
            from ament_flake8.main import main_with_errors
        except ImportError:
            self.skipTest('ament_flake8 is not installed')
        result, errors = main_with_errors(argv=[str(Path(__file__).resolve().parents[1])])
        self.assertEqual(result, 0, '\n'.join(errors))

    def test_pep257(self):
        """Apply ament's docstring checks."""
        try:
            from ament_pep257.main import main
        except ImportError:
            self.skipTest('ament_pep257 is not installed')
        self.assertEqual(main(argv=[str(Path(__file__).resolve().parents[1])]), 0)

    def test_copyright(self):
        """Check package copyright and Apache license headers."""
        try:
            from ament_copyright.main import main
        except ImportError:
            self.skipTest('ament_copyright is not installed')
        self.assertEqual(main(argv=[str(Path(__file__).resolve().parents[1])]), 0)
