from pydantic import BaseModel

from picobot.tools.base import ToolSpec
from picobot.tools.registry import ToolRegistry


class DummyArgs(BaseModel):
    x: int = 1


async def _dummy_handler(args: DummyArgs) -> dict:
    return {"ok": True, "data": {"x": args.x}}


def test_registry_register_and_get():
    registry = ToolRegistry()
    spec = ToolSpec(
        name="dummy",
        description="dummy tool",
        schema=DummyArgs,
        handler=_dummy_handler,
    )

    registry.register(spec, aliases=["d"])
    assert registry.has("dummy")
    assert registry.has("d")
    assert registry.resolve_name("d") == "dummy"
    assert registry.get("dummy").name == "dummy"
    assert "dummy" in registry.list()
