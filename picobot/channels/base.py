from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable

StatusCb = Callable[[str], Awaitable[None]]


class Channel(ABC):
    @abstractmethod
    async def run(self) -> None: ...
