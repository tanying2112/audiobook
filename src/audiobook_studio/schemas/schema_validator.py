"""Schema Validator - Auto-sync ORM models and Pydantic schemas.

Provides:
- Field type consistency checks between ORM and Schema
- Auto-detection of drift (new/removed/modified fields)
- Migration script generation hints
- Sync validation for CI/CD
"""

import inspect
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class DriftType(str, Enum):
    """Types of schema drift."""
    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    TYPE_CHANGED = "type_changed"
    NULLABILITY_CHANGED = "nullability_changed"
    LENGTH_CHANGED = "length_changed"


@dataclass
class FieldDiff:
    """Represents a single field difference between ORM and Schema."""

    drift_type: DriftType
    field_name: str
    orm_type: Optional[str] = None
    schema_type: Optional[str] = None
    orm_nullable: bool = True
    schema_nullable: bool = True
    message: str = ""


@dataclass
class SchemaSyncReport:
    """Report of schema synchronization status."""

    model_name: str
    schema_name: str
    is_synced: bool
    drifts: List[FieldDiff] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    migration_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "model_name": self.model_name,
            "schema_name": self.schema_name,
            "is_synced": self.is_synced,
            "drifts": [
                {
                    "drift_type": d.drift_type.value,
                    "field_name": d.field_name,
                    "orm_type": d.orm_type,
                    "schema_type": d.schema_type,
                    "message": d.message,
                }
                for d in self.drifts
            ],
            "warnings": self.warnings,
            "migration_hints": self.migration_hints,
        }


