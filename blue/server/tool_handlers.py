"""One handler per tool, and the table that finds it.

`_execute_tool_internal` was a 651-line `if tool_name == ...` chain, 59
branches deep. Adding a tool meant finding the end of it; answering "which
tools exist?" meant reading all of it; and a name matching nothing fell
silently through to "Unknown tool" at the bottom — the failure this codebase
has hit more than any other.

Same bodies, same order, same guards. What changes is that the set of tools is
now a dict you can look at, and cross-check against the schemas.

Two conventions carried over from the chain:

  * Returning None means "not handled", and the caller answers "Unknown tool".
    That is what an unavailable subsystem did before — the branch simply did
    not match and the chain ran on — and what the four branches that fall off
    the end of their body did.
  * `get_local_time` really did have two implementations, the enhanced one
    taking precedence over a plain fallback. That precedence now lives inside
    its handler instead of in the order of a chain.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional

import bluetools as bt


def _tool_move_head(tool_name, tool_args):
    action = (tool_args.get("action") or "").lower().strip()
    times = int(tool_args.get("times") or 2)
    ok = False
    if action.startswith("look_"):
        ok = bt.blue_head.look(action[len("look_"):])
    elif action == "nod_yes":
        ok = bt.blue_head.nod_yes(times)
    elif action == "shake_no":
        ok = bt.blue_head.shake_no(times)
    elif action == "blink":
        ok = bt.blue_head.blink(times)
    elif action in ("happy", "sad", "surprised", "curious", "neutral", "wink"):
        ok = bt.blue_head.expression(action)
    if ok:
        return json.dumps({"success": True, "action": action})
    if not bt.blue_head.is_available():
        return json.dumps({"success": False, "error": "head not connected"})
    return json.dumps({"success": False, "error": f"unknown action: {action}"})


def _tool_head_eye_color(tool_name, tool_args):
    r = int(tool_args.get("r", 0))
    g = int(tool_args.get("g", 0))
    b = int(tool_args.get("b", 0))
    if bt.blue_head.eye_color(r, g, b):
        return json.dumps({"success": True, "r": r, "g": g, "b": b})
    if not bt.blue_head.is_available():
        return json.dumps({"success": False, "error": "head not connected"})
    return json.dumps({"success": False, "error": "eye colour failed"})


def _tool_play_music(tool_name, tool_args):
    query = tool_args.get("query", "")
    action = tool_args.get("action", "play")
    service = tool_args.get("service", "youtube_music")

    if action == "search":
        result = bt.search_music_info(query)
    else:
        result = bt.play_music(query, service)
    print(f"   [OK] Music action completed")
    return result


def _tool_control_music(tool_name, tool_args):
    action = tool_args.get("action", "")
    result = bt.control_music(action)
    print(f"   [OK] Music control executed")
    return result


def _tool_music_visualizer(tool_name, tool_args):
    action = tool_args.get("action", "start")

    if action == "start":
        duration = tool_args.get("duration", 300)
        style = tool_args.get("style", "party")
        result = bt.start_music_visualizer(duration, style)
    elif action == "stop":
        result = bt.stop_music_visualizer()
    else:
        result = f"Unknown visualizer action: {action}"

    print(f"   [OK] Visualizer action completed")
    return result


def _tool_control_lights(tool_name, tool_args):
    result = bt.execute_light_control(
        tool_args.get("action"),
        tool_args.get("light_name"),
        tool_args.get("brightness"),
        tool_args.get("color"),
        tool_args.get("mood")
    )
    print(f"   [OK] Light control executed")
    return result


def _tool_search_documents(tool_name, tool_args):
    query = tool_args.get("query", "")
    max_results = tool_args.get("max_results", 3)
    result = bt._search_documents_guarded(query, max_results)
    print(f"   [OK] Document search completed")

    # Check if result contains images (special JSON format)
    try:
        result_data = json.loads(result)
        if isinstance(result_data, dict) and result_data.get("_type") == "document_search_with_images":
            images = result_data.get("images", [])
            text_docs = result_data.get("text_documents", [])

            # Store images globally so they can be injected into next LLM call
            for img in images:
                bt._vision_queue.add_image(
                    filepath=img['filepath'],
                    filename=img['filename'],
                    is_camera=False
                )
            print(f"   [VISION] Stored {len(images)} image(s) for vision model")

            # Build text response
            response_parts = []
            if images:
                image_names = [img['filename'] for img in images]
                response_parts.append(f"Found {len(images)} image(s): {', '.join(image_names)}")
                response_parts.append("(Images will be shown to vision model in next response)")

            if text_docs:
                response_parts.append("\n\nText documents found:\n\n" + "\n---\n\n".join(text_docs))

            return "\n".join(response_parts) if response_parts else "Found documents."
    except (json.JSONDecodeError, TypeError):
        # Not JSON or not our special format - return as-is
        pass

    return result


def _tool_view_image(tool_name, tool_args):
    filename = tool_args.get("filename")
    query = tool_args.get("query")
    result = bt.view_image(filename=filename, query=query)
    print(f"   [OK] Image view requested")
    return result


def _tool_capture_camera(tool_name, tool_args):
    result = bt.capture_camera_image(
        look=tool_args.get("look"),
        zoom=tool_args.get("zoom"),
        zoom_region=tool_args.get("zoom_region") or "center",
    )
    print(f"   [OK] Camera capture completed")
    return result


def _tool_email_snapshot(tool_name, tool_args):
    result = bt._execute_email_snapshot(tool_args)
    print(f"   [OK] Snapshot capture+email completed")
    return result


def _tool_recall_visual_memory(tool_name, tool_args):
    if not bt.VISUAL_MEMORY_AVAILABLE:
        return json.dumps({"error": "Visual memory not available"})
    try:
        vm = bt.get_visual_memory()
        query = tool_args.get("query")
        hours = tool_args.get("hours", 24)

        if query:
            observations = vm.search_observations(
                query, limit=10, observer=bt._ACTIVE_CHAT_ROBOT)
            search_type = f"search for '{query}'"
        else:
            observations = vm.get_visual_timeline(
                hours, observer=bt._ACTIVE_CHAT_ROBOT)
            search_type = f"timeline (last {hours}h)"

        if not observations:
            return json.dumps({
                "success": True,
                "search_type": search_type,
                "message": "No visual memories found for that query.",
                "observations": []
            })

        # Format observations for the LLM
        formatted = []
        for obs in observations:
            entry = {
                "timestamp": obs.get("timestamp", ""),
                "description": obs.get("scene_description", ""),
                "location": obs.get("location"),
                "people": obs.get("people_present"),
                "objects": obs.get("notable_objects"),
                "observer": obs.get("observer"),
                "recognition": obs.get("recognition_json"),
                "has_image": bool(obs.get("image_path"))
            }
            formatted.append(entry)

        # Also get scene change info
        changes = vm.detect_scene_changes(
            "", observer=bt._ACTIVE_CHAT_ROBOT)
        result = {
            "success": True,
            "search_type": search_type,
            "total_memories": len(formatted),
            "observations": formatted,
            "_instruction": (
                f"These are {bt._ACTIVE_CHAT_ROBOT}'s own camera observations. "
                "Summarize them naturally with times and places. Distinguish "
                "embedding matches from names merely mentioned in prose."
            )
        }
        if changes.get("has_previous"):
            result["last_seen_ago"] = changes["time_since"]
        print(f"   [OK] Visual memory recall: {len(formatted)} observations ({search_type})")
        return json.dumps(result)
    except Exception as e:
        print(f"   [ERROR] Visual memory recall failed: {e}")
        return json.dumps({"error": str(e)})


def _tool_get_weather(tool_name, tool_args):
    result = bt.get_weather_data(tool_args.get("location", ""))
    print(f"   [OK] Weather retrieved")
    return result


def _tool_web_search(tool_name, tool_args):
    result = bt.execute_web_search(tool_args.get("query", ""))
    print(f"   [OK] Search completed")
    return result


def _tool_search_scholar(tool_name, tool_args):
    if not bt.SCHOLAR_AVAILABLE:
        return json.dumps({"error": "Scholarly search is not available."})
    result = bt.execute_scholar_search(tool_args)
    print(f"   [OK] Scholarly search completed")
    return result


def _tool_get_paper(tool_name, tool_args):
    if not bt.SCHOLAR_AVAILABLE:
        return json.dumps({"error": "Scholarly search is not available."})
    result = bt.execute_get_paper(tool_args)
    print(f"   [OK] Paper lookup completed")
    return result


def _tool_read_paper(tool_name, tool_args):
    if not bt.SCHOLAR_AVAILABLE:
        return json.dumps({"error": "Scholarly search is not available."})
    result = bt.execute_read_paper(tool_args)
    try:
        _rp = json.loads(result)
        if _rp.get("success"):
            print(f"   [OK] Paper read via {_rp.get('access_route')} ({_rp.get('text_chars')} chars)")
        else:
            print(f"   [WARN] Paper fetch failed: {_rp.get('error')}")
    except Exception:
        pass
    return result


def _tool_run_javascript(tool_name, tool_args):
    try:
        import js2py
        result = js2py.eval_js(tool_args.get("code", ""))
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {str(e)}"


def _tool_create_document(tool_name, tool_args):
    filename = tool_args.get("filename", "")
    content = tool_args.get("content", "")
    file_type = tool_args.get("file_type", "txt")
    result = bt.create_document_file(filename, content, file_type)
    print(f"   [OK] Document created")
    return result


def _tool_browse_website(tool_name, tool_args):
    print(f"   [DEBUG] Calling bt._execute_browse_website...")
    result = bt._execute_browse_website(tool_args)
    print(f"   [DEBUG] Got result, length: {len(result)} chars")
    # Parse the result to check success
    try:
        result_obj = json.loads(result)
        if result_obj.get("success"):
            print(f"   [OK] Browse completed - fetched {len(result_obj.get('text', ''))} chars")
        else:
            print(f"   [ERROR] Browse failed: {result_obj.get('error', 'Unknown error')}")
    except Exception:
        pass
    return result


def _tool_read_gmail(tool_name, tool_args):
    result = bt._execute_read_gmail(tool_args)
    # Add operation type to help Blue understand what just happened
    try:
        result_obj = json.loads(result)
        result_obj["_operation_type"] = "READ_EMAIL"
        result_obj["_instruction"] = "You just READ emails. User asked to check/read, NOT to reply or send."
        result = json.dumps(result_obj)
    except Exception:
        pass
    print(f"   [OK] Gmail READ completed")
    return result


def _tool_send_gmail(tool_name, tool_args):
    result = bt._execute_send_gmail(tool_args)
    # Add operation type to help Blue understand what just happened
    try:
        result_obj = json.loads(result)
        result_obj["_operation_type"] = "SEND_EMAIL"
        result_obj["_instruction"] = "You just SENT a new email. User asked to send, NOT to read or reply."
        result = json.dumps(result_obj)
    except Exception:
        pass
    print(f"   [OK] Gmail SEND completed")
    return result


def _tool_reply_gmail(tool_name, tool_args):
    result = bt._execute_reply_gmail(tool_args)
    # Add operation type to help Blue understand what just happened
    try:
        result_obj = json.loads(result)
        result_obj["_operation_type"] = "REPLY_EMAIL"
        result_obj["_instruction"] = "You just REPLIED to emails. User asked to reply/respond, NOT to just read."
        result = json.dumps(result_obj)
    except Exception:
        pass
    print(f"   [OK] Gmail REPLY completed")
    return result


def _tool_auto_reply_emails(tool_name, tool_args):
    result = bt._execute_auto_reply_inbox(tool_args)
    try:
        result_obj = json.loads(result)
        result_obj["_operation_type"] = "AUTO_REPLY_EMAILS"
        result_obj["_instruction"] = (
            "You just scanned Blue's own gmail inbox "
            "(alevantresearch@gmail.com) and sent autonomous replies "
            "to every personal email there. Summarise to the user: "
            "how many replies were sent, who they went to, and the "
            "subject lines. Note each reply is BCC'd to Alex at "
            "alevant1905@gmail.com so he can read the full text "
            "there. State ONLY what the tool result actually says — "
            "do NOT speculate about Blue's capabilities and do NOT "
            "claim Blue cannot do something the tool just did. Blue's "
            "inbox is alevantresearch@gmail.com (NOT alevant1905 or "
            "alevant@yorku.ca — those are Alex's addresses)."
        )
        result = json.dumps(result_obj)
    except Exception:
        pass
    print(f"   [OK] Gmail AUTO-REPLY completed")
    return result


def _tool_create_reminder(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        tool_args = bt._drop_ungrounded_description(tool_args)
        result = bt.CalendarManager.create_reminder(**tool_args)
        print(f"   [OK] Reminder created")
        return json.dumps(result)


def _tool_get_upcoming_reminders(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.CalendarManager.get_upcoming_reminders(**tool_args)
        print(f"   [OK] Retrieved reminders")
        return json.dumps(result)


def _tool_complete_reminder(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.CalendarManager.complete_reminder(**tool_args)
        print(f"   [OK] Reminder completed")
        return json.dumps(result)


def _tool_cancel_reminder(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.CalendarManager.cancel_reminder(**tool_args)


def _tool_reschedule_reminder(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.CalendarManager.update_reminder(**tool_args)


def _tool_add_contact(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.ContactManager.add_contact(**tool_args)


def _tool_list_contacts(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.ContactManager.list_contacts(**tool_args)


def _tool_find_contact(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.ContactManager.find_contact(**tool_args)
        print(f"   [OK] Reminder cancel attempt: success={result.get('success')}")
        return json.dumps(result)


def _tool_create_task(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.TaskManager.create_task(**tool_args)
        print(f"   [OK] Task created")
        return json.dumps(result)


def _tool_get_tasks(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.TaskManager.get_tasks(**tool_args)
        print(f"   [OK] Retrieved tasks")
        return json.dumps(result)


def _tool_complete_task(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.TaskManager.complete_task(**tool_args)
        print(f"   [OK] Task completed")
        return json.dumps(result)


def _tool_create_note(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.NoteManager.create_note(**tool_args)
        print(f"   [OK] Note saved")
        return json.dumps(result)


def _tool_search_notes(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.NoteManager.search_notes(**tool_args)
        print(f"   [OK] Note search completed")
        return json.dumps(result)


def _tool_set_timer(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.TimerManager.set_timer(**tool_args)
        print(f"   [OK] Timer set")
        return json.dumps(result)


def _tool_check_timers(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.TimerManager.check_timers()
        print(f"   [OK] Timer status checked")
        return json.dumps(result)


def _tool_get_system_info(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.SystemController.get_system_info()
        print(f"   [OK] System info retrieved")
        return json.dumps(result)


def _tool_take_screenshot(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.SystemController.take_screenshot(**tool_args)
        print(f"   [OK] Screenshot captured")
        return json.dumps(result)


def _tool_launch_application(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.SystemController.launch_application(**tool_args)
        print(f"   [OK] Application launched")
        return json.dumps(result)


def _tool_set_volume(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.SystemController.set_volume(**tool_args)
        print(f"   [OK] Volume set")
        return json.dumps(result)


def _tool_list_files(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.FileOperations.list_files(**tool_args)
        print(f"   [OK] Files listed")
        return json.dumps(result)
    else:
        return json.dumps({
            "success": False,
            "message": "File system operations are not available. Use search_documents to access uploaded documents."
        })


def _tool_read_file(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.FileOperations.read_file(**tool_args)
        print(f"   [OK] File read")
        return json.dumps(result)
    else:
        return json.dumps({
            "success": False,
            "message": "File reading is not available. Use search_documents to read uploaded documents."
        })


def _tool_write_file(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.FileOperations.write_file(**tool_args)
        print(f"   [OK] File written")
        return json.dumps(result)


def _tool_get_file_info(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.FileOperations.get_file_info(**tool_args)
        print(f"   [OK] File info retrieved")
        return json.dumps(result)


def _tool_story_prompt(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.StorytellingTools.story_prompt(**tool_args)
        print(f"   [OK] Story prompt generated")
        return json.dumps(result)


def _tool_educational_activity(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.StorytellingTools.educational_activity(**tool_args)
        print(f"   [OK] Activity suggested")
        return json.dumps(result)


def _tool_get_local_time(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.LocationServices.get_local_time()
        print(f"   [OK] Local time retrieved")
        return json.dumps(result)
    # Fallback: get_local_time works without enhanced tools
    from datetime import datetime
    now = datetime.now()
    return json.dumps({
        "success": True,
        "time": now.strftime("%I:%M %p"),
        "date": now.strftime("%A, %B %d, %Y"),
        "iso": now.isoformat()
    })


def _tool_get_sunrise_sunset(tool_name, tool_args):
    if bt.ENHANCED_TOOLS_AVAILABLE:
        result = bt.LocationServices.get_sunrise_sunset()
        print(f"   [OK] Sunrise/sunset times retrieved")
        return json.dumps(result)


def _tool_remember_person(tool_name, tool_args):
    if bt.VISUAL_MEMORY_AVAILABLE:
        name = tool_args.get("name", "")
        appearance = tool_args.get("appearance", "")
        relationship = tool_args.get("relationship", "")
        notes = tool_args.get("notes", "")

        try:
            vm = bt.get_visual_memory()
            vm.add_person(
                name=name,
                typical_appearance=appearance,
                relationship=relationship,
                notes=notes
            )
            print(f"   [OK] Remembered person: {name}")
            return json.dumps({
                "success": True,
                "message": (
                    f"I'll remember {name}'s profile. Reliable automatic face "
                    "recognition also requires a clear enrolled reference photo."
                )
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to remember person: {str(e)}"
            })


def _tool_remember_place(tool_name, tool_args):
    if bt.VISUAL_MEMORY_AVAILABLE:
        name = tool_args.get("name", "")
        description = tool_args.get("description", "")
        typical_contents = tool_args.get("typical_contents", "")
        notes = tool_args.get("notes", "")

        try:
            vm = bt.get_visual_memory()
            vm.add_place(
                name=name,
                description=description,
                typical_contents=typical_contents,
                notes=notes
            )
            print(f"   [OK] Remembered place: {name}")
            return json.dumps({
                "success": True,
                "message": f"I'll remember {name}. Next time I see this location, I'll recognize it."
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to remember place: {str(e)}"
            })


def _tool_who_do_i_know(tool_name, tool_args):
    if bt.VISUAL_MEMORY_AVAILABLE:
        try:
            vm = bt.get_visual_memory()
            people = vm.get_recognition_people()
            places = vm.get_all_places()

            result = {"people": [], "places": []}

            for person in people:
                sighting = vm.get_person_sighting(
                    person['name'], bt._ACTIVE_CHAT_ROBOT)
                result["people"].append({
                    "name": person['name'],
                    "relationship": person['relationship'],
                    "appearance": person['typical_appearance'],
                    "visual_reference_stored": bool(
                        person.get('image_path')
                        and os.path.exists(person['image_path'])
                    ),
                    "times_seen_by_this_robot": (
                        sighting.get('times_seen') if sighting else 0
                    ),
                    "last_seen_by_this_robot": (
                        sighting.get('last_seen') if sighting else None
                    ),
                })

            for place in places:
                result["places"].append({
                    "name": place['name'],
                    "description": place['description'],
                    "times_seen": place['times_seen']
                })

            print(f"   [OK] Retrieved visual memory: {len(people)} people, {len(places)} places")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to retrieve visual memory: {str(e)}"
            })


def _tool_analyze_with_chat_theory(tool_name, tool_args):
    if bt.ACADEMIC_ASSISTANT_AVAILABLE:
        topic = tool_args.get("topic", "")
        context = tool_args.get("context", "")

        result = bt.analyze_with_chat(topic, context)
        print(f"   [OK] Generated CHAT analysis for: {topic}")
        return result


def _tool_prepare_lecture(tool_name, tool_args):
    if bt.ACADEMIC_ASSISTANT_AVAILABLE:
        topic = tool_args.get("topic", "")
        duration = tool_args.get("duration", 50)
        course = tool_args.get("course", "")
        level = tool_args.get("level", "undergraduate")

        result = bt.prepare_lecture(topic, duration, course, level)
        print(f"   [OK] Generated lecture outline for: {topic}")
        return result


def _tool_discussion_questions(tool_name, tool_args):
    if bt.ACADEMIC_ASSISTANT_AVAILABLE:
        reading = tool_args.get("reading", "")
        topic = tool_args.get("topic", "")

        result = bt.generate_discussion_questions(reading, topic)
        print(f"   [OK] Generated discussion questions for: {topic}")
        return result


def _tool_simulate_student_questions(tool_name, tool_args):
    if bt.ACADEMIC_ASSISTANT_AVAILABLE:
        topic = tool_args.get("topic", "")
        context = tool_args.get("context", "")

        result = bt.simulate_student_q_and_a(topic, context)
        print(f"   [OK] Simulated student questions for: {topic}")
        return result


def _tool_check_proactive_suggestions(tool_name, tool_args):
    if bt.PROACTIVE_ASSISTANCE_AVAILABLE:
        try:
            pa = bt.get_proactive_assistance()
            # Get current person from context (default to Alex)
            person = "Alex"  # Could be enhanced to detect from visual memory

            suggestions = pa.check_for_suggestions(person)

            if suggestions:
                result = {
                    "has_suggestions": True,
                    "suggestions": [
                        {
                            "type": suggestion.suggestion_type,
                            "priority": suggestion.priority,
                            "message": suggestion.message,
                            "action_available": suggestion.action_available
                        }
                        for suggestion in suggestions
                    ]
                }
                print(f"   [OK] Found {len(suggestions)} proactive suggestions")
            else:
                result = {
                    "has_suggestions": False,
                    "message": "No suggestions at this time"
                }
                print(f"   [OK] No proactive suggestions at this time")

            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to check suggestions: {str(e)}"
            })


HANDLERS: Dict[str, Callable[..., Optional[str]]] = {
    "move_head": _tool_move_head,
    "head_eye_color": _tool_head_eye_color,
    "play_music": _tool_play_music,
    "control_music": _tool_control_music,
    "music_visualizer": _tool_music_visualizer,
    "control_lights": _tool_control_lights,
    "search_documents": _tool_search_documents,
    "view_image": _tool_view_image,
    "capture_camera": _tool_capture_camera,
    "email_snapshot": _tool_email_snapshot,
    "recall_visual_memory": _tool_recall_visual_memory,
    "get_weather": _tool_get_weather,
    "web_search": _tool_web_search,
    "search_scholar": _tool_search_scholar,
    "get_paper": _tool_get_paper,
    "read_paper": _tool_read_paper,
    "run_javascript": _tool_run_javascript,
    "create_document": _tool_create_document,
    "browse_website": _tool_browse_website,
    "read_gmail": _tool_read_gmail,
    "send_gmail": _tool_send_gmail,
    "reply_gmail": _tool_reply_gmail,
    "auto_reply_emails": _tool_auto_reply_emails,
    "create_reminder": _tool_create_reminder,
    "get_upcoming_reminders": _tool_get_upcoming_reminders,
    "complete_reminder": _tool_complete_reminder,
    "cancel_reminder": _tool_cancel_reminder,
    "reschedule_reminder": _tool_reschedule_reminder,
    "add_contact": _tool_add_contact,
    "list_contacts": _tool_list_contacts,
    "find_contact": _tool_find_contact,
    "create_task": _tool_create_task,
    "get_tasks": _tool_get_tasks,
    "complete_task": _tool_complete_task,
    "create_note": _tool_create_note,
    "search_notes": _tool_search_notes,
    "set_timer": _tool_set_timer,
    "check_timers": _tool_check_timers,
    "get_system_info": _tool_get_system_info,
    "take_screenshot": _tool_take_screenshot,
    "launch_application": _tool_launch_application,
    "set_volume": _tool_set_volume,
    "list_files": _tool_list_files,
    "read_file": _tool_read_file,
    "write_file": _tool_write_file,
    "get_file_info": _tool_get_file_info,
    "story_prompt": _tool_story_prompt,
    "educational_activity": _tool_educational_activity,
    "get_local_time": _tool_get_local_time,
    "get_sunrise_sunset": _tool_get_sunrise_sunset,
    "remember_person": _tool_remember_person,
    "remember_place": _tool_remember_place,
    "who_do_i_know": _tool_who_do_i_know,
    "analyze_with_chat_theory": _tool_analyze_with_chat_theory,
    "prepare_lecture": _tool_prepare_lecture,
    "discussion_questions": _tool_discussion_questions,
    "simulate_student_questions": _tool_simulate_student_questions,
    "check_proactive_suggestions": _tool_check_proactive_suggestions,
}
