"""
Blue Robot Configuration
========================
Central configuration for all Blue modules.
"""

import os
from pathlib import Path

# Base directory (where this file lives)
BASE_DIR = Path(__file__).parent.resolve()

# Data directories
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
DOCUMENTS_DIR = BASE_DIR / "documents"
CAMERA_DIR = BASE_DIR / "camera_captures"

# Database paths
DATABASE_PATH = DATA_DIR / "blue.db"
VISUAL_MEMORY_DB_PATH = DATA_DIR / "visual_memory.db"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
DOCUMENTS_DIR.mkdir(exist_ok=True)
CAMERA_DIR.mkdir(exist_ok=True)

# API Keys (from environment variables)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Hue Bridge Configuration
HUE_BRIDGE_IP = os.environ.get("HUE_BRIDGE_IP", "")
HUE_USERNAME = os.environ.get("HUE_USERNAME", "")

# Gmail Configuration
GMAIL_CREDENTIALS_FILE = BASE_DIR / "gmail_credentials.json"
GMAIL_TOKEN_FILE = BASE_DIR / "gmail_token.pickle"

# Server Configuration
HOST = os.environ.get("BLUE_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLUE_PORT", "5000"))
DEBUG = os.environ.get("BLUE_DEBUG", "false").lower() == "true"

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Family Configuration (can be overridden by database)
class FamilyConfig:
    """Default family configuration - customize as needed."""
    timezone = "America/Toronto"
    home_location = "Toronto, ON"
    members = {
        "Alex": {"role": "primary_user", "age": None},
        "Stella": {"role": "partner", "age": None},
        "Emmy": {"role": "child", "age": None},
        "Athena": {"role": "child", "age": None},
        "Vilda": {"role": "child", "age": None},
    }

family = FamilyConfig()

# Interaction settings
class InteractionConfig:
    """How Blue should interact."""
    voice_enabled = True
    proactive_suggestions = True
    remember_conversations = True
    max_conversation_history = 50

interaction = InteractionConfig()

# Skills configuration
class SkillsConfig:
    """What Blue can do."""
    music_enabled = True
    lights_enabled = True
    email_enabled = True
    calendar_enabled = True
    camera_enabled = True
    web_search_enabled = True

skills = SkillsConfig()
