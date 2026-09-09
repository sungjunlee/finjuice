"""Round-trip YAML configuration for exact decimal scalar lexemes."""

from __future__ import annotations

from typing import Any

from ruamel.yaml import YAML

_FLOAT_TAG = "tag:yaml.org,2002:float"


class ExactFloatLexeme(str):
    """A YAML float token retained as its original decimal text."""


def configure_exact_floats(yaml: YAML) -> YAML:
    """Preserve YAML float tokens without a binary-float conversion."""

    def construct_exact_float(constructor: Any, node: Any) -> ExactFloatLexeme:
        del constructor
        return ExactFloatLexeme(node.value)

    def represent_exact_float(representer: Any, value: ExactFloatLexeme) -> Any:
        return representer.represent_scalar(_FLOAT_TAG, str(value))

    yaml.constructor.add_constructor(_FLOAT_TAG, construct_exact_float)
    yaml.representer.add_representer(ExactFloatLexeme, represent_exact_float)
    return yaml


__all__ = ["ExactFloatLexeme", "configure_exact_floats"]
