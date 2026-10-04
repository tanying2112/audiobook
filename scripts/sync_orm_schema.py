"""ORM to Pydantic Schema Auto-Sync Tool.

Automatically generates Pydantic schemas from SQLAlchemy ORM models,
eliminating manual duplication and ensuring type consistency.

Usage:
    python scripts/sync_orm_schema.py [--dry-run] [--model ModelName]
"""

import argparse
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class ModelField:
    """Represents a single field in an ORM model."""

    name: str
    field_type: str
    is_optional: bool
    has_default: bool
    default_value: Optional[str]
    nullable: bool
    doc: str = ""


@dataclass
class ORMModel:
    """Represents a complete ORM model."""

    name: str
    tablename: Optional[str]
    fields: List[ModelField] = field(default_factory=list)


@dataclass
class SchemaResult:
    """Result of schema generation."""

    model_name: str
    input_schema: str
    output_schema: str
    changes: List[str] = field(default_factory=list)


# Type mapping from SQLAlchemy to Python/Pydantic
SA_TYPE_MAP = {
    "Integer": "int",
    "BigInteger": "int",
    "SmallInteger": "int",
    "Float": "float",
    "Numeric": "float",
    "String": "str",
    "Text": "str",
    "Boolean": "bool",
    "DateTime": "datetime",
    "Date": "date",
    "Time": "time",
    "JSON": "Dict[str, Any]",
    "ARRAY": "List",
    "Enum": "str",
    "UUID": "UUID",
}

# Fields to exclude from input schemas (internal/bookkeeping)
EXCLUDED_FIELDS = {
    "created_at",
    "updated_at",
    "deleted_at",  # Timestamps
}


