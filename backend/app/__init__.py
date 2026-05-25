from __future__ import annotations

import platform
import sys
import warnings

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning


warnings.filterwarnings(
    "ignore",
    message=r"The default value of .*allowed_objects.*",
    category=LangChainPendingDeprecationWarning,
)


if sys.platform == "win32" and hasattr(platform, "_wmi"):
    # Python 3.13 may query WMI during platform.machine(); when WMI is slow or
    # wedged this blocks SQLAlchemy import during backend startup.
    platform._wmi = None
