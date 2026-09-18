"""CLI for running the local NORA processing pipeline."""
from __future__ import annotations

import argparse
from pathlib import Path

from app.services.entity_resolution.registry import EntityRegistry
from app.services.entity_resolution.resolver import EntityResolver
from app.services.queue_manager import EntityQueue
from app.processor import NORAProcessor


def build_processor() -> NORAProcessor:
    registry = EntityRegistry()
    resolver = EntityResolver(registry)
    return NORAProcessor(registry=registry, resolver=resolver, queue=EntityQueue())


def cmd_process(args: argparse.Namespace) -> int:
    processor = build_processor()
    result = processor.process_file(args.path)
    print(result)
    return 0


def cmd_process_dir(args: argparse.Namespace) -> int:
    processor = build_processor()
    summary = processor.process_directory(args.directory)
    print(summary)
    return 0


def cmd_nodes(args: argparse.Namespace) -> int:
    processor = build_processor()
    print(processor.list_nodes())
    return 0


def cmd_node(args: argparse.Namespace) -> int:
    processor = build_processor()
    result = processor.get_node(args.node_id)
    print(result)
    return 0


def cmd_relationships(args: argparse.Namespace) -> int:
    processor = build_processor()
    print(processor.list_relationships(args.node_id))
    return 0


def cmd_unresolved(args: argparse.Namespace) -> int:
    processor = build_processor()
    print(processor.list_unresolved())
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    processor = build_processor()
    nodes = processor.list_nodes()
    relationships = []
    for node in nodes:
        relationships.extend(processor.list_relationships(node["node_id"]))
    print({
        "nodes": len(nodes),
        "relationships": len(relationships),
        "unresolved": len(processor.list_unresolved()),
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NORA local processing CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser("process", help="Process a single Markdown source file")
    process_parser.add_argument("path")
    process_parser.set_defaults(func=cmd_process)

    process_dir_parser = subparsers.add_parser("process-dir", help="Process all Markdown files in a directory")
    process_dir_parser.add_argument("directory")
    process_dir_parser.set_defaults(func=cmd_process_dir)

    nodes_parser = subparsers.add_parser("nodes", help="List stored nodes")
    nodes_parser.set_defaults(func=cmd_nodes)

    node_parser = subparsers.add_parser("node", help="Get a single node")
    node_parser.add_argument("node_id")
    node_parser.set_defaults(func=cmd_node)

    relationships_parser = subparsers.add_parser("relationships", help="List relationships for a node")
    relationships_parser.add_argument("node_id")
    relationships_parser.set_defaults(func=cmd_relationships)

    unresolved_parser = subparsers.add_parser("unresolved", help="List unresolved entities")
    unresolved_parser.set_defaults(func=cmd_unresolved)

    status_parser = subparsers.add_parser("status", help="Get NORA status summary")
    status_parser.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
