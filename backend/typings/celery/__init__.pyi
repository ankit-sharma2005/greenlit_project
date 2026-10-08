from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, overload

P = ParamSpec("P")
R = TypeVar("R")

class Celery:
    def __init__(
        self,
        main: str,
        broker: str | None = ...,
        backend: str | None = ...,
    ) -> None: ...
    @overload
    def task(self, __function: Callable[P, R], /) -> Callable[P, R]: ...
    @overload
    def task(self, **options: Any) -> Callable[[Callable[P, R]], Callable[P, R]]: ...
