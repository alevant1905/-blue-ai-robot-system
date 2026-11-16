"""
Blue Robot Tools Package
========================
The tool implementations that live outside bluetools.py: the library index
(rag, documents), scholarly search (scholar), page fetching for banter (web),
face embeddings (face_engine) and the Facebook sign-in (facebook_integration,
social_media, calendar).

Music, lights, Gmail and the camera are implemented in bluetools.py. This
package held a second copy of each, used only by run.py's startup check, and
fifteen more modules nothing imported at all; they were removed 2026-11-16.

Submodule symbols resolve lazily (PEP 562): `from blue.tools import X` imports
exactly the one submodule that owns `X`, on first access.
"""

import importlib
from typing import Any

# Map of submodule name -> public symbols it exports.
# Used both for lazy attribute resolution (`from blue.tools import X`) and
# to populate `__all__`. Keep in sync with each submodule's actual exports.
_LAZY_MAP = {
    "documents": (
        "UPLOAD_FOLDER", "DOCUMENTS_FOLDER", "MAX_FILE_SIZE",
        "ALLOWED_EXTENSIONS", "DOCUMENT_INDEX_FILE",
        "load_document_index", "save_document_index", "allowed_file",
        "ensure_unique_path", "get_file_hash", "encode_image_to_base64",
        "extract_text_from_file", "add_document_to_rag",
        "search_documents_rag", "search_documents_local",
        "create_document_file",
    ),
    "web": (
        "execute_web_search", "get_weather_data", "execute_browse_website",
        "SEARCH_MAX_PER_MINUTE", "SEARCH_CACHE_TTL_SEC",
        "SEARCH_RESULTS_PER_QUERY",
    ),
    "scholar": (
        "execute_scholar_search", "execute_get_paper", "execute_read_paper",
        "library_account_status", "proxy_link",
        "omni_search_url", "WLU_PROXY_PREFIX", "OMNI_HOST", "OMNI_VID",
        "SCHOLAR_MAX_PER_MINUTE", "SCHOLAR_CACHE_TTL_SEC",
        "SCHOLAR_RESULTS_PER_QUERY",
    ),
    "calendar": (
        "CalendarManager", "CalendarEvent", "EventType", "RecurrenceType",
        "get_calendar_manager", "create_event_cmd", "list_events_cmd",
        "search_events_cmd", "delete_event_cmd", "execute_calendar_command",
    ),
    "social_media": (
        "SocialMediaManager", "SocialPost", "ContentIdea", "PlatformAccount",
        "Platform", "PostStatus", "ContentType", "ApprovalStatus",
        "get_social_media_manager", "draft_post_cmd", "approve_post_cmd",
        "list_posts_cmd", "get_scheduled_posts_cmd", "add_content_idea_cmd",
        "get_content_ideas_cmd", "get_engagement_stats_cmd",
        "suggest_hashtags_cmd", "connect_account_cmd",
    ),
    "facebook_integration": (
        "FacebookOAuthManager", "FacebookAPIClient", "FacebookIntegration",
        "get_facebook_integration", "setup_facebook_app_cmd",
        "connect_facebook_cmd", "complete_facebook_auth_cmd",
        "publish_to_facebook_cmd", "sync_facebook_engagement_cmd",
    ),
}

# Reverse map: public symbol -> submodule that owns it.
_NAME_TO_SUBMODULE = {
    name: submodule
    for submodule, names in _LAZY_MAP.items()
    for name in names
}

__all__ = sorted(_NAME_TO_SUBMODULE.keys())


def __getattr__(name: str) -> Any:
    submodule = _NAME_TO_SUBMODULE.get(name)
    if submodule is None:
        raise AttributeError(f"module 'blue.tools' has no attribute {name!r}")
    mod = importlib.import_module(f".{submodule}", __name__)
    value = getattr(mod, name)
    globals()[name] = value
    return value


def __dir__():
    return list(__all__)
