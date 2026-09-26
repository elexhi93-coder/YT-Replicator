"""
Authentication Manager - OAuth token management for all platforms.

Handles OAuth flows, token storage, and refresh across all supported platforms.
"""

import json
import time
import threading
import webbrowser
import http.server
import urllib.parse
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, List
from enum import Enum
import hashlib
import base64
import secrets

logger = logging.getLogger(__name__)


class OAuthProvider(Enum):
    """Supported OAuth providers."""
    YOUTUBE = "youtube"
    DAILYMOTION = "dailymotion"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"


@dataclass
class OAuthConfig:
    """OAuth configuration for a platform."""
    provider: OAuthProvider
    client_id: str
    client_secret: str
    auth_url: str
    token_url: str
    scopes: List[str]
    redirect_uri: str = "http://localhost:8585/callback"
    extra_params: Dict[str, str] = field(default_factory=dict)


@dataclass
class TokenData:
    """Stored token data."""
    access_token: str
    refresh_token: Optional[str]
    token_type: str
    expires_at: float
    scopes: List[str]
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return time.time() >= self.expires_at - 60  # 1 minute buffer
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_type': self.token_type,
            'expires_at': self.expires_at,
            'scopes': self.scopes,
            'extra_data': self.extra_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TokenData':
        """Create from dictionary."""
        return cls(
            access_token=data['access_token'],
            refresh_token=data.get('refresh_token'),
            token_type=data.get('token_type', 'Bearer'),
            expires_at=data.get('expires_at', 0),
            scopes=data.get('scopes', []),
            extra_data=data.get('extra_data', {})
        )


