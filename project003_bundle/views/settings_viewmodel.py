"""
Settings ViewModel for IDM-YT
Bridges AppSettings with Tkinter variables for reactive UI binding.
"""

import tkinter as tk
from typing import Dict, Any, Optional, Type, Callable, List
from dataclasses import dataclass, field
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class BindingInfo:
    """Information about a settings binding"""
    key: str
    var: tk.Variable
    var_type: Type[tk.Variable]
    transform_to_ui: Optional[Callable] = None
    transform_from_ui: Optional[Callable] = None
    validation: Optional[Callable[[Any], bool]] = None


class SettingsViewModel:
    """
    Bridges between application settings and Tkinter UI variables.
    
    Provides two-way data binding:
    - Changes in settings update UI
    - Changes in UI update settings
    
    Usage:
        from core.settings import AppSettings
        
        settings = AppSettings()
        vm = SettingsViewModel(settings)
        
        # Get bound variables for UI
        download_path_var = vm.bind_string("download_path")
        concurrent_var = vm.bind_int("concurrent_fragments", default=4)
        use_aria2c_var = vm.bind_bool("use_aria2c", default=False)
        
        # Use in UI
        ttk.Entry(frame, textvariable=download_path_var)
        ttk.Checkbutton(frame, variable=use_aria2c_var)
        
        # Save changes back to settings
        vm.save()
    """
    
    def __init__(self, settings: Any = None):
        """
        Initialize the ViewModel.
        
        Args:
            settings: Settings object (or dict-like) to bind to
        """
        self._settings = settings or {}
        self._bindings: Dict[str, BindingInfo] = {}
        self._dirty = False
        self._change_callbacks: List[Callable[[str, Any], None]] = []
    
    @property
    def settings(self) -> Any:
        return self._settings
    
    @settings.setter
    def settings(self, value: Any):
        self._settings = value
        self._refresh_all()
    
    @property
    def is_dirty(self) -> bool:
        """Check if any settings have been modified"""
        return self._dirty
    
    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        """Register callback for any setting change"""
        self._change_callbacks.append(callback)
    
    def _get_setting(self, key: str, default: Any = None) -> Any:
        """Get setting value by key"""
        if hasattr(self._settings, key):
            return getattr(self._settings, key)
        elif isinstance(self._settings, dict):
            return self._settings.get(key, default)
        return default
    
    def _set_setting(self, key: str, value: Any) -> None:
        """Set setting value by key"""
        if hasattr(self._settings, key):
            setattr(self._settings, key, value)
        elif isinstance(self._settings, dict):
            self._settings[key] = value
        
        self._dirty = True
        
        # Notify callbacks
        for callback in self._change_callbacks:
            try:
                callback(key, value)
            except Exception as e:
                logger.error(f"Settings change callback error: {e}")
    
    def _create_binding(
        self,
        key: str,
        var_type: Type[tk.Variable],
        default: Any = None,
        transform_to_ui: Callable = None,
        transform_from_ui: Callable = None,
        validation: Callable[[Any], bool] = None,
    ) -> tk.Variable:
        """Create a binding between a setting and a Tkinter variable"""
        
        # Get current value
        value = self._get_setting(key, default)
        
        # Apply transform for UI display
        if transform_to_ui:
            value = transform_to_ui(value)
        
        # Create variable
        var = var_type(value=value)
        
        # Store binding info
        binding = BindingInfo(
            key=key,
            var=var,
            var_type=var_type,
            transform_to_ui=transform_to_ui,
            transform_from_ui=transform_from_ui,
            validation=validation,
        )
        self._bindings[key] = binding
        
        # Set up trace for changes
        def on_var_change(*args):
            try:
                new_value = var.get()
                
                # Apply reverse transform
                if transform_from_ui:
                    new_value = transform_from_ui(new_value)
                
                # Validate
                if validation and not validation(new_value):
                    # Revert to previous value
                    old_value = self._get_setting(key, default)
                    if transform_to_ui:
                        old_value = transform_to_ui(old_value)
                    var.set(old_value)
                    return
                
                # Update settings
                self._set_setting(key, new_value)
                
            except Exception as e:
                logger.error(f"Error updating setting {key}: {e}")
        
        var.trace_add('write', on_var_change)
        
        return var
    
    def bind_string(
        self,
        key: str,
        default: str = "",
        transform_to_ui: Callable[[Any], str] = None,
        transform_from_ui: Callable[[str], Any] = None,
        validation: Callable[[str], bool] = None,
    ) -> tk.StringVar:
        """Bind a string setting to a StringVar"""
        return self._create_binding(
            key, tk.StringVar, default,
            transform_to_ui, transform_from_ui, validation
        )
    
    def bind_int(
        self,
        key: str,
        default: int = 0,
        min_value: int = None,
        max_value: int = None,
    ) -> tk.IntVar:
        """Bind an integer setting to an IntVar"""
        
        def validate(v):
            if min_value is not None and v < min_value:
                return False
            if max_value is not None and v > max_value:
                return False
            return True
        
        return self._create_binding(key, tk.IntVar, default, validation=validate)
    
    def bind_float(
        self,
        key: str,
        default: float = 0.0,
        min_value: float = None,
        max_value: float = None,
    ) -> tk.DoubleVar:
        """Bind a float setting to a DoubleVar"""
        
        def validate(v):
            if min_value is not None and v < min_value:
                return False
            if max_value is not None and v > max_value:
                return False
            return True
        
        return self._create_binding(key, tk.DoubleVar, default, validation=validate)
    
    def bind_bool(self, key: str, default: bool = False) -> tk.BooleanVar:
        """Bind a boolean setting to a BooleanVar"""
        return self._create_binding(key, tk.BooleanVar, default)
    
    def bind_path(self, key: str, default: str = "") -> tk.StringVar:
        """Bind a path setting to a StringVar with path normalization"""
        return self._create_binding(
            key, tk.StringVar, default,
            transform_to_ui=lambda p: str(p) if p else "",
            transform_from_ui=lambda s: Path(s) if s else None,
        )
    
    def bind_enum(
        self,
        key: str,
        enum_type: Type,
        default: Any = None,
    ) -> tk.StringVar:
        """Bind an enum setting to a StringVar (using enum name)"""
        if default is None:
            default = list(enum_type)[0]
        
        return self._create_binding(
            key, tk.StringVar, default,
            transform_to_ui=lambda e: e.name if hasattr(e, 'name') else str(e),
            transform_from_ui=lambda s: enum_type[s] if s in enum_type.__members__ else default,
        )
    
    def bind_list(
        self,
        key: str,
        separator: str = ",",
        default: List[str] = None,
    ) -> tk.StringVar:
        """Bind a list setting to a StringVar (comma-separated)"""
        return self._create_binding(
            key, tk.StringVar, default or [],
            transform_to_ui=lambda lst: separator.join(lst) if lst else "",
            transform_from_ui=lambda s: [x.strip() for x in s.split(separator) if x.strip()],
        )
    
    def get_var(self, key: str) -> Optional[tk.Variable]:
        """Get the Tkinter variable for a binding"""
        binding = self._bindings.get(key)
        return binding.var if binding else None
    
    def refresh(self, key: str) -> None:
        """Refresh a specific binding from settings"""
        binding = self._bindings.get(key)
        if binding:
            value = self._get_setting(key)
            if binding.transform_to_ui:
                value = binding.transform_to_ui(value)
            binding.var.set(value)
    
    def _refresh_all(self) -> None:
        """Refresh all bindings from settings"""
        for key in self._bindings:
            self.refresh(key)
    
    def save(self) -> bool:
        """
        Save all changes back to settings.
        
        Returns:
            True if saved successfully
        """
        try:
            # If settings has a save method, call it
            if hasattr(self._settings, 'save'):
                self._settings.save()
            
            self._dirty = False
            logger.info("Settings saved")
            return True
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            return False
    
    def reset(self, key: str = None) -> None:
        """
        Reset settings to defaults.
        
        Args:
            key: Specific key to reset, or None for all
        """
        if hasattr(self._settings, 'reset'):
            if key:
                self._settings.reset(key)
                self.refresh(key)
            else:
                self._settings.reset()
                self._refresh_all()


