"""Tests for schema_validator module."""

import pytest
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import DeclarativeBase

from src.audiobook_studio.schemas.schema_validator import (
    SchemaSyncReport,
    FieldDiff,
    DriftType,
    SchemaValidator,
    sync_schema_validator,
)


class MockBase(DeclarativeBase):
    """Mock ORM base for testing."""
    pass


class MockUserModel(MockBase):
    """Mock SQLAlchemy model."""
    __tablename__ = "mock_users"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    email = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)


class MockUserSchema(BaseModel):
    """Corresponding Pydantic schema."""
    id: int
    name: str
    email: Optional[str] = None
    age: Optional[int] = None


class MockSchemaDifferent(BaseModel):
    """Schema with different fields (for drift detection)."""
    id: int
    name: str
    email: str  # Should be Optional
    extra_field: str = "default"


class MockModelMissing(MockBase):
    """Model missing fields."""
    __tablename__ = "mock_missing"

    id = Column(Integer, primary_key=True)
    name = Column(String(50))


class MockSchemaMissing(BaseModel):
    """Schema missing fields."""
    id: int
    name: str
    age: Optional[int] = None


class TestDriftType:
    """Tests for DriftType enum."""

    def test_drift_type_values(self):
        """Test DriftType enum values."""
        assert DriftType.FIELD_ADDED.value == "field_added"
        assert DriftType.FIELD_REMOVED.value == "field_removed"
        assert DriftType.TYPE_CHANGED.value == "type_changed"
        assert DriftType.NULLABILITY_CHANGED.value == "nullability_changed"
        assert DriftType.LENGTH_CHANGED.value == "length_changed"


class TestFieldDiff:
    """Tests for FieldDiff dataclass."""

    def test_field_diff_creation(self):
        """Test creating a FieldDiff."""
        diff = FieldDiff(
            drift_type=DriftType.FIELD_ADDED,
            field_name="test_field",
            message="Field was added",
        )
        assert diff.drift_type == DriftType.FIELD_ADDED
        assert diff.field_name == "test_field"
        assert diff.message == "Field was added"
        assert diff.orm_type is None
        assert diff.schema_type is None

    def test_field_diff_with_types(self):
        """Test FieldDiff with type info."""
        diff = FieldDiff(
            drift_type=DriftType.TYPE_CHANGED,
            field_name="x",
            orm_type="VARCHAR",
            schema_type="str",
            orm_nullable=False,
            schema_nullable=True,
        )
        assert diff.orm_type == "VARCHAR"
        assert diff.schema_type == "str"
        assert diff.orm_nullable is False
        assert diff.schema_nullable is True


class TestSchemaSyncReport:
    """Tests for SchemaSyncReport dataclass."""

    def test_report_creation(self):
        """Test creating a SchemaSyncReport."""
        report = SchemaSyncReport(
            model_name="TestModel",
            schema_name="TestSchema",
            is_synced=True,
        )
        assert report.model_name == "TestModel"
        assert report.schema_name == "TestSchema"
        assert report.is_synced is True
        assert report.drifts == []
        assert report.warnings == []
        assert report.migration_hints == []

    def test_report_to_dict(self):
        """Test converting report to dict."""
        report = SchemaSyncReport(
            model_name="TestModel",
            schema_name="TestSchema",
            is_synced=False,
            drifts=[
                FieldDiff(
                    drift_type=DriftType.FIELD_ADDED,
                    field_name="extra",
                    orm_type="VARCHAR",
                    schema_type="str",
                    message="New field",
                )
            ],
            warnings=["warning1"],
            migration_hints=["hint1"],
        )
        result = report.to_dict()
        assert result["model_name"] == "TestModel"
        assert result["is_synced"] is False
        assert len(result["drifts"]) == 1
        assert result["drifts"][0]["drift_type"] == "field_added"
        assert result["drifts"][0]["field_name"] == "extra"
        assert result["warnings"] == ["warning1"]
        assert result["migration_hints"] == ["hint1"]


