import importlib
import pkgutil
from typing import List

from plugins.base_plugin import BasePlugin

class PluginManager:
    def __init__(self):
        self.plugins: List[BasePlugin] = []

    def discover(self):
        # Scan plugins package for modules with register()
        try:
            import plugins
        except Exception:
            return
        for m in pkgutil.iter_modules(plugins.__path__):
            if m.name.startswith('_'):
                continue
            try:
                module = importlib.import_module(f'plugins.{m.name}')
                if hasattr(module, 'register'):
                    plugin = module.register()
                    if isinstance(plugin, BasePlugin):
                        self.plugins.append(plugin)
            except Exception:
                # Don't crash on a bad plugin; continue
                continue

    def get_plugins(self) -> List[BasePlugin]:
        return list(self.plugins)

    def get_enabled(self) -> List[BasePlugin]:
        return [p for p in self.plugins if getattr(p, 'enabled', False)]
