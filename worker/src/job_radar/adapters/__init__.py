from .ashby import AshbyAdapter
from .base import Adapter, AdapterError, Posting
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "ashby": AshbyAdapter,
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
}

__all__ = [
    "ADAPTERS",
    "Adapter",
    "AdapterError",
    "AshbyAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "Posting",
]
