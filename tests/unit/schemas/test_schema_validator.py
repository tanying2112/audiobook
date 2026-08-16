"""Tests for src/audiobook_studio/schemas/schema_validator.py.

Pure-logic tests (no DB): SchemaValidator compares SQLAlchemy ORM models
against Pydantic schemas and reports drift. Exercises type normalization,
Optional detection, Literal refinement, nullability matching, and migration
hint generation.
"""
from __future__ import annotations

from typing import List, Optional

import pytest
from pydantic import BaseModel

from src.audiobook_studio.schemas.schema_validator import (
    DriftType,
    FieldDiff,
    SchemaSyncReport,
    SchemaValidator,
    sync_schema_validator,
)


# ---- minimal ORM-like fixtures (no DB needed) -----------------------------

class _FakeColumn:
    def __init__(self, name, type_obj, nullable=True, primary_key=False, default=None, length=None):
        self.name = name
        self.type = type_obj
        self.nullable = nullable
        self.primary_key = primary_key
        self.default = default
        self.type.length = length


class _FakeType:
    def __init__(self, python_type: str):
        self.python_type = type(python_type) if not isinstance(python_type, type) else python_type
        self.length = None

    @property
    def __class_name__(self):
        return type(self).__name__


class _FakeTypeWrapper:
    """Wraps an ORM type so type(obj).__name__ and obj.python_type work like SA."""

    def __init__(self, type_name: str, python_type_name: str = "str", length=None):
        self.type_name = type_name
        self.python_type_name = python_type_name
        self.length = length
        # mimic attribute access used by validator: type(col.type).__name__
        self.__class__ = type(type_name, (), {"python_type": type(self)})  # not used directly

    # Provide the shape SchemaValidator._get_orm_columns expects:
    #   type(col.type).__name__ -> "String" etc
    #   col.type.python_type.__name__ -> "str" etc
    def _make_type_obj(self):
        t = type(self.type_name, (), {})  # class named e.g. "String"
        t.python_type = type(self.python_type_name, (), {})  # class named e.g. "str"
        t.length = self.length
        return self  # type: ignore[return-value]


class _FakeAttr:
    """Mimics a SQLAlchemy mapper attr with a `.columns` list."""

    def __init__(self, columns):
        self.columns = columns


class _FakeMapper:
    def __init__(self, attrs):
        self.attrs = attrs


def _orm_model(columns, model_name="FakeModel"):
    """Build a minimal fake ORM model whose sa_inspection returns columns.

    `columns` is a list of dicts: {name, type_name, python_type_name, nullable, pk, default, length}.
    """
    fake_cols = []
    for c in columns:
        type_class = type(c["type_name"], (), {})  # class whose __name__ == type_name
        pt = type(c.get("python_type_name", "str"), (), {})
        type_instance = type_class()
        type_instance.python_type = pt
        type_instance.length = c.get("length")
        col_obj = type(
            "Col",
            (),
            {
                "name": c["name"],
                "type": type_instance,
                "nullable": c.get("nullable", True),
                "primary_key": c.get("pk", False),
                "default": c.get("default"),
            },
        )()
        fake_cols.append(col_obj)

    class FakeModel:
        @staticmethod
        def _sa_inspect():
            return _FakeMapper([_FakeAttr(fake_cols)])

    # `__name__ = x` inside the class body is shadowed by type.__name__'s
    # getset descriptor (which returns the `class` statement identifier).
    # Assign on the descriptor post-declaration to actually rename it.
    FakeModel.__name__ = model_name
    return FakeModel


# Patch sqlalchemy.inspect inside the validator module for these tests.
import src.audiobook_studio.schemas.schema_validator as sv_module


@pytest.fixture
def patched_inspect():
    orig = sv_module.sa_inspect
    captured = {}

    def fake_inspect(model):
        # Each FakeModel exposes its columns via _sa_inspect
        report = model._sa_inspect() if hasattr(model, "_sa_inspect") else orig(model)
        captured["mapper"] = report
        return report

    sv_module.sa_inspect = fake_inspect
    yield captured
    sv_module.sa_inspect = orig


