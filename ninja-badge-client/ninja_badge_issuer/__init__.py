"""Issue Ninja Badge PASS / PARTICIPATION badges to workshop participants."""
__version__ = "0.1.0"

from .api import (LiveNinjaBadgeClient, MockNinjaBadgeClient, NinjaApiError)  # noqa: E402
from .config import Config, load_config  # noqa: E402
from .issuer import (BadgeResult, IssuanceReport, Participant, issue_badges,  # noqa: E402
                     load_participants)

__all__ = ["issue_badges", "load_participants", "load_config", "Config", "Participant",
           "BadgeResult", "IssuanceReport", "LiveNinjaBadgeClient", "MockNinjaBadgeClient",
           "NinjaApiError", "__version__"]
