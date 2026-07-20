from __future__ import annotations

import datetime
import hashlib
import io
import json
import math
import re
import token
import tokenize
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FormulaSourceType = Literal["asset", "index"]
FormulaStatus = Literal["draft", "active", "retired"]
FormulaAlignmentPolicy = Literal["exact", "asof"]
FormulaMissingDataPolicy = Literal["drop", "fail"]


def _utc(value: datetime.datetime | str | pd.Timestamp | None) -> datetime.datetime | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("formula timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _validate_alignment_parameters(
    alignment_policy: FormulaAlignmentPolicy,
    alignment_parameters_json: dict[str, Any] | None,
) -> None:
    parameters = alignment_parameters_json or {}
    if alignment_policy == "exact" and parameters:
        raise ValueError("exact alignment does not accept alignment parameters")
    if alignment_policy == "asof":
        allowed = {"max_staleness_seconds"}
        unknown = set(parameters) - allowed
        if unknown:
            raise ValueError(f"unsupported asof alignment parameters: {sorted(unknown)}")
        max_staleness = parameters.get("max_staleness_seconds")
        if not isinstance(max_staleness, (int, float)) or isinstance(max_staleness, bool):
            raise ValueError("asof alignment requires numeric max_staleness_seconds")
        if not math.isfinite(float(max_staleness)) or float(max_staleness) < 0:
            raise ValueError("max_staleness_seconds must be finite and non-negative")


class IndexFormulaSourceReference(BaseModel):
    """Stable source identity used by a formula input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: FormulaSourceType
    identifier: str = Field(min_length=1, max_length=255)

    @field_validator("identifier")
    @classmethod
    def _strip_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source identifier cannot be empty")
        return normalized


class IndexFormulaInput(BaseModel):
    """Exact public source binding for one formula reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_reference: IndexFormulaSourceReference
    meta_table_uid: uuid.UUID
    observable: str = Field(min_length=1, max_length=255)

    @field_validator("observable")
    @classmethod
    def _validate_observable(cls, value: str) -> str:
        normalized = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized) is None:
            raise ValueError("observable must be a valid formula attribute name")
        return normalized

    @property
    def reference(self) -> FormulaReference:
        return FormulaReference(
            source_type=self.source_reference.type,
            identifier=self.source_reference.identifier,
            observable=self.observable,
        )

    def semantic_payload(self) -> dict[str, str]:
        return {
            "source_type": self.source_reference.type,
            "identifier": self.source_reference.identifier,
            "meta_table_uid": str(self.meta_table_uid),
            "observable": self.observable,
        }


class IndexFormulaDefinition(BaseModel):
    """Immutable versioned point-in-time formula definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: uuid.UUID | None = None
    index_uid: uuid.UUID | None = None
    version: int | None = Field(default=None, gt=0)
    status: FormulaStatus = "draft"
    valid_from: datetime.datetime
    valid_to: datetime.datetime | None = None
    formula: str = Field(min_length=1)
    alignment_policy: FormulaAlignmentPolicy = "exact"
    alignment_parameters_json: dict[str, Any] | None = None
    missing_data_policy: FormulaMissingDataPolicy = "drop"
    definition_hash: str | None = Field(default=None, min_length=64, max_length=64)
    metadata_json: dict[str, Any] | None = None

    @field_validator("valid_from", "valid_to", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: Any) -> datetime.datetime | None:
        return _utc(value)

    @field_validator("formula")
    @classmethod
    def _validate_formula(cls, value: str) -> str:
        parse_formula(value)
        return value.strip()

    @model_validator(mode="after")
    def _validate_contract(self) -> IndexFormulaDefinition:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        _validate_alignment_parameters(
            self.alignment_policy,
            self.alignment_parameters_json,
        )
        return self

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "valid_from": self.valid_from.isoformat(),
            "formula": canonical_formula(self.formula),
            "alignment_policy": self.alignment_policy,
            "alignment_parameters_json": self.alignment_parameters_json,
            "missing_data_policy": self.missing_data_policy,
        }


class IndexFormulaResult(BaseModel):
    """Pure formula result in canonical Index observation shape."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    values: pd.DataFrame


@dataclass(frozen=True, order=True)
class FormulaReference:
    source_type: FormulaSourceType
    identifier: str
    observable: str

    @property
    def expression(self) -> str:
        return f"{self.source_type}[{json.dumps(self.identifier, ensure_ascii=True)}].{self.observable}"


@dataclass(frozen=True)
class FormulaNumber:
    value: int | float


@dataclass(frozen=True)
class FormulaUnary:
    operator: Literal["+", "-"]
    operand: FormulaNode


@dataclass(frozen=True)
class FormulaBinary:
    operator: Literal["+", "-", "*", "/", "**"]
    left: FormulaNode
    right: FormulaNode


