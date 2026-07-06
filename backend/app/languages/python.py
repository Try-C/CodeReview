"""Python Tree-sitter adapter."""

from tree_sitter import Node

from app.languages.schemas import SymbolRef
from app.languages.tree_sitter_adapter import (
    Definition,
    TreeSitterLanguageAdapter,
    node_text,
    owning_definition,
    walk,
)


class PythonLanguageAdapter(TreeSitterLanguageAdapter):
    language = "python"
    extensions = frozenset({".py", ".pyi"})
    definition_types = frozenset({"class_definition", "function_definition"})

    def risk_hints(self) -> tuple[str, ...]:
        return (
            "eval",
            "exec",
            "pickle.loads",
            "subprocess",
            "shell=True",
            "yaml.load",
        )

    def normalize_query(self, query: str) -> str:
        return query.strip().replace("::", ".")

    def _symbol_type(self, node: Node, parent: Definition | None) -> str:
        if node.type == "class_definition":
            return "class"
        return "method" if parent and parent.symbol_type == "class" else "function"

    def _signature(self, node: Node, source: bytes) -> str:
        body = node.child_by_field_name("body")
        end_byte = body.start_byte if body is not None else node.end_byte
        return source[node.start_byte : end_byte].decode("utf-8").rstrip(" :\r\n")

    def _imports(self, root: Node, source: bytes) -> tuple[str, ...]:
        imports: list[str] = []
        for node in walk(root):
            text = node_text(node, source)
            if node.type == "import_statement":
                imports.extend(
                    part.strip().split(" as ", maxsplit=1)[0]
                    for part in text.removeprefix("import ").split(",")
                )
            elif node.type == "import_from_statement":
                module = node.child_by_field_name("module_name")
                if module is not None:
                    imports.append(node_text(module, source))
                else:
                    prefix = text.removeprefix("from ").split(" import ", maxsplit=1)[0]
                    if prefix:
                        imports.append(prefix.strip())
        return tuple(dict.fromkeys(value for value in imports if value))

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
                source_symbol="<module>",
                target_symbol=target,
                source_file=file_path,
                relation_type="import",
                confidence=0.95,
                resolution_status="external",
            )
            for target in imports
        ]
        for node in walk(root):
            if node.type == "call":
                function = node.child_by_field_name("function")
                owner = owning_definition(node, definitions)
                if function is not None and owner is not None:
                    references.append(
                        SymbolRef(
                            source_symbol=owner.qualified_name,
                            target_symbol=node_text(function, source),
                            source_file=file_path,
                            relation_type="call",
                            confidence=0.75,
                        )
                    )
            elif node.type == "class_definition":
                owner = next((item for item in definitions if item.node == node), None)
                superclasses = node.child_by_field_name("superclasses")
                if owner is not None and superclasses is not None:
                    for child in (
                        child
                        for child in superclasses.named_children
                        if child.type != "keyword_argument"
                    ):
                        references.append(
                            SymbolRef(
                                source_symbol=owner.qualified_name,
                                target_symbol=node_text(child, source),
                                source_file=file_path,
                                relation_type="extend",
                                confidence=0.8,
                            )
                        )
        return _unique_references(references)


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
