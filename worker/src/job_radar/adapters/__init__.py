from .ashby import AshbyAdapter
from .base import Adapter, AdapterError, Posting
from .greenhouse import GreenhouseAdapter
from .lever import LeverAdapter
from .recruitee import RecruiteeAdapter
from .workable import WorkableAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    "ashby": AshbyAdapter,
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "recruitee": RecruiteeAdapter,
    "workable": WorkableAdapter,
}

__all__ = [
    "ADAPTERS",
    "Adapter",
    "AdapterError",
    "AshbyAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
    "Posting",
    "RecruiteeAdapter",
    "WorkableAdapter",
]