# ---- Pydantic schemas for compare tests -----------------------------------


class SyncedSchema(BaseModel):
    name: str
    age: int


class ExtraFieldSchema(BaseModel):
    name: str
    age: int
    unexpected_field: str = "x"


class MissingFieldSchema(BaseModel):
    # Schema MISSING the 'age' field the ORM defines -> RFIELD_REMOVED drift
    name: str


class TypeMismatchSchema(BaseModel):
    name: int  # ORM is str, schema is int


class NullableSchema(BaseModel):
    name: str  # schema non-nullable but ORM nullable


# ============================================================
# _type_to_string
# ============================================================

class TestTypeToString:
    def test_plain_types(self):
        v = SchemaValidator()
        assert v._type_to_string(int) == "int"
        assert v._type_to_string(str) == "str"
        assert v._type_to_string(bool) == "bool"
        assert v._type_to_string(float) == "float"

    def test_list_with_arg(self):
        v = SchemaValidator()
        result = v._type_to_string(List[int])
        assert result == "List[int]"

    def test_list_without_args(self):
        v = SchemaValidator()
        # bare list primitive (no generic args) -> "list" via PYDANTIC_TYPE_MAP
        assert v._type_to_string(list) == "list"

    def test_dict_origin(self):
        v = SchemaValidator()
        result = v._type_to_string(dict)
        # plain dict (no __origin__ in 3.9+ runtime) falls to PYDANTIC_TYPE_MAP
        assert result == "dict"

    def test_dict_with_args_returns_dict(self):
        from typing import Dict

        v = SchemaValidator()
        # Dict[str, int] has __origin__ is dict -> "dict" (collapses to plain dict)
        assert v._type_to_string(Dict[str, int]) == "dict"

    def test_optional_unwraps_first_arg(self):
        v = SchemaValidator()
        result = v._type_to_string(Optional[int])
        assert result == "int"

    def test_unknown_type_falls_back_to_repr(self):
        v = SchemaValidator()
        class Custom:
            pass
        # Unknown type with no __origin__ -> str(type) fallback
        result = v._type_to_string(Custom)
        assert "Custom" in result


# ============================================================
# _is_optional
# ============================================================

class TestIsOptional:
    def test_plain_type_not_optional(self):
        v = SchemaValidator()
        assert v._is_optional(int) is False
        assert v._is_optional(str) is False

    def test_optional_int(self):
        v = SchemaValidator()
        assert v._is_optional(Optional[int]) is True

    def test_union_with_none(self):
        from typing import Union
        v = SchemaValidator()
        assert v._is_optional(Union[str, None]) is True

    def test_union_without_none(self):
        from typing import Union
        v = SchemaValidator()
        assert v._is_optional(Union[int, str]) is False

    def test_list_of_optional_not_optional_itself(self):
        # List[Optional[int]] -> the outer type is list, not Optional
        v = SchemaValidator()
        assert v._is_optional(List[Optional[int]]) is False


# ============================================================
# compare - drift detection
# ============================================================