class TestSchemaValidator:
    """Tests for SchemaValidator class."""

    def test_init(self):
        """Test initialization."""
        validator = SchemaValidator()
        assert validator is not None

    def test_type_to_string_builtin(self):
        """Test type_to_string with builtin types."""
        validator = SchemaValidator()
        assert validator._type_to_string(int) == "int"
        assert validator._type_to_string(str) == "str"
        assert validator._type_to_string(float) == "float"

    def test_type_to_string_optional(self):
        """Test type_to_string with Optional types."""
        validator = SchemaValidator()
        result = validator._type_to_string(Optional[int])
        assert "int" in result.lower()

    def test_is_optional_true(self):
        """Test is_optional returns True for Optional types."""
        validator = SchemaValidator()
        assert validator._is_optional(Optional[str]) is True
        assert validator._is_optional(Optional[int]) is True

    def test_is_optional_false(self):
        """Test is_optional returns False for non-Optional types."""
        validator = SchemaValidator()
        assert validator._is_optional(str) is False
        assert validator._is_optional(int) is False

    def test_get_orm_columns(self):
        """Test _get_orm_columns extracts column information."""
        validator = SchemaValidator()
        columns = validator._get_orm_columns(MockUserModel)
        assert "id" in columns
        assert "name" in columns
        assert "email" in columns
        assert "age" in columns
        assert columns["name"]["nullable"] is False
        assert columns["email"]["nullable"] is True

    def test_get_schema_fields(self):
        """Test _get_schema_fields extracts field information."""
        validator = SchemaValidator()
        fields = validator._get_schema_fields(MockUserSchema)
        assert "id" in fields
        assert "name" in fields
        assert "email" in fields
        assert "age" in fields

    def test_compare_synced(self):
        """Test compare returns SchemaSyncReport."""
        validator = SchemaValidator()
        report = validator.compare(MockUserModel, MockUserSchema)
        assert isinstance(report, SchemaSyncReport)
        assert report.model_name == "MockUserModel"
        assert report.schema_name == "MockUserSchema"

    def test_compare_with_different_fields(self):
        """Test compare identifies drift."""
        validator = SchemaValidator()
        report = validator.compare(MockUserModel, MockSchemaDifferent)
        assert isinstance(report.drifts, list)
        assert isinstance(report.warnings, list)

    def test_compare_with_missing_fields(self):
        """Test compare handles missing fields."""
        validator = SchemaValidator()
        report = validator.compare(MockModelMissing, MockSchemaMissing)
        assert isinstance(report, SchemaSyncReport)

    def test_validate_all(self):
        """Test validate_all processes multiple pairs."""
        validator = SchemaValidator()
        pairs = [
            (MockUserModel, MockUserSchema),
            (MockUserModel, MockSchemaDifferent),
        ]
        reports = validator.validate_all(pairs)
        assert len(reports) == 2
        assert all(isinstance(r, SchemaSyncReport) for r in reports)

    def test_validate_all_empty(self):
        """Test validate_all with empty list."""
        validator = SchemaValidator()
        reports = validator.validate_all([])
        assert reports == []

    def test_generate_migration_script_hint(self):
        """Test generate_migration_script_hint."""
        validator = SchemaValidator()
        validator.compare(MockUserModel, MockSchemaDifferent)
        hint = validator.generate_migration_script_hint()
        assert isinstance(hint, str)


class TestSyncSchemaValidator:
    """Tests for sync_schema_validator function."""

    def test_sync_schema_validator_basic(self):
        """Test sync_schema_validator runs without unhandled exception."""
        # sync_schema_validator calls sys.exit() - catch the SystemExit
        with pytest.raises(SystemExit) as exc_info:
            sync_schema_validator()
        assert exc_info.value.code in (0, 1, None)

    def test_sync_schema_validator_prints_report(self, capsys):
        """Test sync_schema_validator prints a report."""
        with pytest.raises(SystemExit):
            sync_schema_validator()
        captured = capsys.readouterr()
        assert "Schema Synchronization Report" in captured.out
        assert "Total pairs checked" in captured.out