FormulaNode = FormulaReference | FormulaNumber | FormulaUnary | FormulaBinary


class FormulaSyntaxError(ValueError):
    """Raised when a formula uses syntax outside the supported arithmetic grammar."""


_IGNORED_TOKENS = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT}
_NUMBER_PATTERN = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


class _FormulaParser:
    def __init__(self, expression: str) -> None:
        try:
            generated = tokenize.generate_tokens(io.StringIO(expression).readline)
            self.tokens = [item for item in generated if item.type not in _IGNORED_TOKENS]
        except (tokenize.TokenError, IndentationError) as exc:
            raise FormulaSyntaxError(f"invalid formula syntax: {exc}") from exc
        self.position = 0

    def parse(self) -> FormulaNode:
        node = self._sum()
        if self._peek().type != token.ENDMARKER:
            raise self._error("unexpected token")
        return node

    def _sum(self) -> FormulaNode:
        node = self._term()
        while self._peek().string in {"+", "-"}:
            operator = self._take().string
            node = FormulaBinary(operator=operator, left=node, right=self._term())
        return node

    def _term(self) -> FormulaNode:
        node = self._unary()
        while self._peek().string in {"*", "/"}:
            operator = self._take().string
            node = FormulaBinary(operator=operator, left=node, right=self._unary())
        return node

    def _unary(self) -> FormulaNode:
        if self._peek().string in {"+", "-"}:
            operator = self._take().string
            return FormulaUnary(operator=operator, operand=self._unary())
        return self._power()

    def _power(self) -> FormulaNode:
        node = self._primary()
        if self._peek().string == "**":
            self._take()
            node = FormulaBinary(operator="**", left=node, right=self._unary())
        return node

    def _primary(self) -> FormulaNode:
        current = self._peek()
        if current.string == "(":
            self._take()
            node = self._sum()
            self._expect(")")
            return node
        if current.type == token.NUMBER:
            return FormulaNumber(self._number(self._take().string))
        if current.type == token.NAME and current.string in {"asset", "index"}:
            return self._reference()
        raise self._error("expected a number, source reference, or parenthesized expression")

    def _reference(self) -> FormulaReference:
        source_type = self._take().string
        self._expect("[")
        identifier_token = self._take()
        if identifier_token.type != token.STRING or not identifier_token.string.startswith('"'):
            raise self._error("source identifiers must be double-quoted strings")
        try:
            identifier = json.loads(identifier_token.string)
        except json.JSONDecodeError as exc:
            raise self._error("source identifier is not a valid JSON string") from exc
        if not isinstance(identifier, str) or not identifier:
            raise self._error("source identifier must be a non-empty string")
        self._expect("]")
        self._expect(".")
        observable_token = self._take()
        if observable_token.type != token.NAME:
            raise self._error("source observable must be an attribute name")
        return FormulaReference(
            source_type=source_type,
            identifier=identifier,
            observable=observable_token.string,
        )

    def _number(self, raw: str) -> int | float:
        if _NUMBER_PATTERN.fullmatch(raw) is None:
            raise self._error("only finite decimal numeric constants are supported")
        try:
            decimal = Decimal(raw)
        except InvalidOperation as exc:
            raise self._error("invalid numeric constant") from exc
        if not decimal.is_finite():
            raise self._error("numeric constants must be finite")
        if decimal == decimal.to_integral_value() and "." not in raw and "e" not in raw.lower():
            return int(decimal)
        result = float(decimal)
        if not math.isfinite(result):
            raise self._error("numeric constants must be finite")
        return result

    def _peek(self) -> tokenize.TokenInfo:
        return self.tokens[self.position]

    def _take(self) -> tokenize.TokenInfo:
        current = self._peek()
        self.position += 1
        return current

    def _expect(self, value: str) -> None:
        if self._peek().string != value:
            raise self._error(f"expected {value!r}")
        self._take()

    def _error(self, message: str) -> FormulaSyntaxError:
        current = self._peek()
        return FormulaSyntaxError(f"{message} at line {current.start[0]}, column {current.start[1] + 1}")


def parse_formula(expression: str) -> FormulaNode:
    normalized = expression.strip()
    if not normalized:
        raise FormulaSyntaxError("formula cannot be empty")
    return _FormulaParser(normalized).parse()


def _canonical_node(node: FormulaNode) -> str:
    if isinstance(node, FormulaReference):
        return node.expression
    if isinstance(node, FormulaNumber):
        return json.dumps(node.value, allow_nan=False)
    if isinstance(node, FormulaUnary):
        return f"({node.operator}{_canonical_node(node.operand)})"
    return f"({_canonical_node(node.left)}{node.operator}{_canonical_node(node.right)})"


def canonical_formula(expression: str) -> str:
    return _canonical_node(parse_formula(expression))


