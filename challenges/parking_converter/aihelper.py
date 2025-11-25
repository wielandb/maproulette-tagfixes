import json
import html
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None

import free_tokens

# Stored prompt that contains the full conversion instructions.
PROMPT_ID = "pmpt_6925be968e748195babcc1d805bee80f09ae5139be5c5a16"
PROMPT_VERSION = "2"

# Prefer small (free) models first, then fall back to larger ones if tokens remain.
DEFAULT_MODEL_ORDER = [
    "gpt-5-mini",
    "gpt-5.1"
]

# Structured output schema expected from the prompt (identical to the example from the
# playground). This keeps the model response predictable.
STRUCTURED_TEXT_SCHEMA: Dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "osm_tag_edits",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "error": {"type": "boolean"},
                "errorMessage": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "operations": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {"$ref": "#/$defs/ModifyElementOperation"},
                        },
                        {"type": "null"},
                    ]
                },
            },
            "required": ["error", "errorMessage", "operations"],
            "$defs": {
                "OsmElementId": {
                    "type": "string",
                    "description": "OSM Element-ID im Format 'node/123', 'way/123', 'relation/123'.",
                },
                "TagPair": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                    "required": ["key", "value"],
                },
                "SetTagsOperation": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "operation": {"type": "string", "enum": ["setTags"]},
                        "data": {"type": "array", "items": {"$ref": "#/$defs/TagPair"}},
                    },
                    "required": ["operation", "data"],
                },
                "UnsetTagsOperation": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "operation": {"type": "string", "enum": ["unsetTags"]},
                        "data": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["operation", "data"],
                },
                "TagOperations": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "setTags": {"$ref": "#/$defs/SetTagsOperation"},
                        "unsetTags": {"$ref": "#/$defs/UnsetTagsOperation"},
                    },
                    "required": ["setTags", "unsetTags"],
                },
                "ModifyElementData": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"$ref": "#/$defs/OsmElementId"},
                        "operations": {"$ref": "#/$defs/TagOperations"},
                    },
                    "required": ["id", "operations"],
                },
                "ModifyElementOperation": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "operationType": {"type": "string", "enum": ["modifyElement"]},
                        "data": {"$ref": "#/$defs/ModifyElementData"},
                    },
                    "required": ["operationType", "data"],
                },
            },
        },
    },
    "verbosity": "medium",
}


def _escape(val: Any) -> str:
    """Escape values for inclusion in the XML snippet sent to the model."""
    return html.escape(str(val), quote=True)


def _osm_id_from_element(element: Dict[str, Any]) -> Optional[str]:
    osm_type = element.get("type")
    osm_id = element.get("id")
    if osm_type and osm_id is not None:
        return f"{osm_type}/{osm_id}"
    return None


def _element_to_input_text(element: Union[str, Dict[str, Any]]) -> str:
    """
    Render the provided element into a compact OSM-like XML string the prompt expects.
    Strings are passed through unchanged to allow callers to hand in custom text.
    """
    if isinstance(element, str):
        return element

    element_type = element.get("type", "way")
    osm_id = element.get("id", "0")
    tags = element.get("tags", {})

    lines = [
        "This XML file does not appear to have any style information associated with it. The document tree is shown below.",
        '<osm version="0.6">',
        f'<{_escape(element_type)} id="{_escape(osm_id)}" visible="true">',
    ]
    for key, value in sorted(tags.items()):
        lines.append(f'<tag k="{_escape(key)}" v="{_escape(value)}"/>')
    lines.append(f"</{_escape(element_type)}>")
    lines.append("</osm>")
    return "\n".join(lines)


def _extract_json_from_response(response: Any) -> Dict[str, Any]:
    """Pull the JSON string from a Responses API object and parse it."""
    # Preferred path: aggregated text property.
    text_blob = getattr(response, "output_text", None)

    # Fallbacks for older/alternate SDK layouts.
    if not text_blob and hasattr(response, "output"):
        for output_item in getattr(response, "output", []):
            contents = getattr(output_item, "content", None) or getattr(
                output_item, "contents", None
            )
            if not contents:
                continue
            for content in contents:
                text_blob = getattr(content, "text", None) or (
                    content.get("text") if isinstance(content, dict) else None
                )
                if text_blob:
                    break
            if text_blob:
                break

    if not text_blob and hasattr(response, "choices"):
        # Very defensive: handle chat-like objects if the SDK changes again.
        choices = getattr(response, "choices", [])
        if choices:
            choice = choices[0]
            message = getattr(choice, "message", None) or choice.get("message", {})
            if message:
                text_blob = message.get("content")

    if not text_blob:
        raise ValueError("AI response did not contain any text payload to parse.")

    return json.loads(text_blob)