class TestCompareDrift:
    def test_synced_model_schema_no_drift(self, patched_inspect):
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False, "pk": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, SyncedSchema)
        assert report.is_synced is True
        assert report.drifts == []

    def test_field_in_schema_not_in_orm_yields_added(self, patched_inspect):
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, ExtraFieldSchema)
        assert report.is_synced is False
        added = [d for d in report.drifts if d.drift_type == DriftType.FIELD_ADDED]
        assert len(added) == 1
        assert added[0].field_name == "unexpected_field"
        # migration hint should mention adding a column
        assert any("Add column 'unexpected_field'" in h for h in report.migration_hints)

    def test_field_in_orm_not_in_schema_yields_removed(self, patched_inspect):
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, MissingFieldSchema)
        assert report.is_synced is False
        removed = [d for d in report.drifts if d.drift_type == DriftType.FIELD_REMOVED]
        assert len(removed) == 1
        assert removed[0].field_name == "age"
        assert any("Add field 'age'" in h for h in report.migration_hints)

    def test_internal_underscore_fields_skipped(self, patched_inspect):
        # Provide a skewed schema so a drift is detected; underscore cols must be ignored
        class OnlyNameSchema(BaseModel):
            name: str

        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "_sa_instance_state", "type_name": "String", "python_type_name": "str", "nullable": True},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, OnlyNameSchema)
        # _sa_instance_state should be skipped (not flagged as REMOVED)
        removed_names = [d.field_name for d in report.drifts if d.drift_type == DriftType.FIELD_REMOVED]
        assert "_sa_instance_state" not in removed_names

    def test_type_mismatch_detected(self, patched_inspect):
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, TypeMismatchSchema)
        changed = [d for d in report.drifts if d.drift_type == DriftType.TYPE_CHANGED]
        assert len(changed) == 1
        assert changed[0].field_name == "name"
        assert changed[0].orm_type == "str"
        assert changed[0].schema_type == "int"

    def test_nullability_mismatch_detected(self, patched_inspect):
        # ORM nullable=True, schema non-nullable (str) -> mismatch
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": True},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, NullableSchema)
        nullab = [d for d in report.drifts if d.drift_type == DriftType.NULLABILITY_CHANGED]
        assert len(nullab) == 1
        assert nullab[0].field_name == "name"
        assert nullab[0].orm_nullable is True
        assert nullab[0].schema_nullable is False
        assert any("Check if 'name' should be nullable" in w for w in report.warnings)

    def test_both_nullable_strings_match(self, patched_inspect):
        # ORM nullable str + Schema Optional[str] -> base types match, no TYPE_CHANGED
        class OptStrSchema(BaseModel):
            name: Optional[str] = None
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": True},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, OptStrSchema)
        # No TYPE_CHANGED drift for name
        type_changed = [d for d in report.drifts if d.drift_type == DriftType.TYPE_CHANGED and d.field_name == "name"]
        # We assert the absence of a TYPE_CHANGED record — a feature of the fix.
        assert type_changed == []

    def test_literal_refines_str_no_type_drift(self, patched_inspect):
        # Schema uses a Literal type refining an ORM str column -> accepted refinement,
        # no TYPE_CHANGED drift (exercises the Literal branch in compare()).
        from typing import Literal

        class LiteralSchema(BaseModel):
            name: Literal["draft", "completed"]

        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        report = v.compare(model, LiteralSchema)
        type_changed = [d for d in report.drifts if d.drift_type == DriftType.TYPE_CHANGED and d.field_name == "name"]
        assert type_changed == []


# ============================================================
# validate_all
# ============================================================

class TestValidateAll:
    def test_validate_all_collects_reports(self, patched_inspect):
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        reports = v.validate_all([(model, MissingFieldSchema)])
        assert len(reports) == 1
        assert reports[0].model_name == "FakeModel"
        assert v.reports == reports

    def test_validate_all_multiple_pairs(self, patched_inspect):
        synced_model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="SyncedModel")
        # drift_model has 'age' but MissingFieldSchema lacks it -> FIELD_REMOVED drift
        drift_model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="DriftModel")
        v = SchemaValidator()
        reports = v.validate_all([
            (synced_model, SyncedSchema),
            (drift_model, MissingFieldSchema),
        ])
        assert reports[0].is_synced is True
        assert reports[1].is_synced is False


# ============================================================
# generate_migration_script_hint
# ============================================================

