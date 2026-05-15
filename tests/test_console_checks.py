from __future__ import annotations

import unittest


class ConsoleChecksImport(unittest.TestCase):
    def test_import_console_checks_module(self) -> None:
        import src.console_checks as cc  # noqa: F401

        self.assertTrue(hasattr(cc, "run_full_env_check"))


if __name__ == "__main__":
    unittest.main()