def _convert_tag_pairs_to_dict(tag_pairs: Iterable[Dict[str, str]]) -> Dict[str, str]:
    """Convert [{'key': 'a', 'value': 'b'}] into {'a': 'b'}."""
    converted: Dict[str, str] = {}
    for pair in tag_pairs:
        key = pair.get("key")
        value = pair.get("value")
        if key is None or value is None:
            continue
        converted[str(key)] = str(value)
    return converted


def _ai_payload_to_maproulette(
    ai_payload: Dict[str, Any], fallback_element: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Convert the structured AI output into the MapRoulette cooperative-work format.

    The only transformation needed is turning the list of key/value pairs from the
    structured output into a plain tag dictionary.
    """
    if not ai_payload or ai_payload.get("error"):
        return None

    operations_in = ai_payload.get("operations") or []
    if not isinstance(operations_in, list):
        return None

    operations_out: List[Dict[str, Any]] = []
    for operation in operations_in:
        if operation.get("operationType") != "modifyElement":
            continue
        data = operation.get("data") or {}
        element_id = data.get("id") or (
            _osm_id_from_element(fallback_element or {}) if fallback_element else None
        )
        tag_ops = data.get("operations") or {}
        set_tags_block = tag_ops.get("setTags") or {}
        unset_tags_block = tag_ops.get("unsetTags") or {}

        set_data = set_tags_block.get("data") or []
        if isinstance(set_data, list):
            set_tags = _convert_tag_pairs_to_dict(set_data)
        elif isinstance(set_data, dict):
            set_tags = set_data
        else:
            set_tags = {}

        unset_tags = unset_tags_block.get("data") or []
        if not isinstance(unset_tags, list):
            unset_tags = []

        if not element_id:
            continue

        operations_out.append(
            {
                "operationType": "modifyElement",
                "data": {
                    "id": element_id,
                    "operations": [
                        {"operation": "setTags", "data": set_tags},
                        {"operation": "unsetTags", "data": unset_tags},
                    ],
                },
            }
        )

    if not operations_out:
        return None

    return {"meta": {"version": 2, "type": 1}, "operations": operations_out}


def _record_token_usage(response: Any, model: str) -> None:
    """Persist token usage so the free-token quota tracking stays accurate."""
    usage = getattr(response, "usage", None)
    if not usage:
        return
    total_tokens = getattr(usage, "total_tokens", None)
    if total_tokens is None and isinstance(usage, dict):
        total_tokens = usage.get("total_tokens")
    if total_tokens:
        free_tokens.add_to_today_tokens(int(total_tokens), model)


def request_ai_parking_conversion(
    element: Union[str, Dict[str, Any]],
    model_order: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Ask the AI (using only the free-token models) to convert old parking tags.

    Parameters
    ----------
    element: dict or str
        Either an OSM element dict with at least ``type``, ``id`` and ``tags`` or a
        raw text blob to feed directly into the prompt.
    model_order: list[str], optional
        Preferred models; defaults to ``DEFAULT_MODEL_ORDER``.

    Returns
    -------
    tuple
        (maproulette_operations, ai_raw_payload). The first entry is ready for
        MapRoulette's cooperative work. Both entries are ``None`` when no model with
        free tokens is available or the response could not be parsed.
    """
    if OpenAI is None:
        raise ImportError("The openai package is not installed.")

    preferred_models = model_order or DEFAULT_MODEL_ORDER
    model = free_tokens.get_model_with_kontingent_from_list(preferred_models)
    if not model:
        return None, None

    client = OpenAI()
    input_text = _element_to_input_text(element)

    try:
        response = client.responses.create(
            model=model,
            prompt={"id": PROMPT_ID, "version": PROMPT_VERSION},
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": input_text}],
                }
            ],
            text=STRUCTURED_TEXT_SCHEMA,
            reasoning={"summary": "auto"},
        )
    except Exception:
        # Keep the caller in control; simply signal failure.
        return None, None

    _record_token_usage(response, model)

    try:
        ai_payload = _extract_json_from_response(response)
    except Exception:
        return None, None

    maproulette_ops = _ai_payload_to_maproulette(
        ai_payload, fallback_element=element if isinstance(element, dict) else None
    )
    return maproulette_ops, ai_payload
