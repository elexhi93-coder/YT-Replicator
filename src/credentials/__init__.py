"""credentials — Google API clients and authorized destination channels (U05).

Cross-module access is only via `credentials.api` (INV-12). Owns the
`google_client` and `authorized_channel` tables (docs/03 §4) and the OAuth
token lifecycle; it never uploads media (that is `youtube`).
"""

