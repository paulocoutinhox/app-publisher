import ast
import tokenize
from io import StringIO
from pathlib import Path


def test_source_layout_and_explicit_style():
    root = Path(__file__).resolve().parents[1] / "src" / "app_publisher"
    modules = sorted(root.rglob("*.py"))
    assert modules
    for path in modules:
        content = path.read_text(encoding="utf-8")
        if path.name == "__init__.py":
            assert content == "", str(path)
            continue
        assert "TYPE_CHECKING" not in content, str(path)
        tree = ast.parse(content, filename=str(path))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        assert len(classes) <= 1, f"Multiple classes in {path}"
        assert not any(
            token.type == tokenize.OP and token.string == ";"
            for token in tokenize.generate_tokens(StringIO(content).readline)
        ), str(path)
