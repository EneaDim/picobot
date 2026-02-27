import pytest
from pydantic import BaseModel

from picobot.tools.base import Tool, ToolError


class Args(BaseModel):
    q: str


class EchoTool(Tool[Args]):
    name = "echo"
    description = "echo"
    args_model = Args

    async def _call(self, args: Args) -> str:
        return args.q


@pytest.mark.asyncio
async def test_tool_validation_ok():
    t = EchoTool()
    out = await t.call({"q": "hi"})
    assert out == "hi"


@pytest.mark.asyncio
async def test_tool_validation_rejects():
    t = EchoTool()
    with pytest.raises(ToolError):
        await t.call({"wrong": 1})