class ORMSchemaExtractor:
    """Extract schema information from SQLAlchemy ORM models."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self.models: Dict[str, ORMModel] = {}

    def extract_all(self) -> Dict[str, ORMModel]:
        """Extract all ORM models from the models directory."""
        for model_file in self.models_dir.glob("*.py"):
            if model_file.name.startswith("_"):
                continue

            content = model_file.read_text(encoding="utf-8")
            models = self._parse_model_file(content, model_file.name)
            self.models.update(models)

        return self.models

    def _parse_model_file(self, content: str, filename: str) -> Dict[str, ORMModel]:
        """Parse a Python file and extract ORM model definitions."""
        models = {}
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check if it's a SQLAlchemy model (has __tablename__)
                if self._has_tablename(node):
                    model = self._extract_model(node)
                    model.tablename = self._get_tablename(node)
                    models[model.name] = model

        return models

    def _has_tablename(self, class_node: ast.ClassDef) -> bool:
        """Check if a class is a SQLAlchemy model."""
        for item in class_node.body:
            if isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name) and item.target.id == "__tablename__":
                    return True
            # Also check for Base inheritance
            for base in class_node.bases:
                if isinstance(base, ast.Name) and base.id == "Base":
                    return True
        return False

    def _get_tablename(self, class_node: ast.ClassDef) -> Optional[str]:
        """Extract the __tablename__ value."""
        for item in class_node.body:
            if isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name) and item.target.id == "__tablename__":
                    if isinstance(item.value, ast.Constant):
                        return item.value.value
        return None

    def _extract_model(self, class_node: ast.ClassDef) -> ORMModel:
        """Extract field information from a model class."""
        model = ORMModel(name=class_node.name, tablename=None)

        for item in class_node.body:
            if isinstance(item, ast.AnnAssign):
                field_info = self._extract_field(item)
                if field_info:
                    model.fields.append(field_info)
            elif isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant):
                # Docstring
                if item.value.value and isinstance(item.value.value, str):
                    pass  # We could add class docstring here

        return model

    def _extract_field(self, node: ast.AnnAssign) -> Optional[ModelField]:
        """Extract field information from an annotated assignment."""
        if not isinstance(node.target, ast.Name):
            return None

        name = node.target.id
        if name.startswith("_") or name in EXCLUDED_FIELDS:
            return None

        # Get type annotation
        field_type = "Any"
        is_optional = False
        has_default = False
        default_value = None
        nullable = False

        if node.annotation:
            annotation_str = ast.unparse(node.annotation)
            field_type = annotation_str

            # Handle Mapped[Optional[...]] and Optional[...]
            if "Optional" in annotation_str:
                is_optional = True
                nullable = True
                # Extract inner type
                match = re.search(r"Mapped\[Optional\[([^\]]+)\]\]", annotation_str)
                if not match:
                    match = re.search(r"Optional\[([^\]]+)\]", annotation_str)
                if match:
                    field_type = match.group(1)
            elif "Mapped[" in annotation_str:
                match = re.search(r"Mapped\[([^\]]+)\]", annotation_str)
                if match:
                    field_type = match.group(1)

        if node.value:
            has_default = True
            default_value = ast.unparse(node.value)
            if "nullable=True" in default_value:
                nullable = True

        return ModelField(
            name=name,
            field_type=field_type,
            is_optional=is_optional,
            has_default=has_default,
            default_value=default_value,
            nullable=nullable,
        )


class PydanticSchemaGenerator:
    """Generate Pydantic schemas from ORM models."""

    def __init__(self, models: Dict[str, ORMModel]):
        self.models = models

    def generate_input_schema(self, model_name: str) -> str:
        """Generate Pydantic Input schema for a model."""
        model = self.models.get(model_name)
        if not model:
            return ""

        # Collect relationship types to exclude them from input
        relationship_types = set()
        for f in model.fields:
            if "List[" in f.field_type or f.field_type in [
                "AudioSegment",
                "TTSEdit",
                "Routing",
                "Quality",
                "FeedbackRecord",
                "Chapter",
                "Paragraph",
            ]:
                relationship_types.add(f.name)

        lines = [
            f'"""Auto-generated Pydantic Input schema for {model_name}."""',
            "",
            "from datetime import datetime",
            "from typing import Any, Dict, List, Optional",
            "from uuid import UUID",
            "",
            "from pydantic import BaseModel, Field, field_validator",
            "",
            "",
            f"class {model_name}Input(BaseModel):",
            f'    """Input schema for {model_name} operations."""',
            "",
        ]

        for f in model.fields:
            if f.name in EXCLUDED_FIELDS:
                continue
            # Skip relationships in input schema
            if f.name in relationship_types:
                continue

            # Build field definition
            py_type = self._sa_to_python_type(f.field_type)

            # Handle JSON type specially
            if "Dict[str, Any]" in py_type or "List[" in py_type:
                optional_marker = "Optional["
                close_bracket = "]"
            elif f.is_optional or f.nullable:
                optional_marker = "Optional["
                close_bracket = "]"
            else:
                optional_marker = ""
                close_bracket = ""

            field_def = f"    {f.name}: {optional_marker}{py_type}{close_bracket}"

            # Add Field() with description and default
            field_args = []
            if f.name == "text" or "text" in f.name.lower():
                field_args.append('description="Text content"')
            if f.name == "id":
                field_args.append('description="Unique identifier"')

            # Handle default value
            has_valid_default = False
            if f.has_default and f.default_value:
                default, has_valid_default = self._clean_default(f.default_value)
                if default.startswith("Field("):
                    field_args.append(default)
                    has_valid_default = True
                elif default and default != "None":
                    field_args.append(f"default={default}")
                    has_valid_default = True
                else:
                    has_valid_default = True  # Explicit None is still a default

            # Determine if field is required
            is_required = not (f.is_optional or f.nullable or has_valid_default)

            if is_required:
                field_args.append("...")

            field_def += f' = Field({", ".join(field_args)})'
            lines.append(field_def)

        lines.append("")
        return "\n".join(lines)

    def generate_output_schema(self, model_name: str) -> str:
        """Generate Pydantic Output schema for a model."""
        model = self.models.get(model_name)
        if not model:
            return ""

        # Collect relationship types to exclude them from output
        relationship_types = set()
        for f in model.fields:
            if "List[" in f.field_type:
                relationship_types.add(f.name)
            elif f.field_type in [
                "AudioSegment",
                "TTSEdit",
                "Routing",
                "Quality",
                "FeedbackRecord",
                "Chapter",
                "Paragraph",
            ]:
                relationship_types.add(f.name)

        lines = [
            f'"""Auto-generated Pydantic Output schema for {model_name}."""',
            "",
            "from datetime import datetime",
            "from typing import Any, Dict, List, Optional",
            "from uuid import UUID",
            "",
            "from pydantic import BaseModel, Field",
            "",
            "",
            f"class {model_name}Output(BaseModel):",
            f'    """Output schema for {model_name} operations."""',
            "",
            "    class Config:",
            "        from_attributes = True  # For ORM compatibility",
            "",
        ]

        # Output schemas typically include all fields including ID
        for f in model.fields:
            # Skip relationships in output schema
            if f.name in relationship_types:
                continue

            py_type = self._sa_to_python_type(f.field_type)

            # Handle JSON type specially
            if "Dict[str, Any]" in py_type or "List[" in py_type:
                optional_marker = "Optional["
                close_bracket = "]"
            elif f.nullable or f.is_optional:
                optional_marker = "Optional["
                close_bracket = "]"
            else:
                optional_marker = ""
                close_bracket = ""

            field_def = f"    {f.name}: {optional_marker}{py_type}{close_bracket}"

            field_args = []
            if f.has_default and f.default_value:
                default, has_default = self._clean_default(f.default_value)
                if has_default:
                    if default.startswith("Field("):
                        field_args.append(default)
                    elif default and default != "None":
                        field_args.append(f"default={default}")

            if field_args:
                field_def += f' = Field({", ".join(field_args)})'

            lines.append(field_def)

        lines.append("")
        return "\n".join(lines)

    def _sa_to_python_type(self, sa_type: str) -> str:
        """Convert SQLAlchemy type to Python type."""
        # Handle Mapped[] wrapper
        sa_type = re.sub(r"Mapped\[([^\]]+)\]", r"\1", sa_type)

        for sa, py in SA_TYPE_MAP.items():
            sa_type = sa_type.replace(sa, py)

        return sa_type

    def _clean_default(self, default: str) -> tuple[str, bool]:
        """Clean up default value for Pydantic schema.

        Returns:
            Tuple of (cleaned_value, has_valid_default)
        """
        # Remove mapped_column(...) wrapper
        default = re.sub(r"mapped_column\([^)]*\)", "", default)

        # Extract default value
        if "default=" in default:
            match = re.search(r"default=([^,)]+)", default)
            if match:
                default = match.group(1).strip()
            else:
                default = default.replace("default=", "").strip()
        else:
            return ("", False)

        # Handle lambda defaults
        if "lambda" in default:
            return ("None", True)

        # Handle common patterns
        if default == "list":
            return ("Field(default_factory=list)", True)
        if default == "dict":
            return ("Field(default_factory=dict)", True)
        if default == "None":
            return ("None", True)
        if default == "True":
            return ("True", True)
        if default == "False":
            return ("False", True)
        if default == "0":
            return ("0", True)
        if default == "0.0":
            return ("0.0", True)
        if default == '""':
            return ('""', True)

        # Try to parse as number
        try:
            float(default)
            return (default, True)
        except ValueError:
            pass

        # Unknown pattern - treat as no default
        return ("", False)


class SchemaSyncTool:
    """Main orchestration for ORM-Schema sync."""

    def __init__(self, models_dir: Path, schemas_dir: Path, dry_run: bool = False):
        self.models_dir = models_dir
        self.schemas_dir = schemas_dir
        self.dry_run = dry_run
        self.extractor = ORMSchemaExtractor(models_dir)
        self.results: List[SchemaResult] = []

    def run(self) -> List[SchemaResult]:
        """Run the sync process."""
        print("=" * 60)
        print("ORM-Schema Auto-Sync Tool")
        print("=" * 60)
        print()

        # Extract models
        print("Extracting ORM models...")
        models = self.extractor.extract_all()
        print(f"  Found {len(models)} models: {list(models.keys())}")
        print()

        # Generate schemas
        generator = PydanticSchemaGenerator(models)

        for model_name in models:
            print(f"Generating schemas for {model_name}...")
            input_schema = generator.generate_input_schema(model_name)
            output_schema = generator.generate_output_schema(model_name)

            result = SchemaResult(
                model_name=model_name,
                input_schema=input_schema,
                output_schema=output_schema,
                changes=[],
            )

            if not self.dry_run:
                # Write to files
                input_path = self.schemas_dir / f"{model_name.lower()}_auto.py"
                output_path = self.schemas_dir / f"{model_name.lower()}_output_auto.py"

                input_path.write_text(input_schema, encoding="utf-8")
                output_path.write_text(output_schema, encoding="utf-8")

                result.changes.append(f"Created: {input_path}")
                result.changes.append(f"Created: {output_path}")

            self.results.append(result)
            print(f"  ✓ {model_name}")

        print()
        print("=" * 60)
        print(f"Generated schemas for {len(self.results)} models")
        if self.dry_run:
            print("(Dry run - no files written)")
        print("=" * 60)

        return self.results


def main():
    parser = argparse.ArgumentParser(description="Sync ORM models to Pydantic schemas")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument("--models-dir", type=str, default="src/audiobook_studio/models")
    parser.add_argument("--schemas-dir", type=str, default="src/audiobook_studio/schemas/auto")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    models_dir = root / args.models_dir
    schemas_dir = root / args.schemas_dir

    schemas_dir.mkdir(parents=True, exist_ok=True)

    tool = SchemaSyncTool(models_dir, schemas_dir, dry_run=args.dry_run)
    tool.run()


if __name__ == "__main__":
    main()
