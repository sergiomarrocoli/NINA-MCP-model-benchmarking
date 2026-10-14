"""Flatten the tool schemas the model sees (#44).

44 of the 105 tools take one parameter, `input`, an object that holds the real arguments (the server's
functions take a single pydantic model). Small local models send the arguments flat, get a pydantic error
they do not act on, and never recover (docs/local-model.md). With `flat` schemas the model sees the arguments
at the top level and the harness wraps them back in `input` before calling the server, for every model alike.
`published` leaves the tools as the server serves them.
"""
import copy

SCHEMAS = ("flat", "published")


def is_wrapped(schema: dict) -> bool:
    """A tool whose only parameter is `input`, an object."""
    props = schema.get("properties") or {}
    return list(props) == ["input"] and props["input"].get("type") == "object" and "$ref" not in props["input"]


def flatten(name: str, description: str, schema: dict) -> tuple[str, dict, bool]:
    """Return the description and schema to show the model, and whether the tool was flattened."""
    if not is_wrapped(schema):
        return description, schema, False
    inner = copy.deepcopy(schema["properties"]["input"])
    flat = {
        "type": "object",
        "additionalProperties": False,
        "properties": inner.get("properties", {}),
        "required": inner.get("required", []),
    }
    # The argument notes the server writes sit on `input`; keep them where the model reads about the tool.
    note = inner.get("description")
    return (f"{description}\n\n{note}" if note else description), flat, True


def wrap_arguments(args: dict, flattened: bool) -> dict:
    """Arguments to send the server. A flattened tool's arguments go back inside `input`; an already wrapped call is left alone."""
    if not flattened:
        return args
    if set(args) == {"input"} and isinstance(args["input"], dict):
        return args
    return {"input": args}
