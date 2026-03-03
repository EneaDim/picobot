from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, Type, TypeVar

from pydantic import BaseModel


class ToolError(Exception):
    pass


def tool_ok(data: dict | None = None, language: str | None = None) -> dict:
    """Standard tool contract wrapper."""
    return {
        "ok": True,
        "data": data or {},
        "error": None,
        "language": language,
    }


def tool_error(message: str, language: str | None = None, data: dict | None = None) -> dict:
    """Standard tool contract wrapper."""
    return {
        "ok": False,
        "data": data or {},
        "error": (message or "error"),
        "language": language,
    }


TArgs = TypeVar("TArgs", bound=BaseModel)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: Type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[dict]]

    def validate(self, args: dict) -> BaseModel:
        if not isinstance(args, dict):
            raise ToolError("tool args must be an object/dict")
        try:
            return self.schema.model_validate(args)
        except Exception as e:
            raise ToolError(str(e)) from e


class Tool(Generic[TArgs]):
    """
    Backward-compatible Tool base used by existing pytest tests:
      class EchoTool(Tool[Args]):
          async def _call(self, args: Args) -> dict: ...
    Supported schema exposure patterns (class attrs):
      - schema = Args
      - Args = Args
      - args_schema = Args
      - args_model = Args
      - Model = Args
      - inner class Args(BaseModel)
    """
    name: str = ""
    description: str = ""
    schema: Type[TArgs] | None = None

    def _resolve_schema(self):
        schema = self.schema
        if schema is None:
            schema = (
                getattr(self.__class__, "schema", None)
                or getattr(self.__class__, "Args", None)
                or getattr(self.__class__, "args_schema", None)
                or getattr(self.__class__, "args_model", None)
                or getattr(self.__class__, "Model", None)
            )
        if schema is None:
            # last resort: find exactly one BaseModel subclass defined on the class
            cands = []
            for v in self.__class__.__dict__.values():
                try:
                    if isinstance(v, type) and issubclass(v, BaseModel) and v is not BaseModel:
                        cands.append(v)
                except Exception:
                    pass
            if len(cands) == 1:
                schema = cands[0]
        return schema

    def validate(self, args: dict) -> TArgs:
        if not isinstance(args, dict):
            raise ToolError("tool args must be an object/dict")
        schema = self._resolve_schema()
        if schema is None:
            raise ToolError("tool schema is not set")
        try:
            return schema.model_validate(args)  # type: ignore[return-value]
        except Exception as e:
            raise ToolError(str(e)) from e

    async def _call(self, args: TArgs) -> dict:
        """Subclass should implement _call OR handle."""
        raise NotImplementedError

    async def handle(self, args: TArgs) -> dict:
        """Alias for subclasses that implement handle()."""
        return await self._call(args)

    async def call(self, args: dict) -> dict:
        # tests expect call()
        return await self.run(args)

    async def run(self, args: dict) -> dict:
        model = self.validate(args)
        try:
            # prefer _call if overridden
            if self.__class__._call is not Tool._call:  # type: ignore
                return await self._call(model)
            return await self.handle(model)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(str(e)) from e