class SchemaValidator:
    """Validates synchronization between ORM models and Pydantic schemas."""

    # Type mapping from SQLAlchemy to Python types
    SQLALCHEMY_TYPE_MAP = {
        "Integer": "int",
        "BigInteger": "int",
        "SmallInteger": "int",
        "String": "str",
        "Text": "str",
        "Boolean": "bool",
        "DateTime": "datetime",
        "Date": "date",
        "Time": "time",
        "Float": "float",
        "Numeric": "Decimal",
        "JSON": "dict",
        "PickleType": "Any",
    }

    # Pydantic type to string mapping
    PYDANTIC_TYPE_MAP = {
        int: "int",
        str: "str",
        bool: "bool",
        float: "float",
        dict: "dict",
        list: "list",
        Any: "Any",
    }

    def __init__(self):
        self.reports: List[SchemaSyncReport] = []

    def _get_orm_columns(self, model: Type[DeclarativeBase]) -> Dict[str, Dict[str, Any]]:
        """Extract column information from ORM model."""
        columns = {}
        mapper = sa_inspect(model)

        for attr in mapper.attrs:
            if hasattr(attr, 'columns'):
                for col in attr.columns:
                    col_type = type(col.type).__name__
                    columns[col.name] = {
                        "type": col_type,
                        "python_type": col.type.python_type.__name__ if hasattr(col.type, 'python_type') else "Any",
                        "nullable": col.nullable,
                        "primary_key": col.primary_key,
                        "default": col.default,
                        "length": getattr(col.type, 'length', None),
                    }

        return columns

    def _get_schema_fields(self, schema: Type[BaseModel]) -> Dict[str, Dict[str, Any]]:
        """Extract field information from Pydantic schema."""
        fields = {}

        for field_name, field_info in schema.model_fields.items():
            field_type = field_info.annotation
            # A field is nullable ONLY if it's Optional (has None in its union)
            # Having a default value doesn't make a field nullable
            fields[field_name] = {
                "type": self._type_to_string(field_type),
                "nullable": self._is_optional(field_type),
                "default": field_info.default if field_info.default is not ... else None,
            }

        return fields

    def _type_to_string(self, type_hint: Any) -> str:
        """Convert Python type hint to string representation."""
        if hasattr(type_hint, '__origin__'):
            origin = type_hint.__origin__
            if origin is list:
                args = type_hint.__args__
                return f"List[{self._type_to_string(args[0])}]" if args else "List"
            elif origin is dict:
                return "dict"
            elif origin is Optional:
                args = type_hint.__args__
                return self._type_to_string(args[0]) if args else "Any"
        return self.PYDANTIC_TYPE_MAP.get(type_hint, str(type_hint))

    def _is_optional(self, type_hint: Any) -> bool:
        """Check if type hint is Optional."""
        if hasattr(type_hint, '__origin__'):
            from typing import Union
            if type_hint.__origin__ is Union:
                args = type_hint.__args__
                return type(None) in args
        return False

    def compare(self, model: Type[DeclarativeBase], schema: Type[BaseModel]) -> SchemaSyncReport:
        """Compare ORM model with Pydantic schema and report drift."""
        model_name = model.__name__
        schema_name = schema.__name__

        orm_cols = self._get_orm_columns(model)
        schema_fields = self._get_schema_fields(schema)

        drifts: List[FieldDiff] = []
        migration_hints: List[str] = []
        warnings: List[str] = []

        orm_field_names = set(orm_cols.keys())
        schema_field_names = set(schema_fields.keys())

        # Check for fields in ORM but not in Schema
        for field_name in orm_field_names - schema_field_names:
            # Skip internal SQLAlchemy fields
            if field_name.startswith('_'):
                continue
            drifts.append(FieldDiff(
                drift_type=DriftType.FIELD_REMOVED,
                field_name=field_name,
                orm_type=orm_cols[field_name]["type"],
                message=f"Field '{field_name}' exists in ORM {model_name} but not in Schema {schema_name}",
            ))
            migration_hints.append(f"Add field '{field_name}' to {schema_name} schema")

        # Check for fields in Schema but not in ORM
        for field_name in schema_field_names - orm_field_names:
            drifts.append(FieldDiff(
                drift_type=DriftType.FIELD_ADDED,
                field_name=field_name,
                schema_type=schema_fields[field_name]["type"],
                message=f"Field '{field_name}' exists in Schema {schema_name} but not in ORM {model_name}",
            ))
            migration_hints.append(f"Add column '{field_name}' to {model_name} table (Alembic migration required)")

        # Check for type mismatches in common fields
        for field_name in orm_field_names & schema_field_names:
            orm_info = orm_cols[field_name]
            schema_info = schema_fields[field_name]

            # Compare types - for ORM, we consider nullable fields as Optional
            orm_type = orm_info["python_type"]
            orm_nullable = orm_info["nullable"]
            schema_type = schema_info["type"]
            schema_nullable = schema_info["nullable"]

            # Normalize types for comparison
            # If ORM field is nullable, treat it as Optional for comparison
            # If Schema field is Optional and ORM is nullable, they match if base types match
            orm_type_normalized = f"Optional[{orm_type}]" if orm_nullable else orm_type
            schema_type_normalized = schema_type  # Already includes Optional in type string

            # Direct type comparison
            types_match = orm_type == schema_type

            # Special case: ORM str/nullable=True should match Schema str | None
            if orm_nullable and schema_nullable:
                # Both are nullable, check if base types match
                base_types_match = orm_type == schema_type.replace(" | None", "")
                if base_types_match:
                    types_match = True

            # Special case: Schema uses Literal type that refines ORM str
            # This is a valid refinement, not a drift
            if "Literal" in schema_type:
                # Schema has a Literal type, which is a refinement of str
                # Check if base ORM type is str
                if orm_type == "str":
                    types_match = True  # accepted refinement

            if not types_match:
                drifts.append(FieldDiff(
                    drift_type=DriftType.TYPE_CHANGED,
                    field_name=field_name,
                    orm_type=orm_type,
                    schema_type=schema_type,
                    message=f"Type mismatch for '{field_name}': ORM={orm_type}, Schema={schema_type}",
                ))
                migration_hints.append(f"Update type for '{field_name}' in {'ORM' if schema_type == orm_type else 'Schema'}")

            # Compare nullability
            if orm_nullable != schema_nullable:
                drifts.append(FieldDiff(
                    drift_type=DriftType.NULLABILITY_CHANGED,
                    field_name=field_name,
                    orm_nullable=orm_nullable,
                    schema_nullable=schema_nullable,
                    message=f"Nullability mismatch for '{field_name}': ORM={orm_nullable}, Schema={schema_nullable}",
                ))
                warnings.append(f"Check if '{field_name}' should be nullable in both ORM and Schema")

        is_synced = len(drifts) == 0

        return SchemaSyncReport(
            model_name=model_name,
            schema_name=schema_name,
            is_synced=is_synced,
            drifts=drifts,
            warnings=warnings,
            migration_hints=migration_hints,
        )

    def validate_all(self, pairs: List[tuple]) -> List[SchemaSyncReport]:
        """Validate all ORM-Schema pairs.

        Args:
            pairs: List of (ORM model, Pydantic schema) tuples

        Returns:
            List of SchemaSyncReport for each pair
        """
        self.reports = []
        for model, schema in pairs:
            report = self.compare(model, schema)
            self.reports.append(report)

            if not report.is_synced:
                logger.warning(f"Schema drift detected: {model.__name__} <-> {schema.__name__}")
                for drift in report.drifts:
                    logger.warning(f"  - {drift.message}")

        return self.reports

    def generate_migration_script_hint(self) -> str:
        """Generate a migration script hint based on detected drifts."""
        if not self.reports:
            return "# No migration needed - schemas are in sync"

        lines = [
            "# Auto-generated migration hints from SchemaValidator",
            "# Run: alembic revision --autogenerate -m 'Sync ORM and Schema'",
            "",
            "def upgrade():",
            "    # ### commands auto generated by SchemaValidator ###",
        ]

        for report in self.reports:
            if report.is_synced:
                continue

            lines.append(f"    # For {report.model_name} / {report.schema_name}:")
            for hint in report.migration_hints:
                lines.append(f"    # HINT: {hint}")

        lines.append("    # ### end auto-generated commands ###")
        lines.append("    pass")
        lines.append("")
        lines.append("def downgrade():")
        lines.append("    # Add downgrade commands if needed")
        lines.append("    pass")

        return "\n".join(lines)


def sync_schema_validator():
    """Validate ORM-Schema synchronization for all registered pairs.

    This function is designed to be called from CI/CD or pre-commit hooks.
    Exit code 1 if drift detected, 0 if synced.
    """
    import sys

    validator = SchemaValidator()

    # Import models and schemas for validation
    from ..models import Project, Chapter, Paragraph  # type: ignore[attr-defined]
    from ..schemas import Project as ProjectSchema  # type: ignore[attr-defined]

    pairs = [
        (Project, ProjectSchema),
        # Add more pairs as needed
    ]

    reports = validator.validate_all(pairs)

    total_drifts = sum(len(r.drifts) for r in reports)
    synced_count = sum(1 for r in reports if r.is_synced)

    print(f"\n=== Schema Synchronization Report ===")
    print(f"Total pairs checked: {len(reports)}")
    print(f"In sync: {synced_count}")
    print(f"Drift detected: {len(reports) - synced_count}")
    print(f"Total drifts: {total_drifts}")

    if total_drifts > 0:
        print("\n=== Migration Hints ===")
        print(validator.generate_migration_script_hint())
        sys.exit(1)

    print("\n✓ All schemas are synchronized with ORM models")
    sys.exit(0)


if __name__ == "__main__":
    sync_schema_validator()