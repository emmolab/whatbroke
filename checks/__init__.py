# System health checks live here
import importlib
import pkgutil

def discover_checks():
    checks = {}

    for module in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{module.name}")
        if hasattr(mod, "check"):
            checks[module.name] = mod.check

    return checks