class TestMigrationHint:
    def test_empty_reports_returns_no_migration_string(self):
        v = SchemaValidator()
        hint = v.generate_migration_script_hint()
        assert "No migration needed" in hint

    def test_filled_reports_generates_upgrade_with_hints(self, patched_inspect):
        # 'age' exists in ORM but not in MissingFieldSchema -> drift -> hint emitted
        model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="FakeModel")
        v = SchemaValidator()
        v.validate_all([(model, MissingFieldSchema)])
        hint = v.generate_migration_script_hint()
        assert "def upgrade" in hint
        assert "def downgrade" in hint
        assert "For FakeModel" in hint
        assert "HINT" in hint

    def test_synced_reports_skipped_in_hint(self, patched_inspect):
        synced_model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="SyncedModel")
        drift_model = _orm_model([
            {"name": "name", "type_name": "String", "python_type_name": "str", "nullable": False},
            {"name": "age", "type_name": "Integer", "python_type_name": "int", "nullable": False},
        ], model_name="DriftModel")
        v = SchemaValidator()
        v.validate_all([
            (synced_model, SyncedSchema),
            (drift_model, MissingFieldSchema),
        ])
        hint = v.generate_migration_script_hint()
        assert "For SyncedModel" not in hint
        assert "For DriftModel" in hint


# ============================================================
# SchemaSyncReport.to_dict
# ============================================================

class TestSchemaSyncReportToDict:
    def test_to_dict_round_trips(self):
        report = SchemaSyncReport(
            model_name="M",
            schema_name="S",
            is_synced=False,
            drifts=[FieldDiff(drift_type=DriftType.FIELD_ADDED, field_name="x", schema_type="str")],
            warnings=["w1"],
            migration_hints=["h1"],
        )
        d = report.to_dict()
        assert d["model_name"] == "M"
        assert d["is_synced"] is False
        assert d["drifts"][0]["drift_type"] == "field_added"
        assert d["drifts"][0]["field_name"] == "x"
        assert d["warnings"] == ["w1"]
        assert d["migration_hints"] == ["h1"]

    def test_to_dict_empty_drifts(self):
        report = SchemaSyncReport(model_name="M", schema_name="S", is_synced=True)
        d = report.to_dict()
        assert d["drifts"] == []
        assert d["warnings"] == []
        assert d["migration_hints"] == []


# ============================================================
# DriftType enum
# ============================================================

class TestDriftType:
    def test_enum_values_are_strings(self):
        assert DriftType.FIELD_ADDED.value == "field_added"
        assert DriftType.FIELD_REMOVED.value == "field_removed"
        assert DriftType.TYPE_CHANGED.value == "type_changed"
        assert DriftType.NULLABILITY_CHANGED.value == "nullability_changed"
        assert DriftType.LENGTH_CHANGED.value == "length_changed"


# ============================================================
# sync_schema_validator (module-level function, calls sys.exit)
# ============================================================

class TestSyncSchemaValidator:
    def test_synced_returns_zero_exit(self, patched_inspect, capsys):
        # Build a synced pair using real Project models is hard; instead patch
        # validator.validate_all to return an empty drifts list.
        from src.audiobook_studio.schemas import schema_validator as mod

        real_validator_cls = mod.SchemaValidator

        class FakeValidator:
            def __init__(self):
                self.reports = []

            def validate_all(self, pairs):
                r = SchemaSyncReport(model_name="Project", schema_name="Project", is_synced=True)
                self.reports = [r]
                return [r]

            def generate_migration_script_hint(self):
                return ""

        # Replace class + restore after
        orig = mod.SchemaValidator
        mod.SchemaValidator = FakeValidator
        try:
            with pytest.raises(SystemExit) as exc:
                sync_schema_validator()
            assert exc.value.code == 0
        finally:
            mod.SchemaValidator = orig

    def test_drift_exits_nonzero(self, patched_inspect):
        from src.audiobook_studio.schemas import schema_validator as mod

        class FakeValidator:
            def __init__(self):
                self.reports = []

            def validate_all(self, pairs):
                r = SchemaSyncReport(
                    model_name="Project",
                    schema_name="Project",
                    is_synced=False,
                    drifts=[FieldDiff(drift_type=DriftType.FIELD_ADDED, field_name="extra")],
                    migration_hints=["Add 'extra'"],
                )
                self.reports = [r]
                return [r]

            def generate_migration_script_hint(self):
                return "fake hint"

        orig = mod.SchemaValidator
        mod.SchemaValidator = FakeValidator
        try:
            with pytest.raises(SystemExit) as exc:
                sync_schema_validator()
            assert exc.value.code == 1
        finally:
            mod.SchemaValidator = orig
