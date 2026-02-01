"""Dashboard configuration schema export functions."""

from functools import lru_cache
from typing import Any, Literal, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefinedType

from bmad_assist.core.config.models.main import Config
from bmad_assist.core.types import SecurityLevel, WidgetType

# Default security level for fields without explicit annotation
DEFAULT_SECURITY_LEVEL: SecurityLevel = "safe"


def get_field_security(
    model: type[BaseModel],
    field_name: str,
) -> SecurityLevel:
    """Get security level for a field.

    Resolution order:
    1. Field's explicit json_schema_extra["security"]
    2. Model's model_config default (not yet implemented)
    3. DEFAULT_SECURITY_LEVEL ("safe")

    Args:
        model: Pydantic model class.
        field_name: Name of the field.

    Returns:
        Security level for the field.

    Raises:
        KeyError: If field does not exist on model.

    """
    if field_name not in model.model_fields:
        raise KeyError(f"Field '{field_name}' not found on {model.__name__}")

    field_info = model.model_fields[field_name]
    extra = field_info.json_schema_extra

    if isinstance(extra, dict) and "security" in extra:
        security = extra["security"]
        if security in ("safe", "risky", "dangerous"):
            return cast(SecurityLevel, security)

    return DEFAULT_SECURITY_LEVEL


def get_field_widget(
    model: type[BaseModel],
    field_name: str,
) -> WidgetType:
    """Get UI widget type for a field.

    Resolution order:
    1. Field's explicit json_schema_extra["ui_widget"]
    2. Type-based default:
       - bool -> "toggle"
       - int/float -> "number"
       - Literal[...] -> "dropdown"
       - list[str] -> "text"
       - str -> "text"

    Args:
        model: Pydantic model class.
        field_name: Name of the field.

    Returns:
        UI widget type for the field.

    Raises:
        KeyError: If field does not exist on model.

    """
    if field_name not in model.model_fields:
        raise KeyError(f"Field '{field_name}' not found on {model.__name__}")

    field_info = model.model_fields[field_name]
    extra = field_info.json_schema_extra

    # Check explicit widget hint
    if isinstance(extra, dict) and "ui_widget" in extra:
        widget = extra["ui_widget"]
        if widget in ("checkbox_group", "toggle", "number", "dropdown", "text", "readonly"):
            return cast(WidgetType, widget)

    # Type-based defaults
    return _infer_widget_from_type(field_info)


def _infer_widget_from_type(field_info: FieldInfo) -> WidgetType:
    """Infer UI widget type from field's Python type annotation."""
    annotation = field_info.annotation

    # Handle Optional types (Union with None)
    origin = get_origin(annotation)
    if origin is type(None):
        return "text"

    # Unwrap Optional[T] to get T
    # For Union types like int | None, get the non-None type
    if hasattr(annotation, "__origin__"):
        args = get_args(annotation)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            annotation = non_none_args[0]
            origin = get_origin(annotation)

    # bool -> toggle (check before int since bool is subtype of int)
    if annotation is bool:
        return "toggle"

    # int/float -> number
    if annotation in (int, float):
        return "number"

    # Literal -> dropdown
    if origin is not None and origin is not type(None):
        # Check for Literal type
        origin_name = getattr(origin, "__name__", str(origin))
        if "Literal" in origin_name or origin is Literal:
            return "dropdown"
    elif hasattr(annotation, "__origin__"):
        origin_attr = getattr(annotation, "__origin__", None)
        if origin_attr is not None:
            origin_name = getattr(origin_attr, "__name__", str(origin_attr))
            if "Literal" in origin_name:
                return "dropdown"

    # list[str] -> text (unless checkbox_group specified)
    if origin is list:
        return "text"

    # Default to text
    return "text"


