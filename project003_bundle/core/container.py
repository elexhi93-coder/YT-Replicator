"""
Dependency Injection Container for IDM-YT
Provides centralized dependency management for better testability and loose coupling.
"""

from typing import TypeVar, Type, Dict, Any, Optional, Callable, Union
from dataclasses import dataclass
from pathlib import Path
import threading
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ContainerError(Exception):
    """Raised when container operations fail"""
    pass


class ServiceLifetime:
    """Service lifetime options"""
    TRANSIENT = "transient"    # New instance every time
    SINGLETON = "singleton"    # Single instance for app lifetime
    SCOPED = "scoped"          # Single instance per scope


@dataclass
class ServiceDescriptor:
    """Describes a registered service"""
    service_type: Type
    implementation: Union[Type, Callable, Any]
    lifetime: str
    instance: Any = None


class Container:
    """
    Simple dependency injection container.
    
    Features:
    - Singleton and transient lifetimes
    - Factory functions
    - Interface-to-implementation mapping
    - Automatic dependency resolution
    
    Usage:
        container = Container()
        
        # Register singleton
        container.register_singleton(PluginManager, PluginManager())
        
        # Register with factory
        container.register_factory(DownloadManager, lambda c: DownloadManager(c.resolve(AppConfig)))
        
        # Register interface -> implementation
        container.register(IDownloadService, DownloadManager)
        
        # Resolve
        manager = container.resolve(DownloadManager)
    """
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._lock = threading.RLock()
    
    def register(
        self,
        service_type: Type[T],
        implementation: Union[Type[T], Callable[['Container'], T]] = None,
        lifetime: str = ServiceLifetime.TRANSIENT
    ) -> 'Container':
        """
        Register a service with the container.
        
        Args:
            service_type: The type to register (interface or class)
            implementation: The implementation class or factory function
            lifetime: Service lifetime (transient or singleton)
            
        Returns:
            Self for chaining
        """
        impl = implementation or service_type
        
        with self._lock:
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                implementation=impl,
                lifetime=lifetime,
            )
        
        logger.debug(f"Registered {service_type.__name__} ({lifetime})")
        return self
    
    def register_singleton(self, service_type: Type[T], instance: T = None) -> 'Container':
        """
        Register a singleton service.
        
        Args:
            service_type: The type to register
            instance: Optional pre-created instance
        """
        with self._lock:
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                implementation=service_type if instance is None else instance,
                lifetime=ServiceLifetime.SINGLETON,
                instance=instance,
            )
        
        logger.debug(f"Registered singleton {service_type.__name__}")
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'Container':
        """
        Register an existing instance as singleton.
        
        Args:
            service_type: The type to register
            instance: The instance to use
        """
        return self.register_singleton(service_type, instance)
    
    def register_factory(
        self,
        service_type: Type[T],
        factory: Callable[['Container'], T],
        lifetime: str = ServiceLifetime.TRANSIENT
    ) -> 'Container':
        """
        Register a factory function for creating instances.
        
        Args:
            service_type: The type to register
            factory: Function that takes Container and returns instance
            lifetime: Service lifetime
        """
        with self._lock:
            self._services[service_type] = ServiceDescriptor(
                service_type=service_type,
                implementation=factory,
                lifetime=lifetime,
            )
        
        logger.debug(f"Registered factory for {service_type.__name__}")
        return self
    
    def resolve(self, service_type: Type[T]) -> T:
        """
        Resolve a service from the container.
        
        Args:
            service_type: The type to resolve
            
        Returns:
            An instance of the requested type
            
        Raises:
            ContainerError: If service is not registered
        """
        with self._lock:
            if service_type not in self._services:
                raise ContainerError(f"Service not registered: {service_type.__name__}")
            
            descriptor = self._services[service_type]
            
            # Return existing singleton instance
            if descriptor.lifetime == ServiceLifetime.SINGLETON and descriptor.instance is not None:
                return descriptor.instance
            
            # Create instance
            impl = descriptor.implementation
            
            if isinstance(impl, type):
                # It's a class, instantiate it
                instance = self._create_instance(impl)
            elif callable(impl):
                # It's a factory function
                instance = impl(self)
            else:
                # It's already an instance
                instance = impl
            
            # Store singleton instance
            if descriptor.lifetime == ServiceLifetime.SINGLETON:
                descriptor.instance = instance
            
            return instance
    
    def _create_instance(self, cls: Type[T]) -> T:
        """Create an instance with automatic dependency injection"""
        import inspect
        
        sig = inspect.signature(cls.__init__)
        params = sig.parameters
        
        kwargs = {}
        for name, param in params.items():
            if name == 'self':
                continue
            
            # Try to resolve parameter by type annotation
            if param.annotation != inspect.Parameter.empty:
                try:
                    kwargs[name] = self.resolve(param.annotation)
                except ContainerError:
                    # If not registered, check if it has a default
                    if param.default == inspect.Parameter.empty:
                        raise
        
        return cls(**kwargs)
    
    def try_resolve(self, service_type: Type[T]) -> Optional[T]:
        """
        Try to resolve a service, returns None if not registered.
        """
        try:
            return self.resolve(service_type)
        except ContainerError:
            return None
    
    def is_registered(self, service_type: Type) -> bool:
        """Check if a service type is registered"""
        with self._lock:
            return service_type in self._services
    
    def unregister(self, service_type: Type) -> bool:
        """
        Unregister a service.
        
        Returns:
            True if service was removed, False if not found
        """
        with self._lock:
            if service_type in self._services:
                del self._services[service_type]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all registered services"""
        with self._lock:
            self._services.clear()


# Global application container
_app_container: Optional[Container] = None


def get_container() -> Container:
    """Get the global application container"""
    global _app_container
    if _app_container is None:
        _app_container = Container()
    return _app_container


def set_container(container: Container) -> None:
    """Set the global application container"""
    global _app_container
    _app_container = container


def resolve(service_type: Type[T]) -> T:
    """Shorthand for get_container().resolve()"""
    return get_container().resolve(service_type)


# Dependency injection decorator
def inject(*dependencies: Type):
    """
    Decorator to inject dependencies into a class.
    
    Usage:
        @inject(PluginManager, AppConfig)
        class MyService:
            def __init__(self, plugin_manager: PluginManager, config: AppConfig):
                self.plugin_manager = plugin_manager
                self.config = config
    """
    def decorator(cls):
        original_init = cls.__init__
        
        def new_init(self, *args, **kwargs):
            container = get_container()
            
            # Inject dependencies
            for dep_type in dependencies:
                attr_name = _camel_to_snake(dep_type.__name__)
                if attr_name not in kwargs:
                    kwargs[attr_name] = container.resolve(dep_type)
            
            original_init(self, *args, **kwargs)
        
        cls.__init__ = new_init
        return cls
    
    return decorator


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case"""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


