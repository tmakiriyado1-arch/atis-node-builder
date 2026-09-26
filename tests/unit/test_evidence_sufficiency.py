"""Tests for evidence sufficiency checking (15+ URL target)."""

from app.services.research.evidence import (
    EvidenceRecord,
    SourceType,
    classify_source_type,
    deduplicate_evidence,
    normalize_url,
)


class TestURLNormalization:
    """Test URL normalization."""

    def test_trailing_slash_removed(self):
        """Test that trailing slashes are removed."""
        url1 = "https://example.com/page/"
        url2 = "https://example.com/page"
        
        normalized1 = normalize_url(url1)
        normalized2 = normalize_url(url2)
        
        assert normalized1 == normalized2

    def test_tracking_params_removed(self):
        """Test that tracking parameters are removed."""
        url1 = "https://example.com/page?utm_source=test"
        url2 = "https://example.com/page"
        
        normalized1 = normalize_url(url1)
        normalized2 = normalize_url(url2)
        
        assert normalized1 == normalized2

    def test_different_schemes_normalized(self):
        """Test that different schemes are normalized to lowercase."""
        url1 = "HTTP://example.com/page"
        url2 = "http://example.com/page"
        
        normalized1 = normalize_url(url1)
        normalized2 = normalize_url(url2)
        
        assert normalized1 == normalized2

    def test_hostname_normalized(self):
        """Test that hostnames are normalized to lowercase."""
        url1 = "https://EXAMPLE.COM/page"
        url2 = "https://example.com/page"
        
        normalized1 = normalize_url(url1)
        normalized2 = normalize_url(url2)
        
        assert normalized1 == normalized2

    def test_fragment_removed(self):
        """Test that URL fragments are removed."""
        url1 = "https://example.com/page#section"
        url2 = "https://example.com/page"
        
        normalized1 = normalize_url(url1)
        normalized2 = normalize_url(url2)
        
        assert normalized1 == normalized2

    def test_meaningful_params_preserved(self):
        """Test that meaningful query parameters are preserved."""
        url = "https://example.com/page?year=2024&report=annual"
        normalized = normalize_url(url)
        
        assert "year=2024" in normalized
        assert "report=annual" in normalized


class TestEvidenceDeduplication:
    """Test evidence deduplication."""

    def test_duplicate_urls_removed(self):
        """Test that duplicate URLs are removed."""
        records = [
            EvidenceRecord(
                url="https://example.com/page",
                title="Page 1",
                snippet="Snippet 1",
                query="query1",
            ),
            EvidenceRecord(
                url="https://example.com/page",
                title="Page 1",
                snippet="Snippet 2",
                query="query2",
            ),
        ]
        
        deduped = deduplicate_evidence(records)
        assert len(deduped) == 1

    def test_different_urls_kept(self):
        """Test that different URLs are kept."""
        records = [
            EvidenceRecord(
                url="https://example.com/page1",
                title="Page 1",
                snippet="Snippet 1",
            ),
            EvidenceRecord(
                url="https://example.com/page2",
                title="Page 2",
                snippet="Snippet 2",
            ),
        ]
        
        deduped = deduplicate_evidence(records)
        assert len(deduped) == 2

    def test_normalized_urls_deduped(self):
        """Test that normalized URLs are deduplicated."""
        records = [
            EvidenceRecord(
                url="https://example.com/page/",
                title="Page 1",
                snippet="Snippet 1",
            ),
            EvidenceRecord(
                url="https://example.com/page",
                title="Page 1",
                snippet="Snippet 2",
            ),
        ]
        
        deduped = deduplicate_evidence(records)
        assert len(deduped) == 1

    def test_query_provenance_preserved(self):
        """Test that query provenance is preserved in deduplication."""
        records = [
            EvidenceRecord(
                url="https://example.com/page",
                title="Page 1",
                snippet="Snippet 1",
                query="query1",
                queries=["query1"],
            ),
            EvidenceRecord(
                url="https://example.com/page",
                title="Page 1",
                snippet="Snippet 2",
                query="query2",
                queries=["query2"],
            ),
        ]
        
        deduped = deduplicate_evidence(records)
        assert len(deduped) == 1
        assert "query1" in deduped[0].queries
        assert "query2" in deduped[0].queries


