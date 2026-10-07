"""Detection pass registry with auto-registration decorator."""

from lost_landscapes.detection.base import DetectionPass
from lost_landscapes.utils.log_manager import log


class PassRegistry:
    """Singleton registry for detection passes."""

    _instance: "PassRegistry | None" = None
    _passes: dict[str, type[DetectionPass]] = {}

    def __new__(cls) -> "PassRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def register(cls, pass_class: type[DetectionPass]) -> type[DetectionPass]:
        """Register a detection pass class."""
        instance = pass_class()
        cls._passes[instance.name] = pass_class
        log.info("pass_registered", pass_name=instance.name, version=instance.version, pass_class=pass_class.__name__, requires_gpu=instance.requires_gpu, requires_point_cloud=instance.requires_point_cloud, required_derivatives=instance.required_derivatives)
        return pass_class

    @classmethod
    def get(cls, name: str) -> type[DetectionPass]:
        """Get a registered pass class by name."""
        if name not in cls._passes:
            available = list(cls._passes.keys())
            log.error("pass_lookup_failed", requested=name, available=available)
            raise KeyError(f"Unknown pass: {name!r}. Available: {available}")
        log.debug("pass_lookup", pass_name=name)
        return cls._passes[name]

    @classmethod
    def list_passes(cls) -> dict[str, type[DetectionPass]]:
        """Return all registered passes."""
        log.debug("list_passes", registered_count=len(cls._passes), pass_names=list(cls._passes.keys()))
        return dict(cls._passes)

    @classmethod
    def get_pass_chain(cls, names: list[str]) -> list[DetectionPass]:
        """Instantiate a chain of passes by name."""
        log.info("build_pass_chain", requested_passes=names, num_passes=len(names))
        chain = [cls.get(name)() for name in names]
        log.info("pass_chain_ready", passes=[p.name for p in chain], versions=[p.version for p in chain])
        return chain

    @classmethod
    def clear(cls) -> None:
        """Clear all registered passes. Useful for testing."""
        log.info("registry_cleared", previous_count=len(cls._passes))
        cls._passes.clear()


def register_pass(cls: type[DetectionPass]) -> type[DetectionPass]:
    """Decorator to register a detection pass at import time."""
    log.debug("register_pass_decorator", pass_class=cls.__name__)
    return PassRegistry.register(cls)
