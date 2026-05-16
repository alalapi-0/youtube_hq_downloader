from __future__ import annotations

import unittest


class ConsoleChecksImport(unittest.TestCase):
    def test_import_product_console_module(self) -> None:
        import src.console.app as app  # noqa: F401

        self.assertTrue(hasattr(app, "main"))


if __name__ == "__main__":
    unittest.main()