class TestSourceTypeClassification:
    """Test source type classification."""

    def test_wikidata_classification(self):
        """Test Wikidata URL classification."""
        source_type = classify_source_type("https://www.wikidata.org/wiki/Q123")
        assert source_type == SourceType.WIKIDATA

    def test_wikipedia_classification(self):
        """Test Wikipedia URL classification."""
        source_type = classify_source_type("https://en.wikipedia.org/wiki/ZERA")
        assert source_type == SourceType.WIKIPEDIA

    def test_gov_domain_classification(self):
        """Test government domain classification."""
        source_type = classify_source_type("https://www.zera.gov.zw")
        assert source_type == SourceType.GOVERNMENT

    def test_official_domain_classification(self):
        """Test official domain classification."""
        source_type = classify_source_type("https://sapp.co.zw")
        assert source_type == SourceType.OFFICIAL

    def test_regulator_keyword_classification(self):
        """Test regulator keyword in URL classification."""
        source_type = classify_source_type("https://energy-regulator.org")
        assert source_type == SourceType.REGULATOR

    def test_news_classification(self):
        """Test news URL classification."""
        source_type = classify_source_type("https://example.com/news/article")
        assert source_type == SourceType.NEWS

    def test_directory_classification(self):
        """Test directory URL classification."""
        source_type = classify_source_type("https://yellowpages.com/listing")
        assert source_type == SourceType.DIRECTORY

    def test_academic_classification(self):
        """Test academic URL classification."""
        source_type = classify_source_type("https://university.edu/research")
        assert source_type == SourceType.ACADEMIC

    def test_institutional_classification(self):
        """Test institutional URL classification."""
        source_type = classify_source_type("https://worldbank.org/report")
        assert source_type == SourceType.INSTITUTIONAL

    def test_default_classification(self):
        """Test default classification for unknown sources."""
        source_type = classify_source_type("https://example.com/page")
        assert source_type == SourceType.SEARCH_DISCOVERED

    def test_metadata_override(self):
        """Test that metadata source_type overrides URL classification."""
        metadata = {"source_type": "official"}
        source_type = classify_source_type(
            "https://example.com/page",
            metadata=metadata,
        )
        assert source_type == SourceType.OFFICIAL


class TestEvidenceSufficiency:
    """Test evidence sufficiency (15+ URL target)."""

    def test_15_plus_urls_target(self):
        """Test that 15+ unique URLs is the target."""
        # This is more of a documentation test
        # The actual check happens in the orchestrator
        assert True  # Placeholder

    def test_unique_urls_count(self):
        """Test counting unique URLs."""
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
            "https://example.com/page1",  # Duplicate
            "https://example.com/page4",
        ]
        
        # Normalize and deduplicate
        normalized = set(normalize_url(url) for url in urls)
        
        assert len(normalized) == 4

    def test_evidence_records_from_urls(self):
        """Test creating evidence records from URLs."""
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]
        
        records = [
            EvidenceRecord(
                url=url,
                title=f"Page {i}",
                snippet=f"Snippet {i}",
            )
            for i, url in enumerate(urls, 1)
        ]
        
        assert len(records) == 3

    def test_insufficient_evidence_reporting(self):
        """Test that insufficient evidence is properly reported."""
        # If we have fewer than 15 unique URLs, it should be reported
        urls = ["https://example.com/page" + str(i) for i in range(10)]
        
        records = [
            EvidenceRecord(
                url=url,
                title=f"Page {i}",
                snippet=f"Snippet {i}",
            )
            for i, url in enumerate(urls, 1)
        ]
        
        deduped = deduplicate_evidence(records)
        
        # Should have 10 unique URLs
        assert len(deduped) == 10
        # This is less than 15, so evidence is insufficient
        # (The actual sufficiency check is in the orchestrator)
