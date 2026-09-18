"""Release gate for the shipped third-party license pack.

Guards the defect that task 22 rev.5 found in `Assert-StagedLicenseDocsMatchGit`:
the gate compared the CRLF->LF-normalised documents as Base64 using PowerShell
`-eq`, which ignores case. The Base64 alphabet shifts by exactly 26 between `A-Z`
and `a-z`, so an aligned single-byte change of +/-26 alters only the *case* of one
character, and `-eq` accepted it. The real occurrence was `THIRD_PARTY.md` offset
105: `n`(0x6E) -> `T`(0x54), which moved only one Base64 character, `u` -> `U`.

The gate now compares with `-ceq`. The end-to-end smoke that proved the fix ran
from `.tmp/` and is sealed with the task 22 evidence rather than tracked, so this
file is the regression guard that lives in the repository: it fails if someone
flips the comparison back to a case-insensitive operator, and it fails loudly
instead of passing quietly if the gate is rewritten past the shapes it knows.

This test never invokes PowerShell, never runs a build and never writes a git
index. The property test below is deliberately self-contained: repository documents
change, and a guard must not drift with them.
"""

import base64
import re
import string
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_portable_zip.ps1"

GATE_FUNCTION = "Assert-StagedLicenseDocsMatchGit"
NORMALISED_VARIABLE = "$indexNormalized"
CASE_SENSITIVE_OPERATORS = ("-ceq", "-cne")
CASE_INSENSITIVE_OPERATORS = ("-eq", "-ne")

# The packaging script tells the next author to "update this gate deliberately in
# the same commit" when the file count changes. A guard test needs the same exit:
# failing loudly here is better than passing over an implementation it no longer
# understands.
UPDATE_THIS_TEST_DELIBERATELY = (
    "门禁实现已变更，请有意识地更新这个守卫测试"
    " (the license gate was rewritten past the shape this guard knows; update this"
    " test deliberately in the same commit)"
)

COMPARISON = re.compile(r"-(c?)(?:eq|ne)\b")


def _extract_gate_function(text):
    """Return the body of GATE_FUNCTION, or None when its declaration is gone."""
    marker = "function " + GATE_FUNCTION + " {"
    start = text.find(marker)
    if start == -1:
        return None
    end = text.find("\nfunction ", start + len(marker))
    if end == -1:
        return text[start:]
    return text[start:end]


def _operators_used_on(body, variable):
    """Return the comparison operators applied to `variable`, comments excluded."""
    operators = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if variable not in line:
            continue
        operators.extend(match.group(0) for match in COMPARISON.finditer(line))
    return operators


class LicenseGateSourceTests(unittest.TestCase):
    def test_license_gate_compares_normalised_base64_case_sensitively(self):
        text = BUILD_SCRIPT.read_text(encoding="utf-8-sig")
        body = _extract_gate_function(text)
        if body is None or NORMALISED_VARIABLE not in body:
            self.fail(UPDATE_THIS_TEST_DELIBERATELY)

        operators = _operators_used_on(body, NORMALISED_VARIABLE)
        if not operators:
            self.fail(UPDATE_THIS_TEST_DELIBERATELY)

        case_insensitive = [op for op in operators if op.lower() in CASE_INSENSITIVE_OPERATORS]
        self.assertEqual(
            [],
            case_insensitive,
            "Base64 比较必须区分大小写，否则单字节篡改会被放行: found "
            + " ".join(case_insensitive)
            + " on "
            + NORMALISED_VARIABLE,
        )
        self.assertTrue(
            any(op.lower() in CASE_SENSITIVE_OPERATORS for op in operators),
            "expected a case-sensitive operator on "
            + NORMALISED_VARIABLE
            + ", found "
            + " ".join(operators),
        )

        # The detector itself has to be able to fail, or the guard is decoration:
        # a synthetic body that flips -ceq back to -eq must be flagged.
        synthetic = "        $equal = ($stagedNormalized -eq $indexNormalized)\n"
        synthetic_flags = [
            op
            for op in _operators_used_on(synthetic, NORMALISED_VARIABLE)
            if op.lower() in CASE_INSENSITIVE_OPERATORS
        ]
        self.assertEqual(["-eq"], synthetic_flags, "detector must flag -eq")


class CaseInsensitiveBase64PropertyTests(unittest.TestCase):
    """Why -eq was unsafe, stated without reading any repository file.

    Real occurrence (task 22 rev.5): `THIRD_PARTY.md` offset 105, `n`(0x6E) ->
    `T`(0x54). The delta is 26, and because that byte sits third in its three-byte
    group only the group's last Base64 character moves -- 46 (`u`) -> 20 (`U`),
    the same letter in the other case. PowerShell -eq, which folds case, called
    the two documents equal.
    """

    ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"

    def test_single_byte_change_can_hide_behind_base64_case(self):
        # head/rest only fix the alignment; `n` -> `T` is the real pair.
        head, rest = b"AB", b"CD\r\nEF\r\n"
        original = head + bytes([0x6E]) + rest
        tampered = head + bytes([0x54]) + rest

        normalised_original = original.replace(b"\r\n", b"\n")
        normalised_tampered = tampered.replace(b"\r\n", b"\n")
        encoded_original = base64.b64encode(normalised_original).decode("ascii")
        encoded_tampered = base64.b64encode(normalised_tampered).decode("ascii")

        # 1. the bytes really differ ...
        self.assertNotEqual(original, tampered)
        self.assertNotEqual(normalised_original, normalised_tampered)
        # 2. ... Base64 compared case-sensitively keeps them apart ...
        self.assertNotEqual(encoded_original, encoded_tampered)
        # 3. ... and case-folded, the way -eq compares, finds them equal -- which
        #    is exactly how the defect let a single-byte tamper through.
        self.assertEqual(encoded_original.casefold(), encoded_tampered.casefold())

        differing = [
            index
            for index, (left, right) in enumerate(zip(encoded_original, encoded_tampered))
            if left != right
        ]
        self.assertEqual(1, len(differing), (encoded_original, encoded_tampered))
        index = differing[0]
        self.assertEqual(
            ("u", "U"), (encoded_original[index], encoded_tampered[index])
        )
        self.assertEqual(
            26,
            abs(
                self.ALPHABET.index(encoded_original[index])
                - self.ALPHABET.index(encoded_tampered[index])
            ),
        )


if __name__ == "__main__":
    unittest.main()