def _build_field_schema(
    field_name: str,
    field_info: FieldInfo,
    json_schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Build schema entry for a single field.

    Returns None if field has dangerous security level (excluded from schema).
    """
    extra = field_info.json_schema_extra
    security: SecurityLevel = DEFAULT_SECURITY_LEVEL
    ui_widget: WidgetType | None = None
    options: list[str] | None = None
    unit: str | None = None

    if isinstance(extra, dict):
        raw_security = extra.get("security", DEFAULT_SECURITY_LEVEL)
        if raw_security in ("safe", "risky", "dangerous"):
            security = cast(SecurityLevel, raw_security)
        raw_widget = extra.get("ui_widget")
        if raw_widget in ("checkbox_group", "toggle", "number", "dropdown", "text", "readonly"):
            ui_widget = cast(WidgetType, raw_widget)
        raw_options = extra.get("options")
        if isinstance(raw_options, list):
            options = cast(list[str], raw_options)
        raw_unit = extra.get("unit")
        if isinstance(raw_unit, str):
            unit = raw_unit

    # Exclude dangerous fields from schema entirely
    if security == "dangerous":
        return None

    # Get type info from JSON schema
    field_schema = json_schema.get("properties", {}).get(field_name, {})

    result: dict[str, Any] = {
        "type": field_schema.get("type", "string"),
        "security": security,
        "ui_widget": ui_widget or _infer_widget_from_type(field_info),
    }

    # Add optional fields (exclude PydanticUndefined for required fields)
    if (
        field_info.default is not None
        and field_info.default is not ...
        and not isinstance(field_info.default, PydanticUndefinedType)
    ):
        default_val = field_info.default
        # Convert Pydantic models to dicts for JSON serializability
        if isinstance(default_val, BaseModel):
            default_val = default_val.model_dump()
        result["default"] = default_val
    elif field_info.default_factory is not None:
        try:
            # default_factory may be a type (like list) or a callable
            factory: Any = field_info.default_factory
            default_val = factory()
            # Convert Pydantic models to dicts for JSON serializability
            if isinstance(default_val, BaseModel):
                default_val = default_val.model_dump()
            elif isinstance(default_val, dict):
                # Handle dict of Pydantic models
                default_val = {
                    k: v.model_dump() if isinstance(v, BaseModel) else v
                    for k, v in default_val.items()
                }
            result["default"] = default_val
        except Exception:
            pass

    if field_info.description:
        result["description"] = field_info.description

    if options:
        result["options"] = options

    if unit:
        result["unit"] = unit

    # Add constraints from JSON schema
    for constraint in ("minimum", "maximum", "minLength", "maxLength", "enum"):
        if constraint in field_schema:
            result[constraint] = field_schema[constraint]

    return result


def _build_model_schema(
    model: type[BaseModel],
    json_schema: dict[str, Any],
    definitions: dict[str, Any],
) -> dict[str, Any]:
    """Build schema for a Pydantic model, recursively handling nested models."""
    result: dict[str, Any] = {}

    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        is_list_of_models = False

        # Get origin for generics (list, Union, etc.)
        origin = get_origin(annotation)

        # Handle Optional[T] -> T (Union with None)
        # But NOT list[T] which also has an origin
        if origin is not None and origin is not list:
            args = get_args(annotation)
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                annotation = non_none_args[0]
                origin = get_origin(annotation)

        # Check for list[BaseModel]
        if origin is list:
            list_args = get_args(annotation)
            if list_args:
                item_type = list_args[0]
                if isinstance(item_type, type) and issubclass(item_type, BaseModel):
                    is_list_of_models = True
                    annotation = item_type

        # Check if field is a nested BaseModel
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            # Get the definition for this model
            model_name = annotation.__name__
            if model_name in definitions:
                nested_schema = definitions[model_name]
            else:
                nested_schema = annotation.model_json_schema()

            nested_result = _build_model_schema(annotation, nested_schema, definitions)
            if nested_result:  # Only add if not all fields are dangerous
                if is_list_of_models:
                    # Wrap in array schema for list[BaseModel]
                    result[field_name] = {
                        "type": "array",
                        "items": nested_result,
                    }
                else:
                    result[field_name] = nested_result
        else:
            field_schema = _build_field_schema(field_name, field_info, json_schema)
            if field_schema is not None:
                result[field_name] = field_schema

    return result


@lru_cache(maxsize=1)
def get_config_schema() -> dict[str, Any]:
    """Get configuration schema with security and UI metadata.

    Returns a nested dictionary structure matching the config hierarchy,
    with security levels and UI widget hints for each field. Fields with
    security level "dangerous" are excluded entirely.

    Returns:
        Nested dictionary with field metadata for dashboard rendering.

    Example:
        >>> schema = get_config_schema()
        >>> schema["benchmarking"]["enabled"]["security"]
        'safe'
        >>> schema["benchmarking"]["enabled"]["ui_widget"]
        'toggle'

    """
    # Get full JSON schema with definitions
    full_schema = Config.model_json_schema()
    definitions = full_schema.get("$defs", {})

    return _build_model_schema(Config, full_schema, definitions)
