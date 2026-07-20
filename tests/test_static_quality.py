"""Standard-library static checks for split contracts and i18n policy."""

from __future__ import annotations

import unittest

from tools.check_i18n import audit_errors
from tools.check_split_contracts import contract_errors


class StaticQualityTests(unittest.TestCase):
    def test_split_base_contracts_are_synchronized(self) -> None:
        self.assertEqual(contract_errors(), [])

    def test_i18n_debt_does_not_increase(self) -> None:
        self.assertEqual(audit_errors(), [])


if __name__ == "__main__":
    unittest.main()
