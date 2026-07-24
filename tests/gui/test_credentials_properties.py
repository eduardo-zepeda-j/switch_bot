# Feature: gui-redesign, Properties 2 & 3: Secret obfuscation round-trip, Model display text
"""Property-based tests para credentials — Ofuscación de secretos y formato ModelInfo.

**Validates: Requirements 1.5, 2.3**

Property 2: Secret obfuscation round-trip — For any valid string (non-empty,
printable characters), applying obfuscate_secret followed by deobfuscate_secret
SHALL produce a string identical to the original input.

Property 3: Model display text formatting — For any ModelInfo instance with a
non-empty name and an optional size_gb value, display_text() SHALL contain the
model name. If size_gb is not None, display_text() SHALL also contain the size
formatted as "(X.X GB)".
"""

from __future__ import annotations

import string

from hypothesis import given, settings
from hypothesis import strategies as st

from switch_bot.gui.credentials import ModelInfo, deobfuscate_secret, obfuscate_secret

# Strategy for printable characters (letters, digits, punctuation, whitespace excluding \r\n etc.)
printable_chars = string.ascii_letters + string.digits + string.punctuation + " "


class TestProperty2SecretObfuscationRoundTrip:
    """Property 2: Secret obfuscation round-trip.

    **Validates: Requirements 1.5**

    For any valid string (non-empty, printable characters), applying
    obfuscate_secret followed by deobfuscate_secret SHALL produce a string
    identical to the original input.
    """

    @given(secret=st.text(min_size=1, alphabet=printable_chars))
    @settings(max_examples=100)
    def test_obfuscate_deobfuscate_roundtrip(self, secret: str) -> None:
        """FOR ALL non-empty printable strings, deobfuscate(obfuscate(s)) == s.

        **Validates: Requirements 1.5**
        """
        obfuscated = obfuscate_secret(secret)
        result = deobfuscate_secret(obfuscated)
        assert result == secret, (
            f"Round-trip failed: original={secret!r}, obfuscated={obfuscated!r}, "
            f"deobfuscated={result!r}"
        )

    @given(secret=st.text(min_size=1, alphabet=printable_chars))
    @settings(max_examples=100)
    def test_obfuscated_differs_from_original(self, secret: str) -> None:
        """FOR ALL non-empty printable strings, obfuscate(s) != s.

        Ensures obfuscation actually transforms the input (not a no-op).

        **Validates: Requirements 1.5**
        """
        obfuscated = obfuscate_secret(secret)
        # For single-char palindromes that are also valid base64,
        # the obfuscated form should still differ due to base64 encoding
        assert obfuscated != secret


class TestProperty3ModelDisplayTextFormatting:
    """Property 3: Model display text formatting.

    **Validates: Requirements 2.3**

    For any ModelInfo instance with a non-empty name and an optional size_gb
    value, display_text() SHALL contain the model name. If size_gb is not None,
    display_text() SHALL also contain the size formatted as "(X.X GB)".
    """

    @given(
        model=st.builds(
            ModelInfo,
            id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "P"))),
            name=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("L", "N", "S", "Z"))),
            size_gb=st.one_of(st.none(), st.floats(min_value=0.1, max_value=999.9, allow_nan=False, allow_infinity=False)),
            model_type=st.sampled_from(["embedding", "llm"]),
        )
    )
    @settings(max_examples=100)
    def test_display_text_contains_name(self, model: ModelInfo) -> None:
        """FOR ALL ModelInfo instances, display_text() contains the model name.

        **Validates: Requirements 2.3**
        """
        text = model.display_text()
        assert model.name in text, (
            f"display_text() does not contain model name: "
            f"name={model.name!r}, display_text={text!r}"
        )

    @given(
        model=st.builds(
            ModelInfo,
            id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "P"))),
            name=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("L", "N", "S", "Z"))),
            size_gb=st.floats(min_value=0.1, max_value=999.9, allow_nan=False, allow_infinity=False),
            model_type=st.sampled_from(["embedding", "llm"]),
        )
    )
    @settings(max_examples=100)
    def test_display_text_contains_size_when_present(self, model: ModelInfo) -> None:
        """FOR ALL ModelInfo with size_gb not None, display_text() contains formatted size.

        **Validates: Requirements 2.3**
        """
        text = model.display_text()
        expected_size = f"({model.size_gb:.1f} GB)"
        assert expected_size in text, (
            f"display_text() does not contain formatted size: "
            f"expected={expected_size!r}, display_text={text!r}"
        )

    @given(
        model=st.builds(
            ModelInfo,
            id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "P"))),
            name=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("L", "N", "S", "Z"))),
            size_gb=st.none(),
            model_type=st.sampled_from(["embedding", "llm"]),
        )
    )
    @settings(max_examples=100)
    def test_display_text_equals_name_when_no_size(self, model: ModelInfo) -> None:
        """FOR ALL ModelInfo with size_gb=None, display_text() equals the model name.

        **Validates: Requirements 2.3**
        """
        text = model.display_text()
        assert text == model.name, (
            f"display_text() should equal name when size_gb is None: "
            f"name={model.name!r}, display_text={text!r}"
        )
