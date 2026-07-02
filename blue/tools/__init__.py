"""
Blue Robot Tools Package
========================
Individual tool implementations.

This package exposes its submodules' public symbols lazily via PEP 562
(`__getattr__`). Importing one submodule (e.g. `from blue.tools.rag import
index_document`) no longer drags in every other submodule's module-level
side effects — face-recognition model loading, Gmail/OAuth client init,
Hue config parse, etc.

Consumers using `from blue.tools import X` still work: the lookup resolves
to exactly the one submodule that owns `X`, on first access.
"""

import importlib
from typing import Any

# Map of submodule name -> public symbols it exports.
# Used both for lazy attribute resolution (`from blue.tools import X`) and
# to populate `__all__`. Keep in sync with each submodule's actual exports.
_LAZY_MAP = {
    "music": (
        "init_youtube_music", "search_youtube_music", "get_music_mood",
        "play_music", "search_music_info", "control_music",
        "YOUTUBE_MUSIC_BROWSER", "MUSIC_SERVICE",
    ),
    "vision": (
        "ImageInfo", "VisionImageQueue", "get_vision_queue", "view_image",
        "capture_camera_image", "start_music_visualizer",
        "stop_music_visualizer", "is_visualizer_active",
        "capture_and_recognize", "recognize_uploaded_image",
        "get_recognition_context", "teach_person", "teach_place",
        "who_do_i_know", "where_do_i_know",
    ),
    "recognition": (
        "FaceRecognitionEngine", "PlaceRecognitionEngine",
        "RecognitionManager", "RecognitionResult", "FaceMatch", "PlaceMatch",
        "get_recognition_manager", "recognize_image", "enroll_person",
        "enroll_place", "list_known_people", "list_known_places",
        "forget_person", "execute_recognition_command",
    ),
    "documents": (
        "UPLOAD_FOLDER", "DOCUMENTS_FOLDER", "MAX_FILE_SIZE",
        "ALLOWED_EXTENSIONS", "DOCUMENT_INDEX_FILE",
        "load_document_index", "save_document_index", "allowed_file",
        "ensure_unique_path", "get_file_hash", "encode_image_to_base64",
        "extract_text_from_file", "add_document_to_rag",
        "search_documents_rag", "search_documents_local",
        "create_document_file",
    ),
    "lights": (
        "HUE_CONFIG", "BRIDGE_IP", "HUE_USERNAME", "COLOR_MAP",
        "MOOD_PRESETS", "get_hue_lights", "find_light_by_name",
        "control_hue_light", "apply_mood_to_lights", "execute_light_control",
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
    "gmail": (
        "GMAIL_AVAILABLE", "GMAIL_SCOPES", "get_gmail_service",
        "execute_read_gmail", "execute_send_gmail", "execute_reply_gmail",
    ),
    "gmail_enhanced": (
        "GmailEnhancedManager", "EmailTemplate", "EmailFilter",
        "ScheduledEmail", "TemplateType", "EmailCategory",
        "get_gmail_enhanced_manager", "create_template_cmd",
        "list_templates_cmd", "schedule_email_cmd",
        "list_scheduled_emails_cmd", "execute_gmail_enhanced_command",
        "PREDEFINED_TEMPLATES",
    ),
    "gmail_ai": (
        "EmailPriority", "EmailSentiment", "EmailAnalysis", "GmailAIManager",
        "get_gmail_ai_manager", "analyze_inbox_cmd", "suggest_reply_cmd",
    ),
    "gmail_bulk": (
        "GmailBulkManager", "AttachmentManager", "get_bulk_manager",
        "get_attachment_manager", "bulk_archive_cmd", "smart_cleanup_cmd",
        "find_large_emails_cmd", "unsubscribe_cmd",
    ),
    "utilities": (
        "get_current_time", "get_current_date", "get_datetime_info",
        "calculate", "convert_units", "get_system_info", "count_text",
        "generate_random", "execute_utility",
    ),
    "timers": (
        "TimerManager", "TimerEntry", "TimerType", "get_timer_manager",
        "set_timer", "set_alarm", "set_reminder", "cancel_timer_cmd",
        "list_timers_cmd", "execute_timer_command", "parse_duration",
        "parse_time",
    ),
    "notes": (
        "NotesManager", "Note", "Task", "ListItem", "TaskPriority",
        "TaskStatus", "get_notes_manager", "create_note_cmd",
        "search_notes_cmd", "delete_note_cmd", "create_task_cmd",
        "complete_task_cmd", "list_tasks_cmd", "add_to_list_cmd",
        "get_list_cmd", "check_item_cmd", "remove_from_list_cmd",
        "execute_notes_command",
    ),
    "system": (
        "get_clipboard", "set_clipboard", "take_screenshot",
        "list_screenshots", "send_notification", "launch_application",
        "open_url", "open_file", "set_volume", "get_volume",
        "get_system_status", "execute_system_command",
    ),
    "calendar": (
        "CalendarManager", "CalendarEvent", "EventType", "RecurrenceType",
        "get_calendar_manager", "create_event_cmd", "list_events_cmd",
        "search_events_cmd", "delete_event_cmd", "execute_calendar_command",
    ),
    "weather": (
        "WeatherManager", "WeatherData", "ForecastDay", "WeatherCondition",
        "get_weather_manager", "get_current_weather_cmd",
        "get_forecast_cmd", "execute_weather_command",
    ),
    "automation": (
        "AutomationManager", "Routine", "Action", "ActionType",
        "TriggerType", "get_automation_manager", "create_routine_cmd",
        "list_routines_cmd", "execute_routine_cmd", "delete_routine_cmd",
        "install_predefined_routine", "execute_automation_command",
        "PREDEFINED_ROUTINES",
    ),
    "media_library": (
        "MediaLibraryManager", "MediaCollection", "MediaItem", "MediaType",
        "MediaStatus", "get_media_library_manager", "subscribe_podcast_cmd",
        "list_subscriptions_cmd", "list_episodes_cmd", "update_progress_cmd",
        "search_media_cmd", "get_recently_played_cmd",
        "get_in_progress_cmd", "execute_media_library_command",
    ),
    "locations": (
        "LocationManager", "Location", "LocationCategory",
        "get_location_manager", "add_location_cmd", "list_locations_cmd",
        "search_locations_cmd", "get_location_cmd", "delete_location_cmd",
        "log_visit_cmd", "execute_location_command",
    ),
    "contacts": (
        "ContactManager", "Contact", "ContactType", "CommunicationType",
        "get_contact_manager", "add_contact_cmd", "list_contacts_cmd",
        "search_contacts_cmd", "get_contact_cmd", "upcoming_birthdays_cmd",
        "execute_contact_command",
    ),
    "habits": (
        "HabitManager", "Habit", "HabitFrequency", "HabitCategory",
        "get_habit_manager", "create_habit_cmd", "list_habits_cmd",
        "complete_habit_cmd", "habit_stats_cmd", "execute_habit_command",
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