class DownloadSettingsViewModel(SettingsViewModel):
    """
    ViewModel specifically for download-related settings.
    Pre-configures all download settings bindings.
    """
    
    def __init__(self, settings: Any = None):
        super().__init__(settings)
        self._setup_bindings()
    
    def _setup_bindings(self):
        """Set up all download settings bindings"""
        # Download path
        self.download_path = self.bind_path("download_path", str(Path.home() / "Downloads"))
        
        # Parallel download settings
        self.concurrent_fragments = self.bind_int("concurrent_fragments", default=4, min_value=1, max_value=16)
        self.use_aria2c = self.bind_bool("use_aria2c", default=False)
        self.aria2c_connections = self.bind_int("aria2c_connections", default=16, min_value=1, max_value=32)
        
        # Output format
        self.output_format = self.bind_string("output_format", default="mp4")
        
        # Audio settings
        self.audio_format = self.bind_string("audio_format", default="mp3")
        self.audio_quality = self.bind_string("audio_quality", default="320")
        
        # Subtitle settings
        self.subtitle_langs = self.bind_list("subtitle_langs", default=["en"])
        self.auto_subtitles = self.bind_bool("auto_subtitles", default=True)
        self.subtitle_format = self.bind_string("subtitle_format", default="srt")
        
        # Thumbnail settings
        self.thumbnail_format = self.bind_string("thumbnail_format", default="jpg")
        
        # Retry settings
        self.max_retries = self.bind_int("max_retries", default=5, min_value=1, max_value=10)
        self.backoff_base_sleep = self.bind_float("backoff_base_sleep", default=2.0, min_value=0.5, max_value=10.0)
        self.backoff_max_sleep = self.bind_float("backoff_max_sleep", default=20.0, min_value=5.0, max_value=60.0)


class UISettingsViewModel(SettingsViewModel):
    """
    ViewModel for UI-related settings.
    """
    
    def __init__(self, settings: Any = None):
        super().__init__(settings)
        self._setup_bindings()
    
    def _setup_bindings(self):
        """Set up UI settings bindings"""
        # Clipboard monitoring
        self.clipboard_monitor_enabled = self.bind_bool("clipboard_monitor_enabled", default=True)
        self.clipboard_interval = self.bind_int("clipboard_interval", default=1000, min_value=500, max_value=5000)
        
        # Window settings
        self.window_width = self.bind_int("window_width", default=800, min_value=600)
        self.window_height = self.bind_int("window_height", default=700, min_value=500)
        self.remember_position = self.bind_bool("remember_position", default=True)
        
        # Display settings
        self.show_thumbnails = self.bind_bool("show_thumbnails", default=True)
        self.confirm_downloads = self.bind_bool("confirm_downloads", default=True)
        self.show_notifications = self.bind_bool("show_notifications", default=True)
