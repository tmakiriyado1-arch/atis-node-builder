"""
Tests for text normalization
"""
import pytest


class TestNormalization:
    """Test deterministic normalization"""

    def test_lowercase_conversion(self, normalizer):
        """Test conversion to lowercase"""
        assert normalizer.normalize("ZERA") == "zera"
        assert normalizer.normalize("Zimbabwe Energy Regulatory Authority") == "zimbabwe energy regulatory authority"

    def test_whitespace_normalization(self, normalizer):
        """Test multiple spaces normalized to single space"""
        assert normalizer.normalize("Zimbabwe  Energy   Regulatory Authority") == "zimbabwe energy regulatory authority"
        assert normalizer.normalize("  ZERA  ") == "zera"
        assert normalizer.normalize("\t ZERA \n") == "zera"

    def test_punctuation_removal(self, normalizer):
        """Test trailing punctuation removal"""
        assert normalizer.normalize("ZERA.") == "zera"
        assert normalizer.normalize("ZERA!") == "zera"
        assert normalizer.normalize("ZERA?") == "zera"
        assert normalizer.normalize("Zimbabwe Energy Regulatory Authority.") == "zimbabwe energy regulatory authority"

    def test_quote_normalization(self, normalizer):
        """Test various quote styles normalized"""
        assert normalizer.normalize('"ZERA"') == normalizer.normalize("'ZERA'")
        assert normalizer.normalize("\"ZERA\"") == "zera"

    def test_dash_normalization(self, normalizer):
        """Test various dash characters normalized"""
        result1 = normalizer.normalize("Zimbabwe-Energy")
        result2 = normalizer.normalize("Zimbabwe–Energy")  # en-dash
        result3 = normalizer.normalize("Zimbabwe—Energy")  # em-dash
        assert result1 == result2 == result3 == "zimbabwe-energy"

    def test_possessive_removal(self, normalizer):
        """Test possessive 's removal"""
        assert normalizer.normalize("Authority's Name") == "authority name"
        assert normalizer.normalize("ZERA's Status") == "zera status"

    def test_parenthetical_preservation(self, normalizer):
        """Test that parentheticals are preserved but normalized"""
        result = normalizer.normalize("Zimbabwe Energy Regulatory Authority (ZERA)")
        assert "zimbabwe energy regulatory authority" in result
        assert "zera" in result

    def test_empty_and_none_input(self, normalizer):
        """Test handling of empty and None inputs"""
        assert normalizer.normalize("") == ""
        assert normalizer.normalize(None) == ""
        assert normalizer.normalize("   ") == ""

    def test_html_entity_decoding(self, normalizer):
        """Test HTML entity decoding"""
        assert normalizer.normalize("Caf&eacute;") == normalizer.normalize("Café")
        assert normalizer.normalize("&amp;") == "&"


class TestAcronymExtraction:
    """Test acronym detection and extraction"""

    def test_extract_parenthetical_acronym(self, normalizer):
        """Test extraction of acronyms in parentheses"""
        assert normalizer.extract_acronym("Zimbabwe Energy Regulatory Authority (ZERA)") == "ZERA"
        assert normalizer.extract_acronym("ZERA (Zimbabwe Energy Regulatory Authority)") == "ZERA"

    def test_extract_standalone_acronym(self, normalizer):
        """Test extraction of standalone acronyms"""
        assert normalizer.extract_acronym("ZERA") == "ZERA"
        assert normalizer.extract_acronym("The ZERA system") == "ZERA"

    def test_extract_acronym_returns_none(self, normalizer):
        """Test that non-acronyms return None"""
        assert normalizer.extract_acronym("Zimbabwe Energy Regulatory Authority") is None
        assert normalizer.extract_acronym("Some random text") is None

    def test_is_likely_acronym(self, normalizer):
        """Test acronym detection"""
        assert normalizer.is_likely_acronym("ZERA") is True
        assert normalizer.is_likely_acronym("ZER") is True
        assert normalizer.is_likely_acronym("ZE") is True
        assert normalizer.is_likely_acronym("Z") is False
        assert normalizer.is_likely_acronym("Zimbabwe") is False

    def test_generate_acronym(self, normalizer):
        """Test acronym generation from multi-word names"""
        assert normalizer.generate_acronym("Zimbabwe Energy Regulatory Authority") == "ZERA"
        assert normalizer.generate_acronym("Ministry of Energy and Power Development") == "MEPD"
        # Single word returns None
        assert normalizer.generate_acronym("Zimbabwe") is None


class TestNameSplitting:
    """Test splitting of names and acronyms"""

    def test_split_explicit_acronym_suffix(self, normalizer):
        """Test splitting when acronym is in suffix position"""
        name, acronym = normalizer.split_name_and_acronym(
            "Zimbabwe Energy Regulatory Authority (ZERA)"
        )
        assert name == "zimbabwe energy regulatory authority"
        assert acronym == "ZERA"

    def test_split_explicit_acronym_prefix(self, normalizer):
        """Test splitting when acronym is in prefix position"""
        name, acronym = normalizer.split_name_and_acronym(
            "ZERA (Zimbabwe Energy Regulatory Authority)"
        )
        assert name == "zimbabwe energy regulatory authority"
        assert acronym == "ZERA"

    def test_split_name_only(self, normalizer):
        """Test splitting name without acronym"""
        name, acronym = normalizer.split_name_and_acronym(
            "Zimbabwe Energy Regulatory Authority"
        )
        assert name == "zimbabwe energy regulatory authority"
        # Should generate acronym
        assert acronym == "ZERA"

    def test_split_acronym_only(self, normalizer):
        """Test splitting acronym only"""
        name, acronym = normalizer.split_name_and_acronym("ZERA")
        assert acronym == "ZERA"

    def test_split_empty_input(self, normalizer):
        """Test splitting empty input"""
        name, acronym = normalizer.split_name_and_acronym("")
        assert name == ""
        assert acronym is None


class TestNormalizeForMatching:
    """Test aggressive normalization for fuzzy matching"""

    def test_removes_punctuation(self, normalizer):
        """Test that punctuation is removed for matching"""
        result1 = normalizer.normalize_for_matching("Zimbabwe-Energy")
        result2 = normalizer.normalize_for_matching("Zimbabwe Energy")
        # Both should normalize similarly
        assert "zimbabwe" in result1 and "energy" in result1
        assert "zimbabwe" in result2 and "energy" in result2

    def test_removes_quotes(self, normalizer):
        """Test that quotes are removed"""
        result = normalizer.normalize_for_matching('"Zimbabwe"')
        assert result == "zimbabwe"

    def test_preserves_word_boundaries(self, normalizer):
        """Test that word boundaries are preserved"""
        result = normalizer.normalize_for_matching("Zimbabwe Energy Regulatory Authority")
        words = result.split()
        assert len(words) == 4
        assert "zimbabwe" in result
        assert "energy" in result
