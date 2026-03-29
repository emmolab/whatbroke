import importlib
import pkgutil


def discover_checks() -> dict:
    """Auto-discover all check modules that expose a check() function."""
    checks = {}
    for module_info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{module_info.name}")
        if hasattr(mod, "check"):
            checks[module_info.name] = mod.check
    return checks
