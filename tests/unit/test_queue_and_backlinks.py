"""Regression tests for queue-backed backlink behavior."""
from app.services.backlink import BacklinkGenerator
from app.services.queue_manager import EntityQueue


def test_queue_deduplicates_normalized_variants():
    queue = EntityQueue()

    assert queue.enqueue("Unknown Entity") is True
    assert queue.enqueue(" unknown  entity. ") is False


def test_backlink_summary_queues_only_unresolved_mentions(registry, resolver, zera_entity):
    queue = EntityQueue()
    generator = BacklinkGenerator(resolver, queue=queue)

    backlinked, resolved = generator.backlink_summary(
        "ZERA worked with Unknown Organization.",
        source_node="NODE-ZERA",
        source_field="summary",
    )

    assert "[[Zimbabwe Energy Regulatory Authority]]" in backlinked
    assert resolved[0][1] == zera_entity.canonical_name
    assert [item.canonical_name for item in queue.list_all()] == ["Unknown Organization"]
    assert queue.list_all()[0].source_node == "NODE-ZERA"