import unittest

from checkin import VERSION, lookup


class CheckinTest(unittest.TestCase):
    def test_known_flight(self):
        self.assertEqual(lookup("ac123")["counters"], "12-18")

    def test_unknown_flight(self):
        self.assertIsNone(lookup("ZZ000"))

    def test_version_is_reported(self):
        self.assertEqual(lookup("WS456")["version"], VERSION)


if __name__ == "__main__":
    unittest.main()
