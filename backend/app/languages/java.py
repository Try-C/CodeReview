"""Java Tree-sitter adapter."""

from tree_sitter import Node

from app.languages.schemas import RelationType, SymbolRef
from app.languages.tree_sitter_adapter import (
    Definition,
    TreeSitterLanguageAdapter,
    node_text,
    owning_definition,
    walk,
)


class JavaLanguageAdapter(TreeSitterLanguageAdapter):
    language = "java"
    extensions = frozenset({".java"})
    definition_types = frozenset(
        {
            "annotation_type_declaration",
            "class_declaration",
            "constructor_declaration",
            "enum_declaration",
            "interface_declaration",
            "method_declaration",
            "record_declaration",
        }
    )

    def risk_hints(self) -> tuple[str, ...]:
        return (
            "Runtime.exec",
            "ProcessBuilder",
            "Statement.execute",
            "ObjectInputStream",
            "SpelExpressionParser",
        )

    def normalize_query(self, query: str) -> str:
        return query.strip().replace("#", ".")

    def _symbol_type(self, node: Node, parent: Definition | None) -> str:
        del parent
        return {
            "annotation_type_declaration": "annotation",
            "class_declaration": "class",
            "constructor_declaration": "constructor",
            "enum_declaration": "enum",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "record_declaration": "record",
        }[node.type]

    def _signature(self, node: Node, source: bytes) -> str:
        body = node.child_by_field_name("body")
        end_byte = body.start_byte if body is not None else node.end_byte
        return source[node.start_byte : end_byte].decode("utf-8").rstrip(" {\r\n")

    def _imports(self, root: Node, source: bytes) -> tuple[str, ...]:
        imports: list[str] = []
        for node in walk(root):
            if node.type != "import_declaration":
                continue
            value = node_text(node, source).removeprefix("import ").removesuffix(";").strip()
            value = value.removeprefix("static ").strip()
            if value:
                imports.append(value)
        return tuple(dict.fromkeys(imports))

    def _references(
        self,
        file_path: str,
        root: Node,
        source: bytes,
        definitions: tuple[Definition, ...],
        imports: tuple[str, ...],
    ) -> tuple[SymbolRef, ...]:
        references = [
            SymbolRef(
                source_symbol="<compilation_unit>",
                target_symbol=target,
                source_file=file_path,
                relation_type="import",
                confidence=0.95,
                resolution_status="external",
            )
            for target in imports
        ]
        for node in walk(root):
            owner = owning_definition(node, definitions)
            if node.type == "method_invocation" and owner is not None:
                name = node.child_by_field_name("name")
                if name is None:
                    continue
                target = node_text(name, source)
                object_node = node.child_by_field_name("object")
                if object_node is not None:
                    target = f"{node_text(object_node, source)}.{target}"
                references.append(
                    SymbolRef(
                        source_symbol=owner.qualified_name,
                        target_symbol=target,
                        source_file=file_path,
                        relation_type="call",
                        confidence=0.75,
                    )
                )
            elif node.type in {
                "annotation_type_declaration",
                "class_declaration",
                "enum_declaration",
                "interface_declaration",
                "record_declaration",
            }:
                definition = next((item for item in definitions if item.node == node), None)
                if definition is None:
                    continue
                type_relations: tuple[tuple[str, RelationType], ...] = (
                    ("superclass", "extend"),
                    ("interfaces", "implement"),
                )
                for field_name, relation_type in type_relations:
                    clause = node.child_by_field_name(field_name)
                    if clause is None:
                        continue
                    for target_node in _type_targets(clause):
                        references.append(
                            SymbolRef(
                                source_symbol=definition.qualified_name,
                                target_symbol=node_text(target_node, source),
                                source_file=file_path,
                                relation_type=relation_type,
                                confidence=0.85,
                            )
                        )
                extends_interfaces = next(
                    (child for child in node.named_children if child.type == "extends_interfaces"),
                    None,
                )
                if extends_interfaces is not None:
                    for target_node in _type_targets(extends_interfaces):
                        references.append(
                            SymbolRef(
                                source_symbol=definition.qualified_name,
                                target_symbol=node_text(target_node, source),
                                source_file=file_path,
                                relation_type="extend",
                                confidence=0.85,
                            )
                        )
        return _unique_references(references)


def _type_targets(clause: Node) -> tuple[Node, ...]:
    direct = tuple(child for child in clause.named_children if child.type != "type_list")
    if direct:
        return direct
    return tuple(
        grandchild for child in clause.named_children for grandchild in child.named_children
    )


def _unique_references(references: list[SymbolRef]) -> tuple[SymbolRef, ...]:
    unique: dict[tuple[str, str, str], SymbolRef] = {}
    for reference in references:
        key = (
            reference.source_symbol,
            reference.target_symbol,
            reference.relation_type,
        )
        unique.setdefault(key, reference)
    return tuple(unique.values())
