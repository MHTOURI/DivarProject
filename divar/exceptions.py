"""
Custom exceptions for Divar scraper.
"""


class DivarError(Exception):
    """Base exception for Divar scraper errors."""
    pass


class ScraperError(DivarError):
    """Error during scraping operation."""
    pass


class RateLimitError(DivarError):
    """Rate limit exceeded error."""
    pass


class AuthenticationError(DivarError):
    """Authentication error."""
    pass


class NetworkError(DivarError):
    """Network-related error."""
    pass


class ConfigurationError(DivarError):
    """Configuration error."""
    pass


class ValidationError(DivarError):
    """Validation error."""
    pass
