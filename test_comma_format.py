"""
모달 폼 숫자 쉼표 포맷팅 수정 검증
1. HTML — type="text" + inputmode + oninput 확인
2. JS — _fmtInput / _parseNum 함수 존재 확인
3. JS — openEditModal에서 toLocaleString('ko-KR') 사용 확인
4. JS — saveStock에서 _parseNum 헬퍼 사용 확인
5. _fmtInput 로직 Python으로 재현해 수치 검증
"""
import re
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

BOT_PATH = os.path.join(os.path.dirname(__file__), "combined_bot.py")

with open(BOT_PATH, encoding="utf-8") as f:
    SRC = f.read()


class TestHtmlInputFields(unittest.TestCase):
    """HTML 입력 필드 type/inputmode/oninput 확인"""

    def test_f_qty_is_text(self):
        self.assertIn('id="f-qty"', SRC)
        # type="text" 로 바뀌어야 함
        m = re.search(r'id="f-qty"[^>]*type="([^"]+)"', SRC)
        if not m:
            m = re.search(r'type="([^"]+)"[^>]*id="f-qty"', SRC)
        self.assertIsNotNone(m, "f-qty type 속성을 찾지 못함")
        self.assertEqual(m.group(1), "text", "f-qty는 type=text여야 함")

    def test_f_avg_is_text(self):
        m = re.search(r'id="f-avg"[^>]*type="([^"]+)"', SRC)
        if not m:
            m = re.search(r'type="([^"]+)"[^>]*id="f-avg"', SRC)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "text")

    def test_f_cash_is_text(self):
        m = re.search(r'id="f-cash"[^>]*type="([^"]+)"', SRC)
        if not m:
            m = re.search(r'type="([^"]+)"[^>]*id="f-cash"', SRC)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "text")

    def test_f_qty_inputmode_numeric(self):
        self.assertIn("inputmode=\"numeric\"", SRC)

    def test_f_avg_inputmode_decimal(self):
        # f-avg와 f-cash 모두 decimal
        self.assertGreaterEqual(SRC.count('inputmode="decimal"'), 2)

    def test_f_qty_oninput_fmt_int(self):
        self.assertIn("_fmtInput(this,'int')", SRC)

    def test_f_avg_oninput_fmt_dec(self):
        self.assertGreaterEqual(SRC.count("_fmtInput(this,'dec')"), 2)

    def test_no_type_number_in_form_inputs(self):
        """f-qty / f-avg / f-cash 에 type="number" 가 남아있으면 안 됨"""
        for fid in ("f-qty", "f-avg", "f-cash"):
            # 해당 id 주변 태그만 추출
            pattern = rf'<input[^>]*id="{fid}"[^>]*>'
            matches = re.findall(pattern, SRC)
            for tag in matches:
                self.assertNotIn('type="number"', tag,
                    f'{fid} 에 type="number"가 남아있음: {tag}')


class TestJsFunctions(unittest.TestCase):
    """JS 함수 존재 및 핵심 로직 확인"""

    def test_fmtInput_defined(self):
        self.assertIn("function _fmtInput(el, mode)", SRC)

    def test_parseNum_defined(self):
        self.assertIn("function _parseNum(id)", SRC)

    def test_parseNum_removes_comma(self):
        self.assertIn(".replace(/,/g, '')", SRC)

    def test_fmtInput_uses_comma_regex(self):
        # 쉼표 삽입 정규식
        self.assertIn(r"\B(?=(\d", SRC)

    def test_fmtInput_int_removes_dot(self):
        self.assertIn("raw.replace(/\\./g, '')", SRC)

    def test_openEditModal_uses_toLocaleString(self):
        self.assertIn("toLocaleString('ko-KR')", SRC)
        # 3번 이상 사용 (qty, avg, cash)
        self.assertGreaterEqual(SRC.count("toLocaleString('ko-KR')"), 3)

    def test_saveStock_uses_parseNum_cash(self):
        self.assertIn("_parseNum('f-cash')", SRC)

    def test_saveStock_uses_parseNum_qty(self):
        self.assertIn("_parseNum('f-qty')", SRC)

    def test_saveStock_uses_parseNum_avg(self):
        self.assertIn("_parseNum('f-avg')", SRC)

    def test_saveStock_no_parseFloat_for_inputs(self):
        """saveStock에 parseFloat(getElementById('f-qty'/'f-avg'/'f-cash')) 가 없어야 함"""
        for fid in ("f-qty", "f-avg", "f-cash"):
            pattern = rf"parseFloat\(document\.getElementById\('{fid}'\)"
            self.assertNotIn(
                f"parseFloat(document.getElementById('{fid}')", SRC,
                f"saveStock에 parseFloat(getElementById('{fid}')) 가 남아있음"
            )


class TestFmtInputLogic(unittest.TestCase):
    """_fmtInput 핵심 로직을 Python으로 재현해 수치 검증"""

    def _fmt(self, value: str, mode: str) -> str:
        raw = re.sub(r'[^0-9.]', '', value)
        if mode == 'int':
            raw = raw.replace('.', '')
        parts = raw.split('.')
        int_part = parts[0] if parts[0] else ''
        dec_part = ('.' + ''.join(parts[1:])) if len(parts) > 1 else ''
        int_part = re.sub(r'\B(?=(\d{3})+(?!\d))', ',', int_part)
        return int_part + dec_part

    def _parse(self, value: str) -> float:
        return float(value.replace(',', '')) if value.replace(',', '').replace('.', '') else 0.0

    def test_int_1234567(self):
        self.assertEqual(self._fmt('1234567', 'int'), '1,234,567')

    def test_int_no_dot(self):
        # int 모드: 점 포함 모든 점 제거 → '1234.5' → '12345' → '12,345'
        self.assertEqual(self._fmt('1234.5', 'int'), '12,345')

    def test_dec_with_dot(self):
        self.assertEqual(self._fmt('1234567.89', 'dec'), '1,234,567.89')

    def test_dec_dot_only(self):
        self.assertEqual(self._fmt('1234.', 'dec'), '1,234.')

    def test_small_number(self):
        self.assertEqual(self._fmt('999', 'int'), '999')

    def test_empty_string(self):
        self.assertEqual(self._fmt('', 'int'), '')

    def test_parse_removes_comma(self):
        self.assertAlmostEqual(self._parse('1,234,567'), 1234567)

    def test_parse_decimal(self):
        self.assertAlmostEqual(self._parse('49,926.15'), 49926.15)

    def test_parse_empty(self):
        self.assertEqual(self._parse(''), 0.0)

    def test_roundtrip_qty(self):
        """1300 → 포맷 → 파싱 → 1300"""
        formatted = self._fmt('1300', 'int')
        self.assertEqual(self._parse(formatted), 1300)

    def test_roundtrip_avg(self):
        """49696.15 → 포맷 → 파싱 → 49696.15"""
        formatted = self._fmt('49696.15', 'dec')
        self.assertAlmostEqual(self._parse(formatted), 49696.15, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
