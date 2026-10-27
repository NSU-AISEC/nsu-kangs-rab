"""앱 화면 문구 — English 판 (생성: tools/gen_strings.py, 원본 docs/plan/ui-strings.md). 키는 두 판이 같다."""

STRINGS = {
    # UI-001
    "screens.about_origin": "Started from a meeting method that AI expert Professor Jang-Mook Kang introduced in his lecture on September 19, 2026. During meetings and classes, it finds and gathers real-time transcript, prior knowledge, and screen content to augment the user's brain and knowledge.",
    # UI-002
    "screens.mic_unavailable_tooltip": "This app does not provide microphone input at the moment",
    # UI-003
    "screens.mic_tooltip": "The user's own voice and ambient sounds are also transcribed",
    # UI-004
    "screens.extension_label": "Extension point",
    # UI-005
    "screens.extension_tooltip": "Can be added by extending this repository",
    # UI-006
    "screens.api_fee_text": "API fees apply",
    # UI-007
    "screens.save_dir_placeholder": "Saves the transcript, summary document, and captures for each session in a date folder under this folder",
    # UI-008
    "screens.effort_tooltip": "Higher levels delay the first characters and increase usage",
    # UI-009
    "screens.family_tooltip": "Uses the latest version of the family. Cannot be changed during a session.",
    # UI-010
    "screens.first_run_heading": "Review before first run",
    # UI-011
    "screens.first_run_intro": "This app transcribes the audio of classes or meetings and sends the transcript and materials to Claude to get answers. Here is what goes where.",
    # UI-012
    "label.tag_local": "Local",
    # UI-013
    "screens.first_run_facts_2": "Audio is transcribed only on this computer and is not sent outside.",
    # UI-014
    "screens.first_run_facts_3": "Sent",
    # UI-015
    "screens.first_run_facts_4": "Transcribed text and captured or attached images are sent to Anthropic through model calls.",
    # UI-016
    "screens.first_run_facts_5": "Session records and capture files are saved only in the records folder on this computer.",
    # UI-017
    "label.tag_download": "Download",
    # UI-019
    "screens.first_run_private_key": "A screen taken with this key is copied only to the clipboard and is not saved to a folder.",
    # UI-020
    "ctl.names": "Screen recording",
    # UI-021
    "screens.first_run_permissions": "Required to capture the area inside the frame.",
    # UI-022
    "screens.first_run_permissions_2": "System audio capture",
    # UI-023
    "screens.first_run_permissions_3": "Required to receive audio from video meetings.",
    # UI-024
    "screens.first_run_permission_foot": "Even without permissions, the app does not quit and shows the reason and what to do. Permissions are granted only to the Prof. Kang's RAB app.",
    # UI-025
    "screens.first_run_understood": "I understand the above.",
    # UI-026
    "screens.providers": "Claude subscription",
    # UI-027
    "screens.providers_2": "ChatGPT subscription",
    # UI-028
    "screens.providers_3": "Gemini subscription",
    # UI-029
    "label.source_system_sound": "System sound",
    # UI-030
    "label.source_system_mic": "System microphone",
    # UI-031
    "label.doc_lecture": "Lecture",
    # UI-032
    "label.doc_meeting": "Meeting",
    # UI-033
    "firstrun.init___033": "Where data goes",
    # UI-035
    "ctl.show_permissions_035": "Required permissions",
    # UI-036
    "firstrun.btn": "Open System Settings",
    # UI-037
    "firstrun.init___037": "Agree and start",
    # UI-038
    "firstrun.set_permissions_038": "Allowed",
    # UI-039
    "firstrun.set_permissions_039": "Permission required",
    # UI-040
    "screens.tag": "Selected",
    # UI-041
    "screens.tag_2": "API fees",
    # UI-042
    "start.init___042": "Course name",
    # UI-044
    "start.init___044": "Change…",
    # UI-045
    "start.init___045": "Default",
    # UI-046
    "start.init___046": "Start session",
    # UI-047
    "start.init___047": "2. Model provider",
    # UI-048
    "start.init___048": "3. Model",
    # UI-049
    "start.init___049": "6. Audio source",
    # UI-050
    "start.init___050": "9. Session documents",
    # UI-051
    "start.init___051": "10. Session prompt",
    # UI-052
    "start.path": "Save location",
    # UI-053
    "start.show_checking_053": "Checking",
    # UI-054
    "screens.init___054": "Change Reflect key",
    # UI-055
    "screens.init___055": "Press the new key to use (works only inside the app window)",
    # UI-056
    "screens.init___056": "OK",
    # UI-057
    "setform.init___057": "Shortcuts",
    # UI-058
    "setform.name": "Reflect key (inside app window)",
    # UI-059
    "setform.init___059": "Requests an answer or reflection. The default is F2.",
    # UI-060
    "setform.init___060": "Default prompt",
    # UI-061
    "setform.init___061": "Restore default text",
    # UI-062
    "setform.init___062": "Default model provider",
    # UI-063
    "setform.init___063": "Claude API key",
    # UI-064
    "ctl.confirm_model_delete_064": "Delete",
    # UI-065
    "setform.note": "API fees apply. The key is stored in this app's own Keychain item on this computer and is not kept in settings files, records, or logs.",
    # UI-066
    "setform.init___066": "Audio source",
    # UI-068
    "setform.init___068": "Delete…",
    # UI-069
    "setform.init___069": "Theme",
    # UI-070
    "setform.notes": "Follows the macOS appearance (light or dark). This is the default.",
    # UI-071
    "setform.notes_2": "Always uses a light appearance.",
    # UI-072
    "setform.notes_3": "Always uses a dark appearance.",
    # UI-073
    "setform.browse_claude_073": "5. claude executable",
    # UI-076
    "setform.init___076": "/path/to/claude",
    # UI-077
    "setform.init___077": "Browse…",
    # UI-078
    "label.claude_not_found": "claude not found",
    # UI-080
    "setform.init___080": "Off",
    # UI-083
    "setform.init___083": "Summary document templates",
    # UI-084
    "setform.init___084": "Lecture (lecture.md)",
    # UI-085
    "setform.init___085": "Meeting (meeting.md)",
    # UI-086
    "setform.init___086": "Restore default templates",
    # UI-089
    "setform.sync_screenshot_enabled_089": "On",
    # UI-091
    "setform.begin_key_change_091": "Save",
    # UI-092
    "setform.begin_key_change_092": "New Claude API key",
    # UI-093
    "screens.init___093": "Input level",
    # UI-094
    "menu.mac_app_menu_text": "About",
    # UI-095
    "menu.mac_app_menu_text_2": "Settings…",
    # UI-096
    "menu.mac_app_menu_text_3": "Hide",
    # UI-097
    "menu.mac_app_menu_text_4": "Hide others",
    # UI-098
    "menu.mac_app_menu_text_5": "Show all",
    # UI-099
    "label.quit": "Quit",
    # UI-100
    "menu.menu_spec": "Session",
    # UI-101
    "menu.menu_spec_2": "Recreate summary document…",
    # UI-102
    "menu.menu_spec_3": "End session…",
    # UI-103
    "menu.menu_spec_4": "Edit",
    # UI-104
    "menu.menu_spec_5": "Undo",
    # UI-105
    "menu.menu_spec_6": "Redo",
    # UI-106
    "menu.menu_spec_7": "Cut",
    # UI-107
    "menu.menu_spec_8": "Copy",
    # UI-108
    "label.paste": "Paste",
    # UI-109
    "menu.menu_spec_10": "Select all",
    # UI-110
    "menu.menu_spec_11": "Request",
    # UI-111
    "label.kind_trigger": "Reflect",
    # UI-112
    "label.kind_answer": "Answer",
    # UI-113
    "label.kind_reflection": "Reflection",
    # UI-114
    "label.kind_summary": "Summary",
    # UI-115
    "menu.menu_spec_12": "Window",
    # UI-116
    "menu.menu_spec_13": "Main window",
    # UI-117
    "menu.m_117": "Show frame",
    # UI-118
    "menu.menu_spec_14": "Minimize",
    # UI-119
    "menu.menu_spec_15": "Zoom",
    # UI-120
    "menu.menu_spec_16": "Help",
    # UI-121
    "menu.menu_spec_17": "Show first-run notice again",
    # UI-122
    "menu.menu_spec_18": "Check required permissions…",
    # UI-123
    "menu.tray_items_2": "Open app window",
    # UI-124
    "menu.mac_app_menu_text_6": "Services",
    # UI-125
    "menu.out": "In session",
    # UI-126
    "menu.tray_status_text_126": "Ending",
    # UI-127
    "menu.tray_status_text_127": "No session",
    # UI-128
    "label.capture_running": "Collecting",
    "label.capture_no_input": "No input",
    # UI-129
    "menu.m_129": "Collection stopped",
    # UI-130
    "menu.m_130": "Collection error",
    # UI-131
    "end.working_title": "Creating the summary document",
    # UI-132
    "end.working_sub": "The transcript document is already saved.",
    # UI-133
    "end.done_title": "Document created",
    # UI-134
    "end.done_sub": "The transcript document and summary document are in the date folder under the save location.",
    # UI-135
    "end.failed_title": "Could not create the summary document",
    # UI-136
    "end.failed_sub": "The transcript document (transcript.txt) is saved. You can recreate the summary document later.",
    # UI-137
    "label.result_done": "Done",
    # UI-138
    "label.result_running": "In progress",
    # UI-139
    "label.result_failed": "Failed",
    # UI-140
    "end.reasons": "Rate limit exceeded",
    # UI-141
    "end.reasons_2": "Could not find the claude executable",
    # UI-142
    "end.reasons_3": "The body is empty",
    # UI-143
    "end.reasons_4": "Could not save",
    # UI-144
    "end.reasons_5": "The process exited",
    # UI-145
    "end.reasons_6": "Timed out",
    # UI-146
    "end.reasons_7": "Could not verify authentication",
    # UI-147
    "end.init___147": "End session",
    # UI-148
    "label.cancel": "Cancel",
    # UI-149
    "end.init___149": "Close",
    # UI-150
    "end.init___150": "Open folder",
    # UI-151
    "end.init___151": "Recreate summary document",
    # UI-152
    "end.set_info_152": "Save location: %s",
    # UI-153
    "end.seg": "%d segments",
    "end.seg.one": "%d segment",
    # UI-154
    "end.cap": "%d captures",
    "end.cap.one": "%d capture",
    # UI-155
    "end.apply_155": "Saved %s",
    # UI-156
    "end.apply_156": "Summarizing transcript, %s, and %d Q&A items",
    "end.apply_156.one": "Summarizing transcript, %s, and %d Q&A item",
    # UI-157
    "end.apply_157": "%s referenced in the summary document",
    # UI-158
    "end.apply_158": "Summary document",
    # UI-159
    "end.apply_159": "%d images",
    "end.apply_159.one": "%d image",
    # UI-160
    "end.sub": "Reason: the model call failed. .",
    # UI-161
    "end.sub_2": "Reason: the model call failed (%s). .",
    # UI-162
    "end.apply_162": "Could not create",
    # UI-163
    "main.card_delete_name": "Delete card",
    # UI-164
    "main.diagram_button_name": "Create diagram",
    # UI-165
    "ctl.activity": "Creating diagram",
    # UI-166
    "main.diagram_retry_text": "Retry",
    # UI-167
    "label.state_waiting": "Waiting",
    # UI-168
    "main.state_labels_2": "Responding",
    # UI-169
    "main.judgment_line_169": "Judgment: unconfirmed",
    # UI-170
    "main.judgment_line_170": "Judgment: %s · %s",
    # UI-171
    "main.judgment_line_171": "Judgment: %s \"%s\"",
    # UI-172
    "main.judgment_line_172": "Judgment: %s",
    # UI-173
    "label.kind_error": "Error",
    # UI-174
    "main.jl": "Request type: %s",
    # UI-175
    "main.update_card_175": "Segments excluded from this request because transcription had not finished: %s",
    # UI-176
    "main.update_card_176": "Attachments that could not be included (%s): %s",
    # UI-177
    "main.diagram_done_177": "Could not display the diagram",
    # UI-178
    "main.init___178": "Reflect %s",
    # UI-179
    "main.init___179": "Capture frame",
    # UI-180
    "main.init___180": "Prompt",
    # UI-181
    "main.add_chip_181": "Remove attachment: %s",
    # UI-182
    "main.ai_note": "Judgment · Answer · Reflection · Screen note",
    # UI-183
    "main.init___183": "Transcript",
    # UI-184
    "main.init___184": "RAB",
    # UI-185
    "main.tick_clock_185": "Session %02d:%02d:%02d",
    # UI-186
    "materials.cols": "Name",
    # UI-187
    "materials.cols_2": "Format",
    # UI-188
    "materials.cols_3": "Size",
    # UI-189
    "materials.cols_4": "Characters",
    # UI-190
    "materials.file_filter": "Materials (*.md *.txt *.pdf *.png *.jpg *.jpeg *.gif *.webp);;All files (*)",
    # UI-191
    "materials.paste_name": "Pasted text",
    # UI-192
    "materials.init___192": "Some materials cannot be added",
    # UI-193
    "materials.init___193": "Remove selected materials",
    # UI-194
    "materials.init___194": "Materials on hold",
    # UI-195
    "materials.init___195": "Prior knowledge",
    # UI-196
    "materials.init___196": "Add files…",
    # UI-197
    "materials.init___197": "Paste text…",
    # UI-198
    "materials.init___198": "Text to paste",
    # UI-199
    "materials.init___199": "No prior knowledge",
    # UI-200
    "materials.title": "8. Prior knowledge",
    # UI-201
    "materials.refresh_201": "Prior knowledge: %d · total characters: about %s",
    # UI-202
    "materials.chars": "%s characters",
    "materials.chars.one": "%s character",
    # UI-203
    "materials.btn": "Remove",
    # UI-204
    "materials.make_row_204": "Remove material",
    # UI-205
    "materials.pick_files_205": "Select material files",
    # UI-206
    "materials.after_add_206": "Added: ",
    # UI-207
    "materials.after_remove_207": "Not added because each exceeds the limit on its own: ",
    # UI-208
    "materials.on_cancelled_208": "%d materials on hold were not added",
    "materials.on_cancelled_208.one": "%d material on hold was not added",
    # UI-209
    "frame.tips": "Move frame",
    # UI-210
    "frame.tips_2": "Hide frame",
    # UI-211
    "frame.tips_3": "Resize frame",
    # UI-212
    "ctl.diagram_fail_text": "Could not create the diagram: timed out",
    # UI-213
    "ctl.diagram_fail_text_2": "Could not create the diagram: no file was created",
    # UI-214
    "ctl.diagram_fail_text_3": "Could not create the diagram: authentication error",
    # UI-215
    "ctl.diagram_fail_text_4": "Could not create the diagram: could not run claude",
    # UI-216
    "ctl.diagram_fail_text_5": "Could not create the diagram: the process ended",
    # UI-217
    "ctl.diagram_fail_text_217": "Could not create the diagram: ",
    # UI-218
    "ctl.diagram_fail_text_218": "Could not create the diagram",
    # UI-219
    "ctl.permission_screen_text": "Screen recording permission is missing",
    # UI-220
    "ctl.notice_text": "Reflect ignored because a response is in progress",
    # UI-221
    "ctl.notice_text_2": "Compacting the conversation history",
    # UI-222
    "ctl.notice_text_3": "Conversation history compacted",
    # UI-223
    "ctl.notice_text_4": "Model process restarted",
    # UI-224
    "ctl.init___224": "No start confirmation was received from the model process",
    # UI-225
    "ctl.wire_225": "Pasted image.png",
    # UI-226
    "ctl.save_226": "Could not save settings: %s",
    # UI-227
    "ctl.save_227": "Could not save settings",
    # UI-228
    "ctl.capture_frame_228": "Could not create the captures folder",
    # UI-229
    "ctl.register_capture_229": "Captured the screen but could not register the image",
    # UI-230
    "ctl.on_frame_capture_failed_230": "Could not capture the screen (%s)",
    # UI-231
    "ctl.open_settings_231": "Settings",
    # UI-235
    "ctl.no_key_banner": "No API key, so the session cannot start",
    # UI-236
    "ctl.no_key_banner_2": "Action: enter the key in the “Claude API key” box of 5. claude executable below, or choose Claude subscription in 2. Model provider.",
    # UI-237
    "ctl.check_line_subscription": "The claude executable was found. The login is checked when the session starts.",
    # UI-238
    "ctl.check_line_api": "A Claude API key is saved. The claude executable was found. The key is checked when the session starts.",
    # UI-239
    "ctl.no_claude_banner_2": "Action: run claude in a terminal, log in with /login, then press [Start session] again. If it cannot be found, specify the path in 5. claude executable below. If you chose an API key, choose Claude API in 2. Model provider and enter the key in the “Claude API key” box of 5. claude executable.",
    # UI-240
    "ctl.on_key_submitted_240": "API key saved",
    # UI-241
    "ctl.on_key_submitted_241": "Could not save the API key",
    # UI-242
    "ctl.on_key_submitted_242": "Could not save the API key. The stored key is unchanged.",
    # UI-243
    "ctl.on_key_delete_243": "API key deleted",
    # UI-244
    "ctl.on_key_delete_244": "Could not delete the API key",
    # UI-245
    "ctl.abort_start_245": "Session not started. .",
    # UI-246
    "ctl.start_session_246": "Could not create the session folder",
    # UI-247
    "ctl.start_session_247": "Cannot write to the save location",
    # UI-248
    "ctl.start_session_248": "Could not start the model process",
    # UI-249
    "ctl.m_249": "%s · %s",
    # UI-250
    "ctl.enter_session_250": "System sound",
    # UI-251
    "ctl.detail": "Could not start audio capture: %s: %s",
    # UI-253
    "ctl.on_audio_state_253": "Audio capture stopped",
    # UI-254
    "ctl.names_3": "Microphone",
    # UI-255
    "ctl.hint": "Change permissions yourself in System Settings > Privacy & Security (Screen & System Audio Recording · Microphone). This window only reads their status.",
    # UI-256
    "ctl.diagram_gate_256": "The session has not started",
    # UI-257
    "ctl.diagram_gate_257": "The session is ending",
    # UI-258
    "ctl.attach_paths_258": "Could not read the file: %s",
    # UI-259
    "ctl.attach_259": "Images can be attached only during a session",
    # UI-260
    "ctl.attach_260": "%s: the image is too large to attach",
    # UI-261
    "ctl.attach_261": "%s: cannot be read as an image",
    # UI-262
    "ctl.attach_262": "%s: could not be saved",
    # UI-263
    "ctl.activity_2": "Request in progress",
    # UI-264
    "ctl.activity_3": "Creating summary document",
    # UI-265
    "ctl.folder": "Select session folder",
    # UI-266
    "ctl.rebuild_summary_266": "The selected folder has no session.jsonl",
    # UI-267
    "ctl.rebuild_summary_267": "There are no transcript segments, so a summary document cannot be created",
    # UI-268
    "label.judgment_no_question": "No question",
    # UI-269
    "label.allowed": "Allowed",
    # UI-270
    "label.stopped": "Stopped",
    # UI-271
    "label.kind_screen_note": "Screen note",
    # UI-272
    "label.kind_free_question": "Free question",
    # UI-273
    "state.m_273": "No input",
    # UI-274
    "state.appearance_choices": "Follow system settings",
    # UI-275
    "state.appearance_choices_2": "Light",
    # UI-276
    "state.appearance_choices_3": "Dark",
    # UI-277
    "state.status_items_277": "Input: %s",
    # UI-278
    "state.status_items_278": "Prior knowledge: %d",
    # UI-279
    "state.status_items_279": "Captures %d",
    # UI-280
    "state.status_items_280": "Transcript errors %d",
    # UI-282
    "state.status_items_282": "Request queue %d",
    # UI-283
    "state.banner_no_input_title": "No input detected",
    # UI-284
    "state.banner_no_input_causes": "Capture settings (output device, default input device, etc.) do not match",
    # UI-285
    "state.banner_no_input_causes_2": "No sound is playing or coming in (meeting muted, paused, or microphone muted)",
    # UI-286
    "state.banner_no_input_causes_3": "No OS permission",
    # UI-287
    "state.banner_permission_reason": "Reason: permission denied",
    # UI-288
    "state.start_failed_prefix": "Could not start audio capture",
    # UI-289
    "state.banner_start_failed_text": "Check that the required components are present and restart the app. If it continues, report the details to the developer.",
    # UI-290
    "state.capture_banner_290": "Reason: %s",
    # UI-291
    "endflow.on_event_291": "The process ended without a result",
    # UI-292
    "endflow.finish_text_292": "The summary document body is empty",
    # UI-293
    "endflow.finish_text_293": "Could not save the summary document: %s",
    # UI-294
    "err.error_text": "No login, or it has expired; or the authentication source differs from the selected method",
    # UI-295
    "err.error_text_2": "Subscription: run `claude` in a terminal, log in with `/login`, then send again. API: restart the app and check or re-enter the Claude API key in 5. claude executable on the start screen.",
    # UI-296
    "err.error_text_3": "Could not find the `claude` executable",
    # UI-297
    "err.error_text_4": "Restart the app and specify the path in 5. claude executable on the start screen.",
    # UI-298
    "err.error_text_5": "Usage limit exceeded (the subscription limit is shared with other sessions)",
    # UI-299
    "err.error_text_6": "Send the same request again after the limit resets.",
    # UI-300
    "err.error_text_7": "Could not connect to the network",
    # UI-301
    "err.error_text_8": "Check the network connection, then send again.",
    # UI-302
    "err.error_text_9": "The model call process ended during the response",
    # UI-303
    "err.error_text_10": "On the next request the app restarts the process. If it cannot restart, the waiting card ends with this error and the next request tries again. If the same error repeats, restart the app and check the path in 5. claude executable on the start screen.",
    # UI-304
    "err.error_text_11": "Transcription failed",
    # UI-305
    "err.error_text_12": "Check the audio source and the input sound. Transcription resumes from the next segment, and the error count is shown in the status bar.",
    # UI-306
    "err.error_text_13": "Check the output device (system sound). Capture resumes when the device recovers.",
    # UI-307
    "err.error_text_14": "Capture does not resume by itself. Check that the required component (audio capture helper) is present and restart the app. If it continues, report the details of this error to the developer.",
    # UI-308
    "err.error_text_15": "Required permissions are missing (screen recording · system audio recording · microphone · documents folder)",
    # UI-309
    "err.error_text_16": "In System Settings > Privacy & Security, allow Prof. Kang's RAB for the relevant permission (the permission name shown on the card), then restart the app.",
    # UI-310
    "err.error_text_17": "Could not read or write a file (save location · session folder)",
    # UI-311
    "err.error_text_18": "Check that the save location exists and is writable, or choose another save location.",
    # UI-312
    "err.restart_failed": "Could not restart the process",
    # UI-313
    "err.reason_text_313": "An unknown error occurred",
    # UI-314
    "err.action_text_314": "Restart the app",
    # UI-315
    "matview.unreadable_text": "File not found",
    # UI-316
    "matview.unreadable_text_2": "Check the file location and add it again.",
    # UI-317
    "matview.unreadable_text_3": "No permission to read the file",
    # UI-318
    "matview.unreadable_text_4": "Check the file's read permission and add it again.",
    # UI-319
    "matview.unreadable_text_5": "Unsupported format",
    # UI-320
    "matview.unreadable_text_6": "Add an md · txt · pdf · png · jpg · gif · webp file.",
    # UI-321
    "matview.unreadable_text_7": "Cannot read a PDF that requires a password to open",
    # UI-322
    "matview.unreadable_text_8": "Add the unlocked file. (A PDF with only an owner password can be added.)",
    # UI-323
    "matview.unreadable_text_9": "Could not extract text (for example, a scanned PDF)",
    # UI-324
    "matview.unreadable_text_10": "Add a file with a text layer, or add it as an image file. (OCR is out of scope.)",
    # UI-325
    "matview.unreadable_text_11": "Cannot read the character encoding",
    # UI-326
    "matview.unreadable_text_12": "Add a file saved as UTF-8 or CP949.",
    # UI-327
    "matview.unreadable_text_13": "Text extraction took too long",
    # UI-328
    "matview.unreadable_text_14": "Split the file and add the parts.",
    # UI-329
    "matview.unreadable_text_15": "An error occurred while reading the file",
    # UI-330
    "matview.unreadable_text_16": "Add the file again. If it repeats, copy it to another location and add it.",
    # UI-331
    "matview.unreadable_text_17": "The text extraction component is unavailable",
    # UI-332
    "matview.unreadable_text_18": "Restart the app. If it repeats, check the app installation.",
    # UI-333
    "matview.unreadable_text_19": "A single image exceeds the size limit ({limit})",
    # UI-334
    "matview.unreadable_text_20": "Add a smaller image",
    # UI-335
    "matview.unreadable_text_21": "The total size of prior knowledge images exceeds the limit ({limit})",
    # UI-336
    "matview.unreadable_text_22": "Remove a prior knowledge image or add a smaller one.",
    # UI-337
    "matview.held_reason_text": "The total character count exceeds the limit ({limit})",
    # UI-338
    "matview.held_reason_text_2": "Select text materials to remove in the selection window. (Removing images does not reduce the character count.)",
    # UI-339
    "matview.held_reason_text_3": "The number of images exceeds the limit ({limit})",
    # UI-340
    "matview.held_reason_text_4": "Select images to remove in the selection window.",
    # UI-341
    "matview.held_reason_text_5": "File size exceeds the limit",
    # UI-342
    "matview.held_reason_text_6": "Removing other materials does not resolve this, so only Cancel is offered. Split the file and add the parts.",
    # UI-343
    "matview.cap_chars_text_343": "%d0,000 chars",
    # UI-344
    "matview.cap_chars_text_344": "%d chars",
    "matview.cap_chars_text_344.one": "%d char",
    # UI-345
    "matview.row_of_345": "%s · %s · %d chars",
    "matview.row_of_345.one": "%s · %s · %d char",
    # UI-346
    "matview.held_text_346": "Could not add the material",
    # UI-347
    "matview.detail": "%s (file size %s, limit %s)",
    # UI-348
    "matview.detail_2": "%s (this material: %d chars)",
    "matview.detail_2.one": "%s (this material: %d char)",
    # UI-349
    "matview.detail_3": "%d images",
    "matview.detail_3.one": "%d image",
    # UI-350
    "matview.unreadable_text_350": "Cannot be read",
    # UI-351
    "matview.reason": "the limit",
    # UI-352
    "matview.marked": " [Exceeds the limit on its own and will not be added]",
    # UI-353
    "matview.selection_353": "Some materials exceed the limit. Select materials to remove, and held materials that fit after the removal are added automatically. A material that exceeds the limit on its own (%s) is not added and is dropped from the held list. If you cancel, the list does not change.",
    # UI-354
    "matview.selection_354": "Some materials exceed the limit. Select materials to remove, and held materials are added automatically. If you cancel, the list does not change.",
    # UI-377
    "card.cancelled_view_377": "Try again",
    # UI-378
    "label.cmd_reflect": "/reflect",
    # UI-379
    "label.cmd_summary": "/summary",
    # UI-380
    "label.cmd_answer": "/answer",
    # UI-381
    "label.src_capture": "Capture",
    # UI-383
    "label.src_drop": "Drag and drop",
    # UI-384
    "label.result_violation": "External resource violation",
    # UI-385
    "settings.load_settings_385": "Could not read the settings file; using defaults: %s",
    # UI-386
    "settings.effort_table_386": "no model family table",
    # UI-387
    "settings.effort_table_387": "model family table is not a dictionary",
    # UI-388
    "settings.effort_table_388": "efforts is not a list of strings",
    # UI-389
    "settings.resolve_selection_389": "The provider is unavailable, so Claude subscription was restored",
    # UI-390
    "settings.resolve_selection_390": "The remembered model family is not in the table, so the default was restored",
    # UI-391
    "settings.resolve_selection_391": "The effort table is broken: %s",
    # UI-392
    "settings.resolve_selection_392": "The remembered effort is not in the table, so the default was restored",
    # UI-393
    "ctx.add_file_393": "Unsupported format (md · txt · pdf · png · jpg · gif · webp)",
    # UI-394
    "ctx.add_file_394": "Cannot be read as UTF-8 or CP949.",
    # UI-395
    "ctx.extract_pdf_process_395": "Extraction timed out (%g s)",
    # UI-396
    "ctx.extract_pdf_process_396": "Cannot read the output of the extraction process.",
    # UI-397
    "ctx.extract_pdf_process_397": "Encrypted PDF",
    # UI-398
    "ctx.extract_pdf_process_398": "Could not extract text",
    # UI-399
    "ctx.register_399": "The size of one image exceeds the limit (%d bytes).",
    # UI-400
    "ctx.register_400": "Could not shrink the image",
    # UI-401
    "ctx.register_401": "The total size of prior knowledge images exceeds the limit (%d).",
    # UI-402
    "label.judgment_question": "Question",
    # UI-403
    "label.judgment_answered": "Already answered",
    # UI-404
    "label.judgment_unconfirmed": "Unconfirmed",
    # UI-405
    "diag.reason_violation": "External resource included",
    # UI-406
    "diag.reason_outside": "A file was created outside the allowed location.",
    # UI-407
    "diag.skill_state_407": "The diagram skill copy is missing",
    # UI-408
    "diag.skill_state_408": "The diagram skill copy is corrupted (plugin.json)",
    # UI-409
    "diag.skill_state_409": "The diagram skill copy is corrupted (SKILL.md)",
    # UI-410
    "diag.can_start_410": "A diagram for this card is being created.",
    # UI-411
    "diag.can_start_411": "The maximum number of concurrent diagrams (%d) has been reached.",
    # UI-412
    "diag.submit_412": "Could not create the one-off process",
    # UI-413
    "diag.resolve_413": "The diagram file was not created",
    # UI-414
    "framegeom.off_screen_notice": "The saved frame position is not on the current screen, so it was reset to the default position.",
    # UI-415
    "input.unknown_command_notice": "Unknown command",
    # UI-416
    "msession.start_416": "Could not create the system prompt file: %s",
    # UI-417
    "msession.start_417": "Could not find the executable",
    # UI-418
    "msession.start_418": "Could not run it: %s",
    # UI-419
    "msession.send_419": "Could not write to the process",
    # UI-420
    "msession.finalize_420": "The process exited unexpectedly (code %s)",
    # UI-421
    "msession.on_init_421": "The authentication source differs from the selected method (expected %s, actual %s)",
    # UI-422
    "msession.fire_422": "Response timed out (%s s)",
    # UI-423
    "oneshot.run_423": "Could not start the one-off process",
    # UI-424
    "oneshot.on_timeout_424": "Timed out (%s s)",
    # UI-425
    "req.dropped_reason": "request size",
    # UI-426
    "req.restart_426": "The process was restarted",
    # UI-427
    "req.pump_queue_427": "Could not pass it to the process.",
    # UI-428
    "mic.open_428": "No default input device",
    # UI-429
    "mic.open_429": "Open failed: %s",
    # UI-430
    "label.device_changed": "Device changed",
    # UI-431
    "mic.handle_block_431": "Input stayed below %.0f dBFS for %.0f s.",
    # UI-432
    "mic.check_432": "No input blocks for %.0f s",
    # UI-433
    "mic.handle_finished_433": "The stream ended",
    # UI-434
    "sysaudio.reason_text": "Could not find the display",
    # UI-435
    "sysaudio.reason_text_2": "Could not start capture",
    # UI-436
    "sysaudio.reason_text_3": "The capture stream stopped because of an error.",
    # UI-437
    "sysaudio.reason_text_4": "The capture process ended",
    # UI-438
    "sysaudio.reason_text_5": "The capture helper program is missing",
    # UI-439
    "attach.judge_attachments_439": "Only png, jpg, gif and webp can be attached.",
    # UI-440
    "attach.judge_attachments_440": "You can attach at most %d images at a time.",
    # UI-443
    "shot.capture_443": "screencapture did not finish within %.0f s.",
    # UI-444
    "shot.capture_444": "Exit code %s",
    # UI-445
    "shot.capture_445": "The result file is missing",
    # UI-446
    "shot.capture_446": "The result file is empty",
    # UI-447
    "shot.capture_447": "The result is not an image",
    # UI-448
    "perm.m_448": "Not allowed",
    # UI-449
    "perm.m_449": "Not asked yet",
    # UI-450
    "perm.m_450": "Cannot be determined",
    # NEW-1
    "newlang.new1": "Language",
    # NEW-2
    "newlang.new2": "App language",
    # NEW-3
    "newlang.new3": "Speech recognition language",
    # NEW-4
    "newlang.new4": "The speech recognition language applies from the next session and cannot be changed during a session. Claude's answers and summary documents are written in the speech recognition language. The transcript document keeps the recognized language as it is.",
    # NEW-5
    "newlang.new5": "(Retired: decision 0167, item 7. Settings no longer shows this line.)",
    # NEW-6
    "newlang.new6": "The app will switch to {chosen} after you restart it. It is still shown in {current} now.",
    # NEW-7
    "newlang.new7": "Cannot be changed during a session (tooltip)",
    # NEW-8
    "newlang.new8": "(Untitled)",
    # NEW-9
    "newlang.new9": "Summary document",
    # NEW-10
    "newlang.new10": "Diagram",
    # 단계 9 키 설정 표 (NEW-11 ~ NEW-16, KEY-1 ~ KEY-9)
    "keyset.new11": "Reflect key (global)",
    "keyset.new12": "Frame capture key (global)",
    "keyset.new13": "Not set",
    "keyset.new14": "Press a key…",
    "keyset.new15": "Clear",
    "keyset.new16": "Press Esc to cancel.",
    "keyset.key1": "{key} is already assigned to “{row}”, so it was not accepted. Press another key.",
    "keyset.key2": "{key} overlaps this app's menu shortcut ({item}), so it was not accepted. Press another key.",
    "keyset.key3": "{key} overlaps a macOS shortcut ({name}), so it was not accepted. Press another key.",
    "keyset.key3n_spotlight": "Spotlight search (⌘Space)",
    "keyset.key3n_switcher": "App switcher (⌘Tab)",
    "keyset.key3n_spaces": "Move between Spaces (⌃← · ⌃→)",
    "keyset.key3n_screenshot": "Screenshot (⇧⌘3 · ⇧⌘4 · ⇧⌘5)",
    "keyset.key3n_system": "system shortcut",
    "keyset.key4": "{key} is a typing key, so it was not accepted. Press it with ⌘, ⌃ or ⌥, or press another key.",
    "keyset.key5": "Registered only during a session. A key without a modifier loses its usual function in other apps then.",
    "keyset.key6": "Registered · ",
    "keyset.key7": "Could not register the global key",
    "keyset.key8": "{key}: choose another key in the Shortcuts table in Settings. The buttons in the app window still work.",
    "keyset.key9": "The saved key {key} is a typing key, so it was reset to the default.",
    # 단계 9 일시 정지 · 정지 확인 · 수집 전 · 진행 글 (NEW-19 ~ NEW-41)
    # NEW-19
    "pause.new19": "Play",
    # NEW-20
    "pause.new20": "Pause",
    # NEW-21
    "pause.new21": "Stop",
    # NEW-22
    "pause.new22": "Transcript controls",
    # NEW-23
    "pause.new23": "Paused",
    # NEW-24
    "pause.new24": "Paused {start} ~ {end} ({duration})",
    # NEW-25
    "pause.new25": "Paused {start} ~",
    # NEW-27
    "pause.new27": "(Paused)",
    # NEW-28
    "stopc.new28": "End the session?",
    # NEW-29
    "stopc.new29": "End session stops collection and transcription and ends the session. If there is a transcript, the summary document is created next. Collection and transcription continue while this window is open. Keep going returns to the session.",
    # NEW-30
    "stopc.new30": "End session ends the session. If there is a transcript, the summary document is created next. Keep going returns to the session, and the collection state stays as it is.",
    # NEW-31
    "stopc.new31": "End session",
    # NEW-32
    "stopc.new32": "Keep going",
    # NEW-33
    "before.new33": "Not started",
    # NEW-34
    "before.new34": "Audio collection has not started",
    # NEW-35
    "before.new35": "Press Play to start collecting and transcribing.",
    # NEW-36
    "before.new36": "Answers to questions, reflections and captures appear here.",
    # NEW-37
    "ctl.card_q": "Question",
    # NEW-38
    "endprog.new38": "Section {n} of {N}",
    # NEW-39
    "endprog.new39": "Preparing",
    # NEW-40
    "endprog.new40": "Section {n} of {N} · Writing the last section",
    # NEW-41
    "endprog.new41": "Elapsed {mm:ss}",
    # NEW-26
    "pause.dur_s": "{n} s",
    "pause.dur_ms": "{m} min {s} s",
    "pause.dur_m": "{m} min",
    "pause.dur_hm": "{h} h {m} min",
    "pause.dur_h": "{h} h",
    # NEW-17
    "newlang.new17": "Requests an answer or a reflection even when another app is in front. It works only during a session. Empty by default.",
    # NEW-18
    "newlang.new18": "Captures the inside of the frame even when another app is in front. It works only during a session. Empty by default.",
    # NEW-42
    "newlang.new42": "Reflect",
    # NEW-44
    "newlang.new44": "Capture frame",
    # NEW-45
    "newlang.new45": "Pressing Play may make the operating system ask for screen recording permission.",
    # NEW-46
    "newlang.new46": "Microphone permission is not allowed. In System Settings > Privacy & Security, allow Prof. Kang's RAB for Microphone, then press Play. If audio is still not collected, restart the app.",
    # NEW-47
    "newlang.new47": "Preparing the speech recognition model ({pct}%)",
    # NEW-48
    "newlang.new48": "Preparing the speech recognition model",
    # NEW-49
    "newlang.new49": "Preparing the speech recognition model. You can press [Play] when it is ready.",
    # NEW-50
    "newlang.new50": "This macOS does not support the selected speech recognition language",
    # NEW-51
    "newlang.new51": "Restart the app and choose another language under 7. Speech recognition language on the start screen.",
    # NEW-52
    "newlang.new52": "Could not download the speech recognition model",
    # NEW-53
    "newlang.new53": "Connect to the network, then click [Try again]",
    # NEW-54
    "newlang.new54": "An error occurred during speech recognition",
    # NEW-55
    "newlang.new55": "Click [Try again]. If it keeps happening, start the session again",
    # NEW-56
    "newlang.new56": "This app requires macOS 26.0 or later",
    # NEW-57
    "newlang.new57": "Update macOS",
    # NEW-58
    "newlang.new58": "Not supported on this macOS",
    # NEW-59
    "newlang.new59": "The saved speech recognition language ({language}) is no longer supported, so it was changed to Korean.",
    # NEW-59N
    "newlang.new59n": "The saved speech recognition language is not supported, so it was changed to Korean.",
    # NEW-60
    "newlang.new60": "Included a sentence that was not yet final in this request: {range}",
    # NEW-61
    "newlang.new61": "The app does not send audio off this device. macOS downloads the speech recognition language model, and Apple states that transcription happens on the device.",
    # NEW-62
    "newlang.new62": "Meeting name",
    # NEW-63
    "newlang.new63": "Restore default path",
    # NEW-64
    "newlang.new64": "This is the path found automatically.",
    # NEW-65
    "newlang.new65": "The claude executable was not found. Specify the path.",
    # NEW-66
    "newlang.new66": "There is no claude executable at the specified path. Check the path.",
    # NEW-67
    "newlang.new67": "Screen recording permission is required",
    # NEW-68
    "newlang.new68": "In System Settings > Privacy & Security > Screen & System Audio Recording, allow Prof. Kang's RAB, then press Play again. If audio is still not collected, restart the app.",
    # NEW-69
    "newlang.new69": "Microphone permission is required",
    # NEW-70
    "newlang.new70": "In System Settings > Privacy & Security > Microphone, allow Prof. Kang's RAB, then press Play again. If audio is still not collected, restart the app.",
    # NEW-71
    "newlang.new71": "Claude’s answers and summary documents are also written in this language.",
    # NEW-74
    "newlang.new74": "Original text",
    # NEW-75
    "newlang.new75": "Save as default",
    # NEW-76
    "newlang.new76": "Restore the text in this box to the text the app shipped with",
    # NEW-77
    "newlang.new77": "Restore the text in this box to the saved default text",
    # NEW-78
    "newlang.new78": "Save the text in this box as the default text. Sessions you start from now on begin with it.",
    # NEW-43
    "newlang.new43": "(deleted, decision 0176)",
    # NEW-79
    "newlang.new79": "1. App language",
    # NEW-80
    "newlang.new80": "7. Speech recognition language",
    # NEW-81
    "newlang.new81": "4. effort",
}
