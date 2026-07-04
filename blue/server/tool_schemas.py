"""Tool JSON schemas extracted verbatim from bluetools.py.

bluetools.py owns the runtime TOOLS binding (TOOLS = list(RAW_TOOLS),
then filters/appends). Tool names here must stay in sync with the
tool_selector detectors and _execute_tool_internal in bluetools.py.
"""

RAW_TOOLS = [
    # ===== Direct Ohbot head control (replaces the Ohbot app on this branch) =====
    {
        "type": "function",
        "function": {
            "name": "move_head",
            "description": "Move Blue's physical head and face. USE THIS to express something with motion: nod yes, shake no, look around, blink, smile, look sad/surprised/curious, wink. Use sparingly and only when motion clearly helps the moment — not on every reply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "look_left", "look_right", "look_up", "look_down", "look_center",
                            "nod_yes", "shake_no", "blink", "wink",
                            "happy", "sad", "surprised", "curious", "neutral"
                        ],
                        "description": "Which motion or expression to perform."
                    },
                    "times": {"type": "integer", "description": "How many times for nod_yes / shake_no / blink (default 2; max 5)."}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "head_eye_color",
            "description": "Change the colour of Blue's eye LEDs. Each channel is 0-10 (e.g. r=0 g=0 b=10 for blue, r=10 g=2 b=8 for warm pink).",
            "parameters": {
                "type": "object",
                "properties": {
                    "r": {"type": "integer", "description": "Red 0-10"},
                    "g": {"type": "integer", "description": "Green 0-10"},
                    "b": {"type": "integer", "description": "Blue 0-10"}
                },
                "required": ["r", "g", "b"]
            }
        }
    },
    # ===== Enhanced Tools - Calendar & Reminders =====
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder or scheduled event. Supports natural-language times ('tomorrow at 3pm', 'in 2 hours', 'next Monday'), events with a duration (pass 'end'), repeating events of any cadence (pass 'recurrence'), an optional advance notice (pass 'remind_before'), and an optional end date for a repeat (pass 'until').",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string", "description": "Who the reminder is for (Alex, Stella, Emmy, Athena, or Vilda)"},
                    "title": {"type": "string", "description": "Short reminder title"},
                    "when": {"type": "string", "description": "Start time - natural language like 'tomorrow at 3pm', 'in 2 hours', 'next Monday at 9am', 'tonight'. For a repeating event use the first occurrence, e.g. 'wednesday at 4pm'."},
                    "description": {"type": "string", "description": "Optional detailed description"},
                    "end": {"type": "string", "description": "Optional end time for an event that spans a range, e.g. '7pm' or 'wednesday at 7pm'. Provide this whenever the user gives both a start and end time so schedule conflicts can be detected."},
                    "recurrence": {"type": "string", "description": "How often it repeats, in plain words: 'daily', 'every weekday', 'weekly', 'every 2 weeks', 'every Monday and Wednesday', 'monthly', 'yearly'. Omit for a one-time reminder."},
                    "remind_before": {"type": "string", "description": "Optional advance notice before the start, e.g. '30 minutes', '1 hour', '1 day', '1 week'. Omit to alert at the start time."},
                    "until": {"type": "string", "description": "Optional end date for a repeating event, e.g. 'December 31' or 'end of June'. Omit for an open-ended repeat."}
                },
                "required": ["user_name", "title", "when"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_reminders",
            "description": "Get upcoming reminders for a user",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "hours_ahead": {"type": "integer", "description": "Look ahead this many hours (default 168 = one week). Use a smaller value only if the user asks specifically about today."}
                },
                "required": ["user_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_reminder",
            "description": "Mark a reminder as completed",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID of the reminder to complete"}
                },
                "required": ["reminder_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "Cancel an upcoming reminder. Pass reminder_id if known, otherwise pass title_query (a few words from the reminder title) and we'll find it. Use this when the user says 'cancel', 'scratch that', 'never mind the X reminder', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "Optional ID — only if you know it from a prior get_upcoming_reminders call"},
                    "title_query": {"type": "string", "description": "Words from the reminder title to search for, e.g. 'dentist' or 'call mom'"},
                    "user_name": {"type": "string", "description": "Optional — restrict the search to one user (Alex, Stella, Emmy, Athena, Vilda)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_reminder",
            "description": "Change an existing reminder/event: move its time, rename it, change how often it repeats, set an advance notice, or edit its notes. First call get_upcoming_reminders to get the reminder_id, then call this with reminder_id plus ONLY the fields that change. Use for 'move my 3pm to 4pm', 'push the dentist to next week', 'make that repeat weekly', 'remind me a day before instead'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID of the reminder to change (from get_upcoming_reminders)"},
                    "title": {"type": "string", "description": "New title (omit to keep)"},
                    "when": {"type": "string", "description": "New start time in natural language, e.g. '4pm' or 'next Monday at 9am' (omit to keep)"},
                    "end": {"type": "string", "description": "New end time, or '' to clear the duration (omit to keep)"},
                    "description": {"type": "string", "description": "New notes (omit to keep)"},
                    "recurrence": {"type": "string", "description": "New repeat cadence in plain words ('weekly', 'every weekday'), or 'none' to stop repeating (omit to keep)"},
                    "remind_before": {"type": "string", "description": "New advance notice ('1 day', '30 minutes'), or '0' for at the time (omit to keep)"},
                    "until": {"type": "string", "description": "New repeat end date, or '' to clear (omit to keep)"}
                },
                "required": ["reminder_id"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "add_contact",
            "description": "Save a person to Blue's contacts/address book so Blue can email them by name later. Use when the user says 'add ... to my contacts', 'save ...'s email', 'remember that ...'s email is ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The person's name"},
                    "email": {"type": "string", "description": "Their email address"},
                    "phone": {"type": "string", "description": "Optional phone number"},
                    "relationship": {"type": "string", "description": "Optional relationship, e.g. 'wife', 'colleague', 'doctor'"},
                    "notes": {"type": "string", "description": "Optional notes about the person"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_contacts",
            "description": "List saved contacts, optionally filtered. Use for 'who's in my contacts', 'show my contacts', 'list everyone I have saved'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional filter on name, email, or relationship"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_contact",
            "description": "Look up one person's saved details (email, phone) by name. Use for 'what's Stella's email', 'do I have a contact for Mark', 'look up the dentist'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name (or part of it) to look up"}
                },
                "required": ["query"]
            }
        }
    },

    # ===== Enhanced Tools - Task Management =====
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task or to-do item",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Optional detailed description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Task priority"},
                    "due_date": {"type": "string", "description": "Due date in natural language or ISO format"},
                    "category": {"type": "string", "description": "Task category (work, personal, shopping, etc.)"}
                },
                "required": ["user_name", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Get tasks for a user",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "completed"], "description": "Filter by status"}
                },
                "required": ["user_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"}
                },
                "required": ["task_id"]
            }
        }
    },

    # ===== Enhanced Tools - Notes =====
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Save a note or memo",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {"type": "string", "description": "Note category"}
                },
                "required": ["user_name", "title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search through saved notes",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["user_name", "query"]
            }
        }
    },

    # ===== Enhanced Tools - Timers =====
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a countdown timer",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {"type": "integer", "description": "Timer duration in minutes"},
                    "label": {"type": "string", "description": "Timer name/label"}
                },
                "required": ["duration_minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_timers",
            "description": "Check status of all active timers",
            "parameters": {"type": "object", "properties": {}}
        }
    },

    # ===== Enhanced Tools - System Control =====
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get computer system information (CPU, memory, disk usage)",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Capture a screenshot of the screen",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Optional filename for the screenshot"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "launch_application",
            "description": "Launch an application (browser, calculator, notepad, terminal, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name (chrome, firefox, calculator, notepad, terminal, vscode, spotify)"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set system volume level",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Volume level 0-100"}
                },
                "required": ["level"]
            }
        }
    },

    # ===== Enhanced Tools - File Operations =====
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path"},
                    "pattern": {"type": "string", "description": "File pattern like *.pdf or *.txt"},
                    "recursive": {"type": "boolean", "description": "Search subdirectories"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a text file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to the file"}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": "Get detailed information about a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"}
                },
                "required": ["filepath"]
            }
        }
    },

    # ===== Enhanced Tools - Educational & Storytelling =====
    {
        "type": "function",
        "function": {
            "name": "story_prompt",
            "description": "Generate an age-appropriate story prompt for a child (Emmy age 10, Athena age 8, or Vilda age 5)",
            "parameters": {
                "type": "object",
                "properties": {
                    "child_name": {"type": "string", "enum": ["Emmy", "Athena", "Vilda"], "description": "Child's name"},
                    "theme": {"type": "string", "description": "Story theme (animals, adventure, magic, etc.)"},
                    "moral": {"type": "string", "description": "Moral or lesson to teach"},
                    "length": {"type": "string", "enum": ["short", "medium", "long"]}
                },
                "required": ["child_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "educational_activity",
            "description": "Suggest an age-appropriate educational activity",
            "parameters": {
                "type": "object",
                "properties": {
                    "child_name": {"type": "string", "enum": ["Emmy", "Athena", "Vilda"]},
                    "subject": {"type": "string", "enum": ["math", "science", "reading", "art", "writing"]}
                },
                "required": ["child_name", "subject"]
            }
        }
    },

    # ===== Enhanced Tools - Location & Time =====
    {
        "type": "function",
        "function": {
            "name": "get_local_time",
            "description": "Get current local time and date",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sunrise_sunset",
            "description": "Get sunrise and sunset times for today",
            "parameters": {"type": "object", "properties": {}}
        }
    },

    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "START playing new music. USE THIS when user wants to: play a song, play an artist, 'put on some music'. DO NOT USE for: pausing, skipping, or volume control (use control_music for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Song name, artist, or search query (e.g., 'Bohemian Rhapsody', 'Taylor Swift Shake It Off', 'relaxing jazz')"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["play", "search"],
                        "description": "'play' to play the song, 'search' to just find information without playing",
                        "default": "play"
                    },
                    "service": {
                        "type": "string",
                        "enum": ["youtube_music", "amazon_music"],
                        "description": "Music service to use",
                        "default": "youtube_music"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_music",
            "description": "CONTROL current playback. USE THIS for: pause, resume, skip, next, previous, volume up/down, mute. Works system-wide. DO NOT USE for: playing new music (use play_music to start playing something).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["pause", "resume", "play_pause", "next", "previous", "volume_up", "volume_down", "mute"],
                        "description": "Control action: 'pause' or 'resume' (toggle play/pause), 'next' (skip forward), 'previous' (skip back), 'volume_up', 'volume_down', 'mute'"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "music_visualizer",
            "description": "Start LIGHT SHOW synced to music. USE THIS when user wants: light show, lights to dance, party lights, sync lights with music. DO NOT USE for: regular light control like turning on/off or setting color (use control_lights for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop"],
                        "description": "'start' to begin visualizer, 'stop' to end it"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "How long to run the visualizer in seconds (default: 300 = 5 minutes)",
                        "default": 300
                    },
                    "style": {
                        "type": "string",
                        "enum": ["party", "chill", "pulse"],
                        "description": "Visualizer style: 'party' (fast colorful), 'chill' (slow smooth), 'pulse' (rhythmic)",
                        "default": "party"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search USER'S UPLOADED documents (PDFs, Word docs, text files). USE THIS when user asks about: 'my documents', 'my files', 'my contract', 'what does my document say', 'search my files'. DO NOT USE for: internet searches or general knowledge (use web_search for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant information in documents"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 3)",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_lights",
            "description": "Control Philips Hue lights. USE THIS for: turn on/off, change brightness, set color, set mood/scene (sunset, relax, etc). DO NOT USE for: music-synced light shows (use music_visualizer for 'light show' or 'lights dance').",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "brightness", "color", "mood", "status"],
                        "description": "Action: 'on', 'off', 'brightness', 'color', 'mood' (apply atmospheric scene), 'status'"
                    },
                    "light_name": {
                        "type": "string",
                        "description": "Specific light name (optional, controls all if empty)"
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Brightness 0-100 (for brightness action)"
                    },
                    "color": {
                        "type": "string",
                        "description": "Color name: red, blue, green, yellow, orange, purple, pink, white, warm white, cool white"
                    },
                    "mood": {
                        "type": "string",
                        "description": "Mood/scene name: moonlight, sunset, ocean, forest, romance, party, focus, relax, energize, movie, fireplace, arctic, sunrise, galaxy, tropical"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather and forecast",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the INTERNET for external information. USE THIS for: current events, news, general knowledge queries, 'search for X', 'google X', 'latest news about X'. DO NOT USE for: user's personal documents (use search_documents for 'my documents', 'my files', 'my contract').",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_scholar",
            "description": "Search ACADEMIC JOURNALS and the Wilfrid Laurier University library (Omni) for scholarly literature. USE THIS for: peer-reviewed articles, journal articles, academic papers, studies, literature reviews, 'find research on X', 'search the Laurier library'. Results include abstracts, citation counts, open-access PDFs, and Laurier library proxy links for full text. DO NOT USE for: general web info (use web_search) or the user's own documents (use search_documents).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Research topic or keywords, e.g. 'activity theory disability studies'"},
                    "limit": {"type": "integer", "description": "Max results (default 6, max 15)"},
                    "year_from": {"type": "integer", "description": "Only include work published in or after this year"},
                    "year_to": {"type": "integer", "description": "Only include work published in or before this year"},
                    "open_access_only": {"type": "boolean", "description": "Only return freely available (open access) papers"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_paper",
            "description": "Look up ONE specific academic paper by DOI or exact title. Returns full metadata, abstract, citation count, an APA citation, a legal open-access PDF link if one exists, and a Laurier library proxy link for the full text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "The paper's DOI, e.g. 10.1080/10749039.2016.1188352"},
                    "title": {"type": "string", "description": "Exact or near-exact paper title (used if no DOI)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_paper",
            "description": "READ the FULL TEXT of ONE academic article so you can summarize, analyze, or synthesize it. Fetches a legal open-access copy when one exists, otherwise retrieves the licensed copy through the Wilfrid Laurier University library proxy using Alex's library account. USE THIS after search_scholar/get_paper when Alex wants the actual content of a paper ('read it', 'summarize that article', 'what does the paper argue'). Fetches one article per call — do research by reading a few key papers, not by mass-downloading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doi": {"type": "string", "description": "The article's DOI (preferred — from search_scholar/get_paper results)"},
                    "url": {"type": "string", "description": "Direct article URL if no DOI is available"},
                    "title": {"type": "string", "description": "Paper title (used to resolve a DOI if neither doi nor url given)"},
                    "max_chars": {"type": "integer", "description": "Max characters of article text to return (default 12000)"},
                    "save": {"type": "boolean", "description": "Also save the article into Blue's document library (Papers folder) for future RAG citation"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_javascript",
            "description": "Execute JavaScript code",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "JavaScript code"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_document",
            "description": "Create and save a new document (text, markdown, or code file) to the documents folder. The user can then download it from the web interface at http://127.0.0.1:5000/documents",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to create (e.g., 'report.txt', 'notes.md', 'recipe.txt')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The text content to write to the file"
                    },
                    "file_type": {
                        "type": "string",
                        "enum": ["txt", "md", "json", "csv", "html"],
                        "description": "File type (default: txt). Options: txt (plain text), md (markdown), json, csv, html",
                        "default": "txt"
                    }
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_gmail",
            "description": "CHECK/READ emails from inbox. USE THIS when user wants to: check email, read inbox, show messages, see unread emails, find specific emails. DO NOT USE for: sending new emails (use send_gmail) or replying to emails (use reply_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query (e.g., 'from:john@example.com', 'subject:meeting', 'is:unread'). Leave empty to get recent emails."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of emails to return (default: 10)",
                        "default": 10
                    },
                    "include_body": {
                        "type": "boolean",
                        "description": "Whether to include full email body (default: true)",
                        "default": True
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_gmail",
            "description": "SEND/COMPOSE a NEW email. USE THIS when user wants to: send email to someone, compose new message, email an address. REQUIRES: recipient email address (extract from user message - look for name@domain.com format). DO NOT USE for: checking inbox (use read_gmail) or replying to existing emails (use reply_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text"
                    },
                    "cc": {
                        "type": "string",
                        "description": "Optional CC email addresses (comma-separated)"
                    },
                    "bcc": {
                        "type": "string",
                        "description": "Optional BCC email addresses (comma-separated)"
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "Optional list of filenames to attach from documents folder. Example: ['report.pdf', 'data.xlsx']"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reply_gmail",
            "description": "REPLY to an EXISTING email. USE THIS when user wants to: reply to, respond to, or answer existing emails. IMPORTANT: For fanmail replies, FIRST use read_gmail to see the email content, THEN use this to reply with a contextual response. DO NOT USE for: checking inbox (use read_gmail) or sending new emails (use send_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find emails to reply to (e.g., 'subject:Fanmail', 'from:john@example.com is:unread'). Required to find which emails to reply to."
                    },
                    "reply_body": {
                        "type": "string",
                        "description": "The reply message body text. Should be contextual and personalized based on the original email content."
                    },
                    "reply_all": {
                        "type": "boolean",
                        "description": "If true, reply to all emails matching the query. If false, only reply to the first match. Default: false",
                        "default": False
                    },
                    "max_replies": {
                        "type": "integer",
                        "description": "Maximum number of emails to reply to (default: 10, max: 50)",
                        "default": 10
                    }
                },
                "required": ["query", "reply_body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_reply_emails",
            "description": "AUTONOMOUSLY scan Blue's own gmail inbox (alevantresearch@gmail.com) for personal emails and reply to every one. Anything that arrives there is by definition written to Blue. The tool skips no-reply senders, mailing lists, Promotions/Social/Updates/Forums categories, and Alex's own addresses. Each reply is BCC'd to Alex (alevant1905@gmail.com) so he has an audit copy. Use this when the user says things like 'check your email and reply', 'see if anyone wrote to you', 'answer your messages', 'handle your inbox'. DO NOT use this for: sending a brand-new email (use send_gmail), replying to one specific known email by query (use reply_gmail), or just reading the inbox (use read_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_hours": {
                        "type": "integer",
                        "description": "How far back to scan, in hours (default 24, max 168).",
                        "default": 24
                    },
                    "max_replies": {
                        "type": "integer",
                        "description": "Maximum number of replies to send this run (default 5, max 20).",
                        "default": 5
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, list which emails would be replied to and preview the drafts without sending. Default false.",
                        "default": False
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "View and analyze a SPECIFIC image file when user EXPLICITLY asks to see/view/look at it. ONLY use this when user directly requests to view an image (e.g., 'show me photo.jpg', 'look at the screenshot', 'what's in this image'). DO NOT use this just because an image filename appears in a document list - only use when user specifically wants to view the image content itself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the image file to view (e.g., 'photo.jpg', 'screenshot.png'). If not provided, will search for images by query."
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query to find images if filename not provided (e.g., 'family photo', 'diagram', 'screenshot')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "capture_camera",
            "description": "Capture a live camera view of your current surroundings. ONLY use this when user EXPLICITLY asks about what you see RIGHT NOW (e.g., 'what do you see?', 'look at me', 'what's in front of you?'). DO NOT use this for general conversation, document queries, or when user doesn't specifically ask about your current visual surroundings. You can AIM the shot: 'look' physically turns your head before capturing (use it when asked what's to your left/right/up/down, or to look back at the center), and 'zoom' (1-4) magnifies part of the view ('zoom_region' picks which part) — use zoom when asked to look closer at something or when you need detail you couldn't make out in a previous capture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "look": {
                        "type": "string",
                        "enum": ["left", "right", "up", "down", "center"],
                        "description": "Turn your head this way before capturing (real pan/tilt)"
                    },
                    "zoom": {
                        "type": "number",
                        "description": "Digital zoom factor: 1 (full view) to 4 (close-up)"
                    },
                    "zoom_region": {
                        "type": "string",
                        "enum": ["center", "left", "right", "top", "bottom",
                                 "top-left", "top-right", "bottom-left", "bottom-right"],
                        "description": "Which part of the view to zoom into (default center)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "email_snapshot",
            "description": "Take a BRAND NEW photo with your camera RIGHT NOW and EMAIL it as an attachment from your own Gmail account. USE THIS when the user wants a picture of what you currently see delivered by email: 'email me a photo of what you see', 'take a snapshot and send it to me', 'send me a picture of the room'. When they say 'me', leave 'to' empty — it goes to Alex. DO NOT USE for just looking/describing (use capture_camera) or for emails without a fresh photo (use send_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address or contact name. Leave empty to send it to Alex."
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional short message to include in the email body"
                    },
                    "look": {
                        "type": "string",
                        "enum": ["left", "right", "up", "down", "center"],
                        "description": "Turn your head this way before capturing (real pan/tilt)"
                    },
                    "zoom": {
                        "type": "number",
                        "description": "Digital zoom factor: 1 (full view) to 4 (close-up)"
                    },
                    "zoom_region": {
                        "type": "string",
                        "enum": ["center", "left", "right", "top", "bottom",
                                 "top-left", "top-right", "bottom-left", "bottom-right"],
                        "description": "Which part of the view to zoom into (default center)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_visual_memory",
            "description": "Recall what you have seen before. Use when user asks about past visual experiences like 'what did you see earlier?', 'who was here before?', 'what's changed?', 'what happened today?'. Returns your visual memory timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query to filter memories (e.g., 'kitchen', 'Emmy', 'morning')"
                    },
                    "hours": {
                        "type": "integer",
                        "description": "How many hours back to look (default: 24)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_person",
            "description": "Learn and remember information about a person you see. Use this when the user tells you who someone is or provides information about a person. This helps you recognize them in the future.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The person's name"
                    },
                    "appearance": {
                        "type": "string",
                        "description": "Description of how they typically look (e.g., 'woman with long brown hair', 'man with beard and glasses')"
                    },
                    "relationship": {
                        "type": "string",
                        "description": "Their relationship to the household (e.g., 'family member', 'friend', 'neighbor')"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Any additional context or information about this person"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_place",
            "description": "Learn and remember information about a location or room you see. Use this when the user tells you about a place or provides context about a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the place (e.g., 'Alex's Office', 'Living Room', 'Kitchen')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of this place and its purpose"
                    },
                    "typical_contents": {
                        "type": "string",
                        "description": "What is typically found in this location"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Any additional context about this place"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "who_do_i_know",
            "description": "List all the people you know and can recognize. Use this when asked who you know or to see your visual memory of people.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_with_chat_theory",
            "description": "Analyze a topic through Cultural-Historical Activity Theory (CHAT) lens. Use this when Alex asks to apply CHAT framework to something, or for academic analysis of technology/education topics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to analyze"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context about the situation"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_lecture",
            "description": "Generate a lecture outline for teaching. Use when Alex needs to prepare for class or wants help structuring a lecture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The lecture topic"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Lecture duration in minutes (default 50)"
                    },
                    "course": {
                        "type": "string",
                        "description": "Course name or context"
                    },
                    "level": {
                        "type": "string",
                        "description": "Student level: undergraduate, graduate, etc."
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "discussion_questions",
            "description": "Generate discussion questions for a reading or topic. Use when Alex is preparing for class discussion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reading": {
                        "type": "string",
                        "description": "The reading or text to generate questions about"
                    },
                    "topic": {
                        "type": "string",
                        "description": "The topic or theme"
                    }
                },
                "required": ["reading", "topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_student_questions",
            "description": "Simulate likely student questions and provide teaching strategies. Use when Alex is preparing to teach a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic being taught"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context about the lesson"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_proactive_suggestions",
            "description": "Check if there are any helpful proactive suggestions based on patterns and context. Use when checking in or when appropriate time has passed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]
