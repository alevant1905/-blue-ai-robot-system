"""
Blue Robot System Tools
========================
System utilities: clipboard, screenshots, notifications, and more.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# ================================================================================
# CLIPBOARD
# ================================================================================

def get_clipboard() -> str:
    """
    Get the current clipboard contents.

    Returns:
        JSON result with clipboard text
    """
    try:
        import pyperclip
        text = pyperclip.paste()
        return json.dumps({
            "success": True,
            "text": text,
            "length": len(text) if text else 0
        })
    except ImportError:
        # Fallback for Windows
        if platform.system() == 'Windows':
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                try:
                    text = win32clipboard.GetClipboardData()
                    return json.dumps({
                        "success": True,
                        "text": text,
                        "length": len(text) if text else 0
                    })
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as e:
                pass

        return json.dumps({
            "success": False,
            "error": "Clipboard access requires pyperclip. Install with: pip install pyperclip"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to read clipboard: {str(e)}"
        })


def set_clipboard(text: str) -> str:
    """
    Set the clipboard contents.

    Args:
        text: Text to copy to clipboard

    Returns:
        JSON result
    """
    if not text:
        return json.dumps({
            "success": False,
            "error": "No text provided to copy"
        })

    try:
        import pyperclip
        pyperclip.copy(text)
        return json.dumps({
            "success": True,
            "message": f"Copied {len(text)} characters to clipboard",
            "preview": text[:100] + "..." if len(text) > 100 else text
        })
    except ImportError:
        # Fallback for Windows
        if platform.system() == 'Windows':
            try:
                import win32clipboard
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text)
                    return json.dumps({
                        "success": True,
                        "message": f"Copied {len(text)} characters to clipboard"
                    })
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as e:
                pass

        return json.dumps({
            "success": False,
            "error": "Clipboard access requires pyperclip. Install with: pip install pyperclip"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to copy to clipboard: {str(e)}"
        })


# ================================================================================
# SCREENSHOTS
# ================================================================================

SCREENSHOT_FOLDER = os.environ.get("BLUE_SCREENSHOT_FOLDER", "data/screenshots")


def take_screenshot(region: str = None, save: bool = True,
                   filename: str = None) -> str:
    """
    Take a screenshot.

    Args:
        region: "full" (default), "active" (active window), or "x,y,w,h" for custom region
        save: Whether to save to file
        filename: Custom filename (optional)

    Returns:
        JSON result with screenshot info
    """
    try:
        from PIL import ImageGrab, Image
    except ImportError:
        return json.dumps({
            "success": False,
            "error": "Screenshot requires Pillow. Install with: pip install Pillow"
        })

    try:
        # Take screenshot
        if region == "active":
            # Try to capture active window (Windows only)
            if platform.system() == 'Windows':
                try:
                    import win32gui
                    import win32ui
                    import win32con
                    from ctypes import windll

                    hwnd = win32gui.GetForegroundWindow()
                    left, top, right, bot = win32gui.GetWindowRect(hwnd)
                    width = right - left
                    height = bot - top

                    img = ImageGrab.grab(bbox=(left, top, right, bot))
                except Exception:
                    # Fall back to full screen
                    img = ImageGrab.grab()
            else:
                img = ImageGrab.grab()
        elif region and ',' in region:
            # Custom region: x,y,w,h
            try:
                parts = [int(p.strip()) for p in region.split(',')]
                if len(parts) == 4:
                    x, y, w, h = parts
                    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                else:
                    img = ImageGrab.grab()
            except Exception:
                img = ImageGrab.grab()
        else:
            # Full screen
            img = ImageGrab.grab()

        result = {
            "success": True,
            "width": img.width,
            "height": img.height,
            "mode": img.mode
        }

        if save:
            # Save to file
            os.makedirs(SCREENSHOT_FOLDER, exist_ok=True)

            if not filename:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"

            filepath = os.path.join(SCREENSHOT_FOLDER, filename)
            img.save(filepath, "PNG")

            result["saved"] = True
            result["filepath"] = filepath
            result["message"] = f"Screenshot saved to {filepath}"
        else:
            # Return as base64
            import io
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            img_base64 = base64.b64encode(buffer.getvalue()).decode()

            result["saved"] = False
            result["base64_length"] = len(img_base64)
            result["message"] = "Screenshot captured (not saved)"

        return json.dumps(result)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to take screenshot: {str(e)}"
        })


def list_screenshots(limit: int = 20) -> str:
    """
    List saved screenshots.

    Returns:
        JSON result with screenshot list
    """
    try:
        if not os.path.exists(SCREENSHOT_FOLDER):
            return json.dumps({
                "success": True,
                "count": 0,
                "screenshots": [],
                "message": "No screenshots folder found"
            })

        files = []
        for f in sorted(Path(SCREENSHOT_FOLDER).glob("*.png"), reverse=True)[:limit]:
            stat = f.stat()
            files.append({
                "filename": f.name,
                "path": str(f),
                "size_kb": round(stat.st_size / 1024, 1),
                "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat()
            })

        return json.dumps({
            "success": True,
            "count": len(files),
            "screenshots": files,
            "folder": SCREENSHOT_FOLDER
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to list screenshots: {str(e)}"
        })


# ================================================================================
# NOTIFICATIONS
# ================================================================================

def send_notification(title: str, message: str, timeout: int = 10) -> str:
    """
    Send a desktop notification.

    Args:
        title: Notification title
        message: Notification message
        timeout: Display duration in seconds

    Returns:
        JSON result
    """
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Blue Assistant",
            timeout=timeout
        )
        return json.dumps({
            "success": True,
            "message": "Notification sent"
        })
    except ImportError:
        # Fallback for Windows
        if platform.system() == 'Windows':
            try:
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=timeout, threaded=True)
                return json.dumps({
                    "success": True,
                    "message": "Notification sent"
                })
            except ImportError:
                pass

        return json.dumps({
            "success": False,
            "error": "Notifications require plyer. Install with: pip install plyer"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to send notification: {str(e)}"
        })


# ================================================================================
# APPLICATION LAUNCHER
# ================================================================================

# Common application aliases
APP_ALIASES = {
    # Browsers
    'chrome': ['chrome', 'google chrome', 'google-chrome'],
    'firefox': ['firefox', 'mozilla firefox', 'mozilla'],
    'edge': ['edge', 'microsoft edge', 'msedge'],
    'brave': ['brave', 'brave browser'],

    # Productivity
    'notepad': ['notepad', 'note pad', 'text editor'],
    'calculator': ['calc', 'calculator'],
    'explorer': ['explorer', 'file explorer', 'files', 'my computer'],
    'cmd': ['cmd', 'command prompt', 'terminal', 'command line'],
    'powershell': ['powershell', 'ps'],

    # Media
    'spotify': ['spotify'],
    'vlc': ['vlc', 'vlc player', 'media player'],

    # Communication
    'outlook': ['outlook', 'mail', 'email client'],
    'teams': ['teams', 'microsoft teams'],
    'slack': ['slack'],
    'discord': ['discord'],

    # Development
    'vscode': ['code', 'vscode', 'visual studio code', 'vs code'],
    'notepad++': ['notepad++', 'npp'],
}


def _allowed_file_roots() -> List[str]:
    app_root = Path(__file__).resolve().parents[2]
    raw = os.environ.get("BLUE_FILE_TOOL_ROOTS", "")
    if raw.strip():
        roots = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    else:
        roots = [
            str(app_root / "documents"),
            str(app_root / "uploads"),
            str(app_root / "uploaded_documents"),
        ]
    return [str(Path(p).expanduser().resolve()) for p in roots]


def _path_is_allowed(path: str) -> bool:
    resolved = str(Path(path).expanduser().resolve())
    for root in _allowed_file_roots():
        try:
            if os.path.commonpath([resolved, root]) == root:
                return True
        except ValueError:
            continue
    return False


def _find_app_command(app_name: str) -> Optional[str]:
    """Find the command to launch an application."""
    app_lower = app_name.lower().strip()

    # Check aliases
    for cmd, aliases in APP_ALIASES.items():
        if app_lower in aliases:
            return cmd

    # Return as-is
    return app_name


def launch_application(app_name: str) -> str:
    """
    Launch an application.

    Args:
        app_name: Application name or alias

    Returns:
        JSON result
    """
    try:
        app_key = (app_name or "").strip().lower()
        command = _find_app_command(app_name)
        allowed = set(APP_ALIASES.keys())
        allowed.update(
            item.strip().lower()
            for item in os.environ.get("BLUE_ALLOWED_APPS", "").split(",")
            if item.strip()
        )
        if app_key not in allowed and command.lower() not in allowed:
            return json.dumps({
                "success": False,
                "error": f"Application not allowed: {app_name}",
                "allowed": sorted(allowed)
            })

        if platform.system() == 'Windows':
            subprocess.Popen([command], shell=False)
        elif platform.system() == 'Darwin':
            # macOS: use open command
            subprocess.Popen(['open', '-a', command])
        else:
            # Linux: just run the command
            subprocess.Popen([command], start_new_session=True)

        return json.dumps({
            "success": True,
            "message": f"Launched {app_name}",
            "command": command
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to launch {app_name}: {str(e)}"
        })


def open_url(url: str) -> str:
    """
    Open a URL in the default browser.

    Args:
        url: URL to open

    Returns:
        JSON result
    """
    try:
        import webbrowser

        url = (url or "").strip()
        # Ensure URL has protocol. file:// is intentionally not accepted here;
        # use open_file, which applies the file-root allowlist.
        if url.startswith('file://'):
            return json.dumps({
                "success": False,
                "error": "Only http and https URLs are allowed"
            })
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        webbrowser.open(url)

        return json.dumps({
            "success": True,
            "message": f"Opened {url}",
            "url": url
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to open URL: {str(e)}"
        })


def open_file(filepath: str) -> str:
    """
    Open a file with the default application.

    Args:
        filepath: Path to the file

    Returns:
        JSON result
    """
    try:
        if not os.path.exists(filepath):
            return json.dumps({
                "success": False,
                "error": f"File not found: {filepath}"
            })
        if not _path_is_allowed(filepath):
            return json.dumps({
                "success": False,
                "error": "File is outside allowed roots",
                "allowed_roots": _allowed_file_roots()
            })

        if platform.system() == 'Windows':
            os.startfile(filepath)
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', filepath])
        else:
            subprocess.Popen(['xdg-open', filepath])

        return json.dumps({
            "success": True,
            "message": f"Opened {filepath}"
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to open file: {str(e)}"
        })


# ================================================================================
# VOLUME CONTROL
# ================================================================================

def set_volume(level: int = None, mute: bool = None) -> str:
    """
    Set system volume or mute.

    Args:
        level: Volume level 0-100
        mute: True to mute, False to unmute

    Returns:
        JSON result
    """
    if platform.system() != 'Windows':
        return json.dumps({
            "success": False,
            "error": "Volume control currently only supported on Windows"
        })

    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        result = {"success": True}

        if mute is not None:
            volume.SetMute(1 if mute else 0, None)
            result["muted"] = mute
            result["message"] = "Muted" if mute else "Unmuted"

        if level is not None:
            # Volume is 0.0 to 1.0
            level = max(0, min(100, level))
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            result["volume"] = level
            result["message"] = f"Volume set to {level}%"

        # Get current state
        current_volume = int(volume.GetMasterVolumeLevelScalar() * 100)
        current_mute = volume.GetMute()
        result["current_volume"] = current_volume
        result["current_mute"] = bool(current_mute)

        return json.dumps(result)

    except ImportError:
        return json.dumps({
            "success": False,
            "error": "Volume control requires pycaw. Install with: pip install pycaw"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to set volume: {str(e)}"
        })


def get_volume() -> str:
    """
    Get current system volume.

    Returns:
        JSON result with volume info
    """
    if platform.system() != 'Windows':
        return json.dumps({
            "success": False,
            "error": "Volume control currently only supported on Windows"
        })

    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        current_volume = int(volume.GetMasterVolumeLevelScalar() * 100)
        current_mute = volume.GetMute()

        return json.dumps({
            "success": True,
            "volume": current_volume,
            "muted": bool(current_mute),
            "message": f"Volume: {current_volume}%" + (" (muted)" if current_mute else "")
        })

    except ImportError:
        return json.dumps({
            "success": False,
            "error": "Volume control requires pycaw. Install with: pip install pycaw"
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to get volume: {str(e)}"
        })


# ================================================================================
# SYSTEM STATUS
# ================================================================================

def get_system_status() -> str:
    """
    Get detailed system status.

    Returns:
        JSON result with system info
    """
    try:
        import psutil
    except ImportError:
        # Basic info without psutil
        return json.dumps({
            "success": True,
            "platform": platform.system(),
            "platform_version": platform.version(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "note": "Install psutil for detailed system stats"
        })

    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()

        # Memory
        memory = psutil.virtual_memory()
        memory_total_gb = round(memory.total / (1024 ** 3), 1)
        memory_used_gb = round(memory.used / (1024 ** 3), 1)
        memory_percent = memory.percent

        # Disk
        disk = psutil.disk_usage('/')
        disk_total_gb = round(disk.total / (1024 ** 3), 1)
        disk_used_gb = round(disk.used / (1024 ** 3), 1)
        disk_percent = disk.percent

        # Battery (if available)
        battery_info = None
        try:
            battery = psutil.sensors_battery()
            if battery:
                battery_info = {
                    "percent": battery.percent,
                    "plugged": battery.power_plugged,
                    "time_left": str(datetime.timedelta(seconds=battery.secsleft)) if battery.secsleft > 0 else None
                }
        except Exception:
            pass

        # Network
        net = psutil.net_io_counters()
        bytes_sent_mb = round(net.bytes_sent / (1024 ** 2), 1)
        bytes_recv_mb = round(net.bytes_recv / (1024 ** 2), 1)

        return json.dumps({
            "success": True,
            "platform": platform.system(),
            "platform_version": platform.version(),
            "processor": platform.processor(),
            "cpu": {
                "percent": cpu_percent,
                "cores": cpu_count
            },
            "memory": {
                "total_gb": memory_total_gb,
                "used_gb": memory_used_gb,
                "percent": memory_percent
            },
            "disk": {
                "total_gb": disk_total_gb,
                "used_gb": disk_used_gb,
                "percent": disk_percent
            },
            "battery": battery_info,
            "network": {
                "sent_mb": bytes_sent_mb,
                "recv_mb": bytes_recv_mb
            }
        })

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Failed to get system status: {str(e)}"
        })


# ================================================================================
# EXECUTOR
# ================================================================================

def execute_system_command(action: str, params: Dict[str, Any] = None) -> str:
    """
    Execute a system command.

    Args:
        action: The action to perform
        params: Parameters for the action

    Returns:
        JSON result
    """
    if params is None:
        params = {}

    action_lower = action.lower().strip()

    # Clipboard
    if action_lower in ['get_clipboard', 'read_clipboard', 'paste', 'clipboard']:
        return get_clipboard()
    elif action_lower in ['set_clipboard', 'copy', 'copy_to_clipboard']:
        return set_clipboard(params.get('text', ''))

    # Screenshots
    elif action_lower in ['screenshot', 'take_screenshot', 'capture_screen']:
        return take_screenshot(
            region=params.get('region'),
            save=params.get('save', True),
            filename=params.get('filename')
        )
    elif action_lower in ['list_screenshots', 'screenshots']:
        return list_screenshots(params.get('limit', 20))

    # Notifications
    elif action_lower in ['notify', 'notification', 'send_notification']:
        return send_notification(
            title=params.get('title', 'Blue'),
            message=params.get('message', ''),
            timeout=params.get('timeout', 10)
        )

    # Applications
    elif action_lower in ['launch', 'open_app', 'start', 'run']:
        return launch_application(params.get('app', ''))
    elif action_lower in ['open_url', 'browse', 'open_website']:
        return open_url(params.get('url', ''))
    elif action_lower in ['open_file', 'open']:
        return open_file(params.get('filepath', params.get('file', '')))

    # Volume
    elif action_lower in ['set_volume', 'volume']:
        return set_volume(
            level=params.get('level'),
            mute=params.get('mute')
        )
    elif action_lower in ['get_volume', 'current_volume']:
        return get_volume()
    elif action_lower == 'mute':
        return set_volume(mute=True)
    elif action_lower == 'unmute':
        return set_volume(mute=False)

    # System status
    elif action_lower in ['system_status', 'status', 'system_info']:
        return get_system_status()

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown system action: {action}",
            "available_actions": [
                "get_clipboard", "set_clipboard",
                "screenshot", "list_screenshots",
                "notify", "launch", "open_url", "open_file",
                "set_volume", "get_volume", "mute", "unmute",
                "system_status"
            ]
        })


__all__ = [
    'get_clipboard',
    'set_clipboard',
    'take_screenshot',
    'list_screenshots',
    'send_notification',
    'launch_application',
    'open_url',
    'open_file',
    'set_volume',
    'get_volume',
    'get_system_status',
    'execute_system_command',
]