# Application-specific container configuration
class AppContainer(Container):
    """
    Pre-configured container for IDM-YT application.
    
    Usage:
        container = AppContainer()
        container.configure()
        
        # Get services
        plugin_manager = container.resolve(PluginManager)
        download_manager = container.resolve(DownloadManager)
    """
    
    def configure(self, config_path: Optional[Path] = None) -> 'AppContainer':
        """
        Configure the container with application services.
        
        Args:
            config_path: Optional path to config directory
        """
        from .config import AppConfig
        from .settings import AppSettings, SettingsManager
        
        # Configuration
        app_config = AppConfig()
        self.register_instance(AppConfig, app_config)
        
        # Settings
        settings_manager = SettingsManager(config_path or Path.home() / ".idm-yt")
        self.register_instance(SettingsManager, settings_manager)
        self.register_factory(
            AppSettings,
            lambda c: c.resolve(SettingsManager).load(),
            lifetime=ServiceLifetime.SINGLETON
        )
        
        # Register core services lazily
        self._register_core_services()
        
        logger.info("AppContainer configured")
        return self
    
    def _register_core_services(self) -> None:
        """Register core application services"""
        # These imports are done here to avoid circular imports
        from .config import AppConfig
        from .download_manager import DownloadManager
        from .url_parser import URLParser
        from .format_parser import FormatParser
        from .video_fetcher import VideoInfoFetcher
        from .progress_tracker import ProgressTracker
        from .state_machine import DownloadStateMachine, MultiDownloadStateMachine
        from .events import EventBus
        
        # URL and format parsing
        self.register(URLParser, lifetime=ServiceLifetime.SINGLETON)
        self.register(FormatParser, lifetime=ServiceLifetime.SINGLETON)
        
        # Video fetching
        self.register_factory(
            VideoInfoFetcher,
            lambda c: VideoInfoFetcher(),
            lifetime=ServiceLifetime.SINGLETON
        )
        
        # Download management
        self.register_factory(
            DownloadManager,
            lambda c: DownloadManager(c.try_resolve(AppConfig)),
            lifetime=ServiceLifetime.SINGLETON
        )
        
        # State machines
        self.register(DownloadStateMachine, lifetime=ServiceLifetime.TRANSIENT)
        self.register(MultiDownloadStateMachine, lifetime=ServiceLifetime.SINGLETON)
        
        # Progress tracker
        self.register(ProgressTracker, lifetime=ServiceLifetime.TRANSIENT)
    
    def configure_plugins(self) -> 'AppContainer':
        """Configure plugin manager"""
        from plugin_manager import PluginManager
        
        plugin_manager = PluginManager()
        try:
            plugin_manager.discover()
        except Exception as e:
            logger.warning(f"Plugin discovery failed: {e}")
        
        self.register_instance(PluginManager, plugin_manager)
        return self
    
    def configure_gui(self, root) -> 'AppContainer':
        """
        Configure GUI-specific services.
        
        Args:
            root: Tkinter root window
        """
        # Store root for UI services
        self.register_instance(type(root), root)
        
        # Clipboard monitor
        from .clipboard_monitor import ClipboardMonitor, ClipboardMonitorConfig
        
        config = ClipboardMonitorConfig(
            check_interval_ms=1000,
            enabled=True,
            auto_paste_when_empty=True,
        )
        self.register_instance(ClipboardMonitorConfig, config)
        
        return self


# Factory function for creating configured container
def create_app_container(config_path: Optional[Path] = None) -> AppContainer:
    """
    Create and configure the application container.
    
    Args:
        config_path: Optional path to config directory
        
    Returns:
        Configured AppContainer
    """
    container = AppContainer()
    container.configure(config_path)
    container.configure_plugins()
    
    # Set as global container
    set_container(container)
    
    return container
