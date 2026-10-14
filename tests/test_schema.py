from types import SimpleNamespace

from harness.run import openai_tools
from harness.schema import flatten, wrap_arguments

MOVE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"input": {
        "description": "FocuserMoveInput containing:\nposition: Target position in steps",
        "type": "object",
        "properties": {"position": {"type": "integer"}, "relative": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None}},
        "required": ["position"],
    }},
    "required": ["input"],
}
NO_ARGS = {"type": "object", "properties": {}}


def tool(name, schema, description="Does a thing."):
    return SimpleNamespace(name=name, description=description, input_schema=schema)


def test_the_input_wrapper_is_lifted_and_its_notes_kept():
    description, schema, flattened = flatten("nina_move_focuser", "Move the focuser.", MOVE)
    assert flattened and list(schema["properties"]) == ["position", "relative"] and schema["required"] == ["position"]
    assert "position: Target position in steps" in description and description.startswith("Move the focuser.")
    assert MOVE["properties"]["input"]["required"] == ["position"]  # the server's schema is not modified


def test_tools_without_an_input_wrapper_are_left_alone():
    assert flatten("nina_get_focuser_info", "Info.", NO_ARGS) == ("Info.", NO_ARGS, False)
    flat = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
    assert flatten("t", "d", flat)[2] is False


def test_all_optional_arguments_flatten_to_no_required_fields():
    schema = {"type": "object", "properties": {"input": {"type": "object", "properties": {"id": {"type": "string"}}}}, "required": ["input"]}
    assert flatten("nina_connect_camera", "d", schema)[1]["required"] == []


def test_arguments_are_wrapped_back_for_flattened_tools_only():
    assert wrap_arguments({"position": 25500}, True) == {"input": {"position": 25500}}
    assert wrap_arguments({}, True) == {"input": {}}
    assert wrap_arguments({"position": 25500}, False) == {"position": 25500}


def test_an_already_wrapped_call_is_accepted():
    assert wrap_arguments({"input": {"position": 25500}}, True) == {"input": {"position": 25500}}


def test_openai_tools_flat_and_published():
    tools = [tool("nina_move_focuser", MOVE), tool("nina_get_focuser_info", NO_ARGS)]
    flat, names = openai_tools(tools, "flat")
    assert names == {"nina_move_focuser"} and "position" in flat[0]["function"]["parameters"]["properties"]
    published, names = openai_tools(tools, "published")
    assert names == set() and published[0]["function"]["parameters"] is MOVE
