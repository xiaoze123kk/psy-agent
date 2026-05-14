from __future__ import annotations

import platform
import sys


if sys.platform == "win32" and hasattr(platform, "_wmi"):
    # Python 3.13 may query WMI during platform.machine(); when WMI is slow or
    # wedged this blocks SQLAlchemy import during backend startup.
    platform._wmi = None
