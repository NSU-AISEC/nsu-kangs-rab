"""결정 0155: /고찰 · /reflect 는 [고찰] 단추와 같은 요청(종류 트리거, 입력 "")이다."""
import unittest

from nsu_kangs_rab.core import inputparse


class ReflectParseTest(unittest.TestCase):
    def test_commands(self):
        for text in ("/고찰", "/reflect"):
            p = inputparse.parse(text)
            self.assertEqual(p.kind, "트리거", text)
        self.assertNotIn("/트리거", inputparse.COMMANDS)


if __name__ == "__main__":
    unittest.main()