class TokenStore:
    """Secure token storage."""
    
    def __init__(self, storage_path: Optional[str] = None):
        """
        Initialize token store.
        
        Args:
            storage_path: Path to store tokens (default: ~/.idm_tokens.json)
        """
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = Path.home() / ".idm_tokens.json"
        
        self._tokens: Dict[str, TokenData] = {}
        self._lock = threading.Lock()
        self._load()
    
    def _load(self):
        """Load tokens from storage."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                
                for provider, token_data in data.items():
                    self._tokens[provider] = TokenData.from_dict(token_data)
                
                logger.info(f"Loaded {len(self._tokens)} tokens from storage")
            except Exception as e:
                logger.error(f"Failed to load tokens: {e}")
    
    def _save(self):
        """Save tokens to storage."""
        try:
            data = {
                provider: token.to_dict()
                for provider, token in self._tokens.items()
            }
            
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug("Tokens saved to storage")
        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
    
    def get(self, provider: str) -> Optional[TokenData]:
        """Get token for a provider."""
        with self._lock:
            return self._tokens.get(provider)
    
    def set(self, provider: str, token: TokenData):
        """Store token for a provider."""
        with self._lock:
            self._tokens[provider] = token
            self._save()
    
    def delete(self, provider: str):
        """Delete token for a provider."""
        with self._lock:
            if provider in self._tokens:
                del self._tokens[provider]
                self._save()
    
    def has_valid_token(self, provider: str) -> bool:
        """Check if provider has a valid (non-expired) token."""
        token = self.get(provider)
        return token is not None and not token.is_expired
    
    def clear_all(self):
        """Clear all stored tokens."""
        with self._lock:
            self._tokens.clear()
            self._save()


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback."""
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
    
    def do_GET(self):
        """Handle GET request from OAuth callback."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        # Store the authorization code or error
        if 'code' in params:
            self.server.auth_code = params['code'][0]
            self.server.auth_error = None
            response = """
            <html>
            <head><title>Authorization Successful</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: #4CAF50;">✓ Authorization Successful</h1>
                <p>You can close this window and return to IDM Video Downloader.</p>
                <script>setTimeout(() => window.close(), 3000);</script>
            </body>
            </html>
            """
        else:
            self.server.auth_code = None
            self.server.auth_error = params.get('error', ['Unknown error'])[0]
            response = f"""
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: #f44336;">✗ Authorization Failed</h1>
                <p>Error: {self.server.auth_error}</p>
                <p>Please close this window and try again.</p>
            </body>
            </html>
            """
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(response.encode())


class OAuthFlow:
    """OAuth 2.0 authorization flow handler."""
    
    def __init__(self, config: OAuthConfig):
        """
        Initialize OAuth flow.
        
        Args:
            config: OAuth configuration
        """
        self.config = config
        self._state = None
        self._code_verifier = None  # For PKCE
    
    def _generate_state(self) -> str:
        """Generate random state for CSRF protection."""
        self._state = secrets.token_urlsafe(32)
        return self._state
    
    def _generate_pkce(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge."""
        self._code_verifier = secrets.token_urlsafe(64)[:128]
        
        # SHA256 hash of code verifier
        digest = hashlib.sha256(self._code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip('=')
        
        return self._code_verifier, code_challenge
    
    def get_authorization_url(self, use_pkce: bool = True) -> str:
        """
        Get the authorization URL.
        
        Args:
            use_pkce: Whether to use PKCE (recommended for public clients)
            
        Returns:
            Authorization URL to open in browser
        """
        params = {
            'client_id': self.config.client_id,
            'redirect_uri': self.config.redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(self.config.scopes),
            'state': self._generate_state(),
            'access_type': 'offline',  # For refresh token
            'prompt': 'consent'  # Force consent screen
        }
        
        if use_pkce:
            verifier, challenge = self._generate_pkce()
            params['code_challenge'] = challenge
            params['code_challenge_method'] = 'S256'
        
        # Add any extra params
        params.update(self.config.extra_params)
        
        query = urllib.parse.urlencode(params)
        return f"{self.config.auth_url}?{query}"
    
    def start_callback_server(self, timeout: float = 120.0) -> Optional[str]:
        """
        Start local server to receive OAuth callback.
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            Authorization code if successful, None otherwise
        """
        # Parse port from redirect URI
        parsed = urllib.parse.urlparse(self.config.redirect_uri)
        port = parsed.port or 8585
        
        server = http.server.HTTPServer(('localhost', port), OAuthCallbackHandler)
        server.auth_code = None
        server.auth_error = None
        server.timeout = timeout
        
        logger.info(f"Starting OAuth callback server on port {port}")
        
        # Handle requests until we get a code or timeout
        start_time = time.time()
        while server.auth_code is None and server.auth_error is None:
            if time.time() - start_time > timeout:
                logger.warning("OAuth callback timeout")
                break
            server.handle_request()
        
        server.server_close()
        
        if server.auth_error:
            logger.error(f"OAuth error: {server.auth_error}")
            return None
        
        return server.auth_code
    
    def exchange_code_for_token(
        self,
        code: str,
        use_pkce: bool = True
    ) -> Optional[TokenData]:
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from callback
            use_pkce: Whether PKCE was used
            
        Returns:
            TokenData if successful, None otherwise
        """
        import urllib.request
        
        data = {
            'client_id': self.config.client_id,
            'client_secret': self.config.client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': self.config.redirect_uri
        }
        
        if use_pkce and self._code_verifier:
            data['code_verifier'] = self._code_verifier
        
        try:
            encoded_data = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(
                self.config.token_url,
                data=encoded_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                token_response = json.loads(response.read().decode())
            
            # Calculate expiry time
            expires_in = token_response.get('expires_in', 3600)
            expires_at = time.time() + expires_in
            
            return TokenData(
                access_token=token_response['access_token'],
                refresh_token=token_response.get('refresh_token'),
                token_type=token_response.get('token_type', 'Bearer'),
                expires_at=expires_at,
                scopes=self.config.scopes
            )
        
        except Exception as e:
            logger.error(f"Token exchange failed: {e}")
            return None
    
    def refresh_access_token(self, refresh_token: str) -> Optional[TokenData]:
        """
        Refresh access token using refresh token.
        
        Args:
            refresh_token: The refresh token
            
        Returns:
            New TokenData if successful, None otherwise
        """
        import urllib.request
        
        data = {
            'client_id': self.config.client_id,
            'client_secret': self.config.client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
        
        try:
            encoded_data = urllib.parse.urlencode(data).encode()
            req = urllib.request.Request(
                self.config.token_url,
                data=encoded_data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                token_response = json.loads(response.read().decode())
            
            expires_in = token_response.get('expires_in', 3600)
            expires_at = time.time() + expires_in
            
            return TokenData(
                access_token=token_response['access_token'],
                refresh_token=token_response.get('refresh_token', refresh_token),
                token_type=token_response.get('token_type', 'Bearer'),
                expires_at=expires_at,
                scopes=self.config.scopes
            )
        
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return None


class AuthManager:
    """Central authentication manager for all platforms."""
    
    # OAuth configurations for each platform
    PLATFORM_CONFIGS = {
        OAuthProvider.YOUTUBE: {
            'auth_url': 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url': 'https://oauth2.googleapis.com/token',
            'scopes': [
                'https://www.googleapis.com/auth/youtube.upload',
                'https://www.googleapis.com/auth/youtube',
                'https://www.googleapis.com/auth/youtube.readonly'
            ]
        },
        OAuthProvider.DAILYMOTION: {
            'auth_url': 'https://api.dailymotion.com/oauth/authorize',
            'token_url': 'https://api.dailymotion.com/oauth/token',
            'scopes': ['manage_videos', 'manage_playlists']
        },
        OAuthProvider.TIKTOK: {
            'auth_url': 'https://www.tiktok.com/v2/auth/authorize/',
            'token_url': 'https://open.tiktokapis.com/v2/oauth/token/',
            'scopes': ['video.publish', 'video.upload']
        },
        OAuthProvider.FACEBOOK: {
            'auth_url': 'https://www.facebook.com/v18.0/dialog/oauth',
            'token_url': 'https://graph.facebook.com/v18.0/oauth/access_token',
            'scopes': [
                'pages_manage_posts',
                'pages_read_engagement',
                'publish_video'
            ]
        }
    }
    
    def __init__(self, token_store: Optional[TokenStore] = None):
        """
        Initialize auth manager.
        
        Args:
            token_store: Token storage instance (default: create new)
        """
        self.token_store = token_store or TokenStore()
        self._configs: Dict[OAuthProvider, OAuthConfig] = {}
        self._auth_callbacks: Dict[OAuthProvider, Callable[[bool], None]] = {}
    
    def configure_platform(
        self,
        provider: OAuthProvider,
        client_id: str,
        client_secret: str,
        redirect_uri: Optional[str] = None
    ):
        """
        Configure OAuth for a platform.
        
        Args:
            provider: The OAuth provider
            client_id: OAuth client ID
            client_secret: OAuth client secret
            redirect_uri: Custom redirect URI (optional)
        """
        platform_config = self.PLATFORM_CONFIGS.get(provider, {})
        
        self._configs[provider] = OAuthConfig(
            provider=provider,
            client_id=client_id,
            client_secret=client_secret,
            auth_url=platform_config.get('auth_url', ''),
            token_url=platform_config.get('token_url', ''),
            scopes=platform_config.get('scopes', []),
            redirect_uri=redirect_uri or "http://localhost:8585/callback"
        )
        
        logger.info(f"Configured OAuth for {provider.value}")
    
    def is_configured(self, provider: OAuthProvider) -> bool:
        """Check if a platform is configured."""
        return provider in self._configs
    
    def is_authenticated(self, provider: OAuthProvider) -> bool:
        """Check if authenticated with a platform."""
        return self.token_store.has_valid_token(provider.value)
    
    def get_access_token(self, provider: OAuthProvider) -> Optional[str]:
        """
        Get access token for a platform, refreshing if needed.
        
        Args:
            provider: The OAuth provider
            
        Returns:
            Access token or None if not authenticated
        """
        token_data = self.token_store.get(provider.value)
        if not token_data:
            return None
        
        # Refresh if expired
        if token_data.is_expired and token_data.refresh_token:
            if self.refresh_token(provider):
                token_data = self.token_store.get(provider.value)
            else:
                return None
        
        return token_data.access_token if token_data else None
    
    def authenticate(
        self,
        provider: OAuthProvider,
        callback: Optional[Callable[[bool], None]] = None
    ) -> bool:
        """
        Start OAuth authentication flow.
        
        Args:
            provider: The OAuth provider
            callback: Optional callback when auth completes
            
        Returns:
            True if authentication started successfully
        """
        if provider not in self._configs:
            logger.error(f"Platform {provider.value} not configured")
            return False
        
        config = self._configs[provider]
        flow = OAuthFlow(config)
        
        # Store callback
        if callback:
            self._auth_callbacks[provider] = callback
        
        def auth_thread():
            try:
                # Get authorization URL and open browser
                auth_url = flow.get_authorization_url()
                logger.info(f"Opening browser for {provider.value} authentication")
                webbrowser.open(auth_url)
                
                # Wait for callback
                code = flow.start_callback_server()
                
                if code:
                    # Exchange code for token
                    token_data = flow.exchange_code_for_token(code)
                    
                    if token_data:
                        self.token_store.set(provider.value, token_data)
                        logger.info(f"Successfully authenticated with {provider.value}")
                        
                        if callback:
                            callback(True)
                        return
                
                logger.error(f"Authentication failed for {provider.value}")
                if callback:
                    callback(False)
                    
            except Exception as e:
                logger.error(f"Authentication error: {e}")
                if callback:
                    callback(False)
        
        # Run in background thread
        thread = threading.Thread(target=auth_thread, daemon=True)
        thread.start()
        
        return True
    
    def refresh_token(self, provider: OAuthProvider) -> bool:
        """
        Refresh access token for a platform.
        
        Args:
            provider: The OAuth provider
            
        Returns:
            True if refresh successful
        """
        if provider not in self._configs:
            return False
        
        token_data = self.token_store.get(provider.value)
        if not token_data or not token_data.refresh_token:
            return False
        
        config = self._configs[provider]
        flow = OAuthFlow(config)
        
        new_token = flow.refresh_access_token(token_data.refresh_token)
        if new_token:
            self.token_store.set(provider.value, new_token)
            logger.info(f"Refreshed token for {provider.value}")
            return True
        
        return False
    
    def revoke(self, provider: OAuthProvider) -> bool:
        """
        Revoke authentication for a platform.
        
        Args:
            provider: The OAuth provider
            
        Returns:
            True if revocation successful
        """
        self.token_store.delete(provider.value)
        logger.info(f"Revoked authentication for {provider.value}")
        return True
    
    def get_authenticated_platforms(self) -> List[OAuthProvider]:
        """Get list of authenticated platforms."""
        return [
            provider
            for provider in OAuthProvider
            if self.is_authenticated(provider)
        ]
    
    def get_token_expiry(self, provider: OAuthProvider) -> Optional[float]:
        """Get token expiry time for a platform."""
        token_data = self.token_store.get(provider.value)
        return token_data.expires_at if token_data else None