def formula_references(expression: str) -> frozenset[FormulaReference]:
    references: set[FormulaReference] = set()

    def visit(node: FormulaNode) -> None:
        if isinstance(node, FormulaReference):
            references.add(node)
        elif isinstance(node, FormulaUnary):
            visit(node.operand)
        elif isinstance(node, FormulaBinary):
            visit(node.left)
            visit(node.right)

    visit(parse_formula(expression))
    return frozenset(references)


def compute_formula_definition_hash(
    definition: IndexFormulaDefinition,
    inputs: list[IndexFormulaInput] | tuple[IndexFormulaInput, ...],
) -> str:
    payload = {
        "definition": definition.semantic_payload(),
        "inputs": [
            item.semantic_payload()
            for item in sorted(inputs, key=lambda item: item.reference.expression)
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_formula_inputs(
    formula: str,
    inputs: list[IndexFormulaInput] | tuple[IndexFormulaInput, ...],
) -> None:
    references = formula_references(formula)
    if not references:
        raise ValueError("an Index formula must reference at least one Asset or Index input")
    input_references = [item.reference for item in inputs]
    if len(set(input_references)) != len(input_references):
        raise ValueError("formula inputs contain duplicate source references")
    missing = references - set(input_references)
    unused = set(input_references) - references
    if missing or unused:
        details: list[str] = []
        if missing:
            details.append(f"missing inputs: {sorted(item.expression for item in missing)}")
        if unused:
            details.append(f"unused inputs: {sorted(item.expression for item in unused)}")
        raise ValueError("formula references must exactly match inputs; " + "; ".join(details))


def validate_formula_contract(
    definition: IndexFormulaDefinition,
    inputs: list[IndexFormulaInput] | tuple[IndexFormulaInput, ...],
) -> str:
    _validate_formula_inputs(definition.formula, inputs)
    digest = compute_formula_definition_hash(definition, inputs)
    if definition.definition_hash is not None and definition.definition_hash != digest:
        raise ValueError("definition_hash does not match formula and source semantics")
    return digest


class IndexFormulaEvaluation(BaseModel):
    """Historical formula values and their latest source observation timestamps."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    values: pd.DataFrame


class IndexFormula(BaseModel):
    """Self-contained formula contract for evaluating historical observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    formula: str = Field(min_length=1)
    inputs: tuple[IndexFormulaInput, ...] = Field(min_length=1)
    alignment_policy: FormulaAlignmentPolicy = "exact"
    alignment_parameters_json: dict[str, Any] | None = None
    missing_data_policy: FormulaMissingDataPolicy = "drop"

    @field_validator("formula")
    @classmethod
    def _validate_formula(cls, value: str) -> str:
        parse_formula(value)
        return value.strip()

    @model_validator(mode="after")
    def _validate_contract(self) -> IndexFormula:
        _validate_alignment_parameters(
            self.alignment_policy,
            self.alignment_parameters_json,
        )
        _validate_formula_inputs(self.formula, self.inputs)
        return self

    @classmethod
    def from_definition(
        cls,
        definition: IndexFormulaDefinition,
        inputs: Sequence[IndexFormulaInput],
    ) -> IndexFormula:
        """Build a pure historical formula from one persisted definition contract."""

        typed_inputs = tuple(inputs)
        validate_formula_contract(definition, typed_inputs)
        return cls(
            formula=definition.formula,
            inputs=typed_inputs,
            alignment_policy=definition.alignment_policy,
            alignment_parameters_json=definition.alignment_parameters_json,
            missing_data_policy=definition.missing_data_policy,
        )

    def evaluate_historical(
        self,
        observations: Mapping[FormulaReference | str, pd.Series | pd.DataFrame],
        *,
        times: Sequence[Any] | pd.DatetimeIndex | None = None,
    ) -> IndexFormulaEvaluation:
        """Evaluate caller-supplied historical series without persisted Index state."""

        from msm.analytics.indices.engine import _evaluate_historical_formula

        return _evaluate_historical_formula(
            formula=self,
            observations=observations,
            times=times,
        )


__all__ = [
    "FormulaAlignmentPolicy",
    "FormulaBinary",
    "FormulaMissingDataPolicy",
    "FormulaNode",
    "FormulaNumber",
    "FormulaReference",
    "FormulaSourceType",
    "FormulaStatus",
    "FormulaSyntaxError",
    "FormulaUnary",
    "IndexFormulaDefinition",
    "IndexFormula",
    "IndexFormulaEvaluation",
    "IndexFormulaInput",
    "IndexFormulaResult",
    "IndexFormulaSourceReference",
    "canonical_formula",
    "compute_formula_definition_hash",
    "formula_references",
    "parse_formula",
    "validate_formula_contract",
]
