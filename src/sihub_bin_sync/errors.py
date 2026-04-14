class ConfigError(Exception):
    """Raised when the YAML configuration is invalid."""


class ValidationError(Exception):
    """Raised when source data fails validation."""


class ApiError(Exception):
    """Raised when the remote API call fails."""


class StateError(Exception):
    """Raised when local state cannot be loaded or saved."""
