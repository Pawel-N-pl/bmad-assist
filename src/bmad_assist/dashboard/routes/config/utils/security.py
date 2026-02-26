"""Security utilities for config route handlers.

Provides dangerous field filtering and schema introspection.
"""

import copy
from typing import Any

from bmad_assist.core.config_editor import _flatten_dict


def _get_full_schema() -> dict[str, Any]:
    """Get the full internal schema including dangerous fields.

    This schema is used internally for filtering dangerous fields from responses.
    It includes all fields, unlike get_config_schema() which excludes dangerous.

    Returns:
        Full config schema with all fields including dangerous.

    """
    # Import here to avoid circular import at module load
    import bmad_assist.dashboard.routes.config.utils as utils_module

    if utils_module._full_schema_cache is None:
        # Build full schema by extracting from Pydantic models directly
        from bmad_assist.core.config import Config

        utils_module._full_schema_cache = _build_full_schema(Config)
    return utils_module._full_schema_cache


def _build_full_schema(
    model: type,
    prefix: str = "",
    _seen: set[type] | None = None,
) -> dict[str, Any]:
    """Build full schema from Pydantic model including all security levels.

    Args:
        model: Pydantic model class.
        prefix: Path prefix for nested fields.
        _seen: Internal set of already-visited model types to prevent infinite
            recursion from self-referential types (e.g., fallbacks).

    Returns:
        Schema dict with security metadata for all fields.

    """
    from typing import get_args, get_origin

    from pydantic import BaseModel

    if _seen is None:
        _seen = set()

    result: dict[str, Any] = {}

    # Get model_fields from Pydantic model
    if not hasattr(model, "model_fields"):
        return result

    # Guard against infinite recursion from self-referential types
    if model in _seen:
        return result
    _seen.add(model)

    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        extra = field_info.json_schema_extra or {}

        # Get security level
        security = "safe"
        if isinstance(extra, dict) and "security" in extra:
            security = extra["security"]

        # Handle Optional types (Union with None)
        origin = get_origin(annotation)
        if origin is not None and origin is not list:
            args = get_args(annotation)
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                annotation = non_none_args[0]
                origin = get_origin(annotation)

        # Check for list[BaseModel]
        is_list_of_models = False
        if origin is list:
            list_args = get_args(annotation)
            if list_args:
                item_type = list_args[0]
                if isinstance(item_type, type) and issubclass(item_type, BaseModel):
                    is_list_of_models = True
                    annotation = item_type

        # Check if field is a nested BaseModel
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            nested = _build_full_schema(annotation, f"{prefix}{field_name}.", _seen)
            if is_list_of_models:
                result[field_name] = {
                    "type": "array",
                    "items": nested,
                    "security": security,
                }
            else:
                # For nested models, add security at this level and recurse
                result[field_name] = nested
        else:
            result[field_name] = {"security": security}

    return result


def _filter_dangerous_fields(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove dangerous fields from config data.

    Args:
        data: Configuration data dictionary.
        schema: Full schema with security metadata.

    Returns:
        Deep copy of data with dangerous fields removed.

    """
    result = copy.deepcopy(data)
    _filter_dangerous_recursive(result, schema)
    return result


def _filter_dangerous_recursive(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Recursively filter dangerous fields in-place.

    Args:
        data: Configuration data dictionary (modified in place).
        schema: Schema with security metadata.

    """
    keys_to_remove = []

    for key in list(data.keys()):
        if key not in schema:
            continue

        field_schema = schema[key]

        # Check if this field is dangerous
        if isinstance(field_schema, dict):
            if field_schema.get("security") == "dangerous":
                keys_to_remove.append(key)
            elif isinstance(data[key], dict):
                # Could be nested object or provenance-wrapped value
                if "value" in data[key] and "source" in data[key]:
                    # Provenance-wrapped value - check if it's an array
                    if field_schema.get("type") == "array":
                        raw_list = data[key].get("value", [])
                        if isinstance(raw_list, list):
                            items_schema = field_schema.get("items", {})
                            for item in raw_list:
                                if isinstance(item, dict):
                                    _filter_dangerous_recursive(item, items_schema)
                    # For non-array wrapped values, nothing to filter recursively
                elif "security" not in field_schema:
                    # Nested object without provenance wrapper - recurse
                    _filter_dangerous_recursive(data[key], field_schema)
            elif field_schema.get("type") == "array" and isinstance(data[key], list):
                # Raw array (not wrapped in provenance) - used by _add_provenance_to_raw
                items_schema = field_schema.get("items", {})
                for item in data[key]:
                    if isinstance(item, dict):
                        _filter_dangerous_recursive(item, items_schema)

    for key in keys_to_remove:
        del data[key]


def _check_risky_fields(paths: list[str], schema: dict[str, Any]) -> list[str]:
    """Check which paths contain RISKY fields.

    Args:
        paths: List of dot-notation paths to check.
        schema: Full schema with security metadata.

    Returns:
        List of paths that are RISKY fields.

    """
    risky = []
    for path in paths:
        security = _get_field_security(path, schema)
        if security == "risky":
            risky.append(path)
    return risky


def _get_field_security(path: str, schema: dict[str, Any]) -> str:
    """Get security level for a field path.

    Args:
        path: Dot-notation path (e.g., "providers.master.model").
        schema: Full schema with security metadata.

    Returns:
        Security level: "safe", "risky", or "dangerous".

    """
    parts = path.split(".")
    current = schema

    for i, part in enumerate(parts):
        if not isinstance(current, dict) or part not in current:
            return "safe"  # Unknown fields default to safe

        field_info = current[part]

        if not isinstance(field_info, dict):
            return "safe"

        # If this is the last part, return its security
        if i == len(parts) - 1:
            security = field_info.get("security", "safe")
            return str(security) if security else "safe"

        # Handle arrays
        if field_info.get("type") == "array":
            current = field_info.get("items", {})
        elif "security" in field_info:
            # Leaf field, but we need to go deeper - path is invalid
            return "safe"
        else:
            # Nested object
            current = field_info

    return "safe"


def _find_dangerous_fields(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Find fields with security='dangerous' in config data.

    Args:
        data: Config dict to scan (can be nested).
        schema: Full schema with security metadata.

    Returns:
        List of dot-notation paths to dangerous fields found in data.

    """
    dangerous = []
    flat_data = _flatten_dict(data)

    for path in flat_data:
        # Check schema for this path's security level
        security = _get_field_security(path, schema)
        if security == "dangerous":
            dangerous.append(path)

    return dangerous


def _filter_dangerous_fields_for_export(
    data: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    """Recursively remove dangerous fields from config data for export.

    Unlike _filter_dangerous_fields which works with provenance-wrapped data,
    this function works with raw config data (no provenance wrappers).

    Args:
        data: Raw configuration data dictionary.
        schema: Full schema with security metadata.

    Returns:
        Deep copy of data with dangerous fields removed.

    """
    result = copy.deepcopy(data)
    _filter_dangerous_for_export_recursive(result, schema)
    return result


def _filter_dangerous_for_export_recursive(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Recursively filter dangerous fields in-place for export.

    Args:
        data: Configuration data dictionary (modified in place).
        schema: Schema with security metadata.

    """
    keys_to_remove = []

    for key in list(data.keys()):
        if key not in schema:
            continue

        field_schema = schema[key]

        # Check if this field is dangerous
        if isinstance(field_schema, dict):
            if field_schema.get("security") == "dangerous":
                keys_to_remove.append(key)
            elif isinstance(data[key], dict):
                # Nested object - always recurse to find nested dangerous fields
                # even if parent has a security level (e.g., "risky" parent may have "dangerous" children) # noqa: E501
                _filter_dangerous_for_export_recursive(data[key], field_schema)
            elif field_schema.get("type") == "array" and isinstance(data[key], list):
                # Array type - filter items
                items_schema = field_schema.get("items", {})
                for item in data[key]:
                    if isinstance(item, dict):
                        _filter_dangerous_for_export_recursive(item, items_schema)

    for key in keys_to_remove:
        del data[key]
