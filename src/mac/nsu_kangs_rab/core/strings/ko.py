"""앱 화면 문구 — 한국어 판 (생성: tools/gen_strings.py, 원본 docs/plan/ui-strings.md). 키는 두 판이 같다."""

STRINGS = {
    # UI-001
    "screens.about_origin": "AI 전문가 강장묵 교수가 2026년 9월 19일 강의에서 소개한 회의 방식에서 출발했습니다. 회의와 수업 중에 실시간 전사 · 사전 지식 · 화면을 찾아 모아, 사용자의 두뇌와 지식을 증강합니다.",
    # UI-002
    "screens.mic_unavailable_tooltip": "이 앱은 마이크 입력을 지금 제공하지 않습니다",
    # UI-003
    "screens.mic_tooltip": "사용자 자신의 말과 주변 소리도 전사됩니다",
    # UI-004
    "screens.extension_label": "확장 지점",
    # UI-005
    "screens.extension_tooltip": "이 저장소를 확장하여 추가할 수 있습니다",
    # UI-006
    "screens.api_fee_text": "API 요금이 부과됩니다",
    # UI-007
    "screens.save_dir_placeholder": "이 폴더 아래 날짜 폴더에 세션마다 전사 · 정리 문서 · 캡처를 저장합니다",
    # UI-008
    "screens.effort_tooltip": "높은 단계는 첫 글자가 늦어지고 사용량이 늘어납니다",
    # UI-009
    "screens.family_tooltip": "계열의 최신 버전을 씁니다. 세션 중에는 바꿀 수 없습니다.",
    # UI-010
    "screens.first_run_heading": "처음 실행하기 전에 확인하세요",
    # UI-011
    "screens.first_run_intro": "이 앱은 수업이나 회의의 음성을 전사하고, 전사와 자료를 Claude 에 보내 답변을 받습니다. 무엇이 어디로 가는지 먼저 안내합니다.",
    # UI-012
    "label.tag_local": "로컬",
    # UI-013
    "screens.first_run_facts_2": "음성은 이 컴퓨터 안에서만 전사하며 외부로 전송하지 않습니다.",
    # UI-014
    "screens.first_run_facts_3": "전송",
    # UI-015
    "screens.first_run_facts_4": "전사된 텍스트와 캡처 · 첨부 이미지는 모델 호출을 통해 Anthropic 으로 전송됩니다.",
    # UI-016
    "screens.first_run_facts_5": "세션 기록과 캡처 파일은 이 컴퓨터의 기록 폴더에만 저장합니다.",
    # UI-017
    "label.tag_download": "내려받기",
    # UI-019
    "screens.first_run_private_key": "이 키로 찍은 화면은 클립보드에만 복사되고 폴더에는 저장되지 않습니다.",
    # UI-020
    "ctl.names": "화면 기록",
    # UI-021
    "screens.first_run_permissions": "액자 안쪽 영역을 캡처하는 데 필요합니다.",
    # UI-022
    "screens.first_run_permissions_2": "시스템 사운드 수집",
    # UI-023
    "screens.first_run_permissions_3": "화상 회의의 음성을 받는 데 필요합니다.",
    # UI-024
    "screens.first_run_permission_foot": "권한이 없어도 앱은 종료하지 않고 사유와 조치를 표시합니다. 권한은 Prof. Kang's RAB 앱에만 부여됩니다.",
    # UI-025
    "screens.first_run_understood": "위 내용을 이해했습니다.",
    # UI-026
    "screens.providers": "Claude 구독",
    # UI-027
    "screens.providers_2": "ChatGPT 구독",
    # UI-028
    "screens.providers_3": "Gemini 구독",
    # UI-029
    "label.source_system_sound": "시스템 사운드",
    # UI-030
    "label.source_system_mic": "시스템 마이크",
    # UI-031
    "label.doc_lecture": "수업",
    # UI-032
    "label.doc_meeting": "회의",
    # UI-033
    "firstrun.init___033": "데이터가 나가는 곳",
    # UI-035
    "ctl.show_permissions_035": "필요한 권한",
    # UI-036
    "firstrun.btn": "시스템 설정 열기",
    # UI-037
    "firstrun.init___037": "동의하고 시작",
    # UI-038
    "firstrun.set_permissions_038": "허용됨",
    # UI-039
    "firstrun.set_permissions_039": "허용 필요",
    # UI-040
    "screens.tag": "선택됨",
    # UI-041
    "screens.tag_2": "API 요금",
    # UI-042
    "start.init___042": "과목명",
    # UI-044
    "start.init___044": "변경…",
    # UI-045
    "start.init___045": "기본값",
    # UI-046
    "start.init___046": "세션 시작",
    # UI-047
    "start.init___047": "2. 모델 제공자",
    # UI-048
    "start.init___048": "3. 모델",
    # UI-049
    "start.init___049": "6. 음성 소스",
    # UI-050
    "start.init___050": "9. 세션 문서",
    # UI-051
    "start.init___051": "10. 세션 프롬프트",
    # UI-052
    "start.path": "저장 위치",
    # UI-053
    "start.show_checking_053": "확인 중",
    # UI-054
    "screens.init___054": "고찰 키 변경",
    # UI-055
    "screens.init___055": "새로 쓸 키를 누르세요 (앱 창 안에서만 동작합니다)",
    # UI-056
    "screens.init___056": "확인",
    # UI-057
    "setform.init___057": "단축키",
    # UI-058
    "setform.name": "고찰 키(앱 창 안)",
    # UI-059
    "setform.init___059": "답변 또는 고찰을 요청합니다. 기본값은 F2 입니다.",
    # UI-060
    "setform.init___060": "기본 프롬프트",
    # UI-061
    "setform.init___061": "기본 문구로 되돌리기",
    # UI-062
    "setform.init___062": "기본 모델 제공자",
    # UI-063
    "setform.init___063": "Claude API 키",
    # UI-064
    "ctl.confirm_model_delete_064": "삭제",
    # UI-065
    "setform.note": "API 요금이 부과됩니다. 키는 이 컴퓨터의 앱 전용 키체인 항목에 보관하며, 설정 파일 · 기록 · 로그에는 남기지 않습니다.",
    # UI-066
    "setform.init___066": "음성 소스",
    # UI-068
    "setform.init___068": "삭제…",
    # UI-069
    "setform.init___069": "테마",
    # UI-070
    "setform.notes": "macOS 의 외관(밝게 · 어둡게)을 따릅니다. 기본값입니다.",
    # UI-071
    "setform.notes_2": "항상 밝은 화면을 씁니다.",
    # UI-072
    "setform.notes_3": "항상 어두운 화면을 씁니다.",
    # UI-073
    "setform.browse_claude_073": "5. claude 실행 파일",
    # UI-076
    "setform.init___076": "/경로/claude",
    # UI-077
    "setform.init___077": "찾아보기…",
    # UI-078
    "label.claude_not_found": "claude 를 찾지 못했습니다",
    # UI-080
    "setform.init___080": "끔",
    # UI-083
    "setform.init___083": "정리 문서 템플릿",
    # UI-084
    "setform.init___084": "수업 (lecture.md)",
    # UI-085
    "setform.init___085": "회의 (meeting.md)",
    # UI-086
    "setform.init___086": "기본 템플릿으로 되돌리기",
    # UI-089
    "setform.sync_screenshot_enabled_089": "켬",
    # UI-091
    "setform.begin_key_change_091": "저장",
    # UI-092
    "setform.begin_key_change_092": "새 Claude API 키",
    # UI-093
    "screens.init___093": "입력 레벨",
    # UI-094
    "menu.mac_app_menu_text": "앱 정보",
    # UI-095
    "menu.mac_app_menu_text_2": "설정…",
    # UI-096
    "menu.mac_app_menu_text_3": "숨기기",
    # UI-097
    "menu.mac_app_menu_text_4": "다른 앱 숨기기",
    # UI-098
    "menu.mac_app_menu_text_5": "모두 보기",
    # UI-099
    "label.quit": "종료",
    # UI-100
    "menu.menu_spec": "세션",
    # UI-101
    "menu.menu_spec_2": "정리 문서 다시 만들기…",
    # UI-102
    "menu.menu_spec_3": "세션 종료…",
    # UI-103
    "menu.menu_spec_4": "편집",
    # UI-104
    "menu.menu_spec_5": "실행 취소",
    # UI-105
    "menu.menu_spec_6": "다시 실행",
    # UI-106
    "menu.menu_spec_7": "오려내기",
    # UI-107
    "menu.menu_spec_8": "복사",
    # UI-108
    "label.paste": "붙여넣기",
    # UI-109
    "menu.menu_spec_10": "모두 선택",
    # UI-110
    "menu.menu_spec_11": "요청",
    # UI-111
    "label.kind_trigger": "고찰",
    # UI-112
    "label.kind_answer": "답변",
    # UI-113
    "label.kind_reflection": "고찰",
    # UI-114
    "label.kind_summary": "요약",
    # UI-115
    "menu.menu_spec_12": "창",
    # UI-116
    "menu.menu_spec_13": "메인 창",
    # UI-117
    "menu.m_117": "액자 보이기",
    # UI-118
    "menu.menu_spec_14": "최소화",
    # UI-119
    "menu.menu_spec_15": "확대 / 축소",
    # UI-120
    "menu.menu_spec_16": "도움말",
    # UI-121
    "menu.menu_spec_17": "첫 실행 안내 다시 보기",
    # UI-122
    "menu.menu_spec_18": "필요한 권한 확인…",
    # UI-123
    "menu.tray_items_2": "앱 창 열기",
    # UI-124
    "menu.mac_app_menu_text_6": "서비스",
    # UI-125
    "menu.out": "세션 중",
    # UI-126
    "menu.tray_status_text_126": "종료 처리 중",
    # UI-127
    "menu.tray_status_text_127": "세션 없음",
    # UI-128
    "label.capture_running": "수집 중",
    "label.capture_no_input": "입력 없음",
    # UI-129
    "menu.m_129": "수집 중단",
    # UI-130
    "menu.m_130": "수집 오류",
    # UI-131
    "end.working_title": "정리 문서를 만드는 중입니다",
    # UI-132
    "end.working_sub": "전사 문서는 이미 저장했습니다.",
    # UI-133
    "end.done_title": "문서를 만들었습니다",
    # UI-134
    "end.done_sub": "전사 문서와 정리 문서가 저장 위치의 날짜 폴더에 있습니다.",
    # UI-135
    "end.failed_title": "정리 문서를 만들지 못했습니다",
    # UI-136
    "end.failed_sub": "전사 문서(transcript.txt)는 저장되어 있으며, 나중에 정리 문서를 다시 만들 수 있습니다.",
    # UI-137
    "label.result_done": "완료",
    # UI-138
    "label.result_running": "진행 중",
    # UI-139
    "label.result_failed": "실패",
    # UI-140
    "end.reasons": "한도 초과",
    # UI-141
    "end.reasons_2": "claude 실행 파일을 찾지 못했습니다",
    # UI-142
    "end.reasons_3": "본문이 비어 있습니다",
    # UI-143
    "end.reasons_4": "저장하지 못했습니다",
    # UI-144
    "end.reasons_5": "프로세스가 종료되었습니다",
    # UI-145
    "end.reasons_6": "시간이 초과되었습니다",
    # UI-146
    "end.reasons_7": "인증을 확인하지 못했습니다",
    # UI-147
    "end.init___147": "세션 종료",
    # UI-148
    "label.cancel": "취소",
    # UI-149
    "end.init___149": "닫기",
    # UI-150
    "end.init___150": "폴더 열기",
    # UI-151
    "end.init___151": "정리 문서 다시 만들기",
    # UI-152
    "end.set_info_152": "저장 위치: %s",
    # UI-153
    "end.seg": "조각 %d개",
    "end.seg.one": "조각 %d개",
    # UI-154
    "end.cap": "캡처 %d장",
    "end.cap.one": "캡처 %d장",
    # UI-155
    "end.apply_155": "%s를 저장했습니다",
    # UI-156
    "end.apply_156": "전사 · %s · 질의응답 %d건으로 정리하는 중",
    "end.apply_156.one": "전사 · %s · 질의응답 %d건으로 정리하는 중",
    # UI-157
    "end.apply_157": "%s을 정리 문서에서 가리킵니다",
    # UI-158
    "end.apply_158": "정리 문서",
    # UI-159
    "end.apply_159": "이미지 %d개",
    "end.apply_159.one": "이미지 %d개",
    # UI-160
    "end.sub": "사유: 모델 호출이 실패했습니다. ",
    # UI-161
    "end.sub_2": "사유: 모델 호출이 실패했습니다(%s). ",
    # UI-162
    "end.apply_162": "만들지 못했습니다",
    # UI-163
    "main.card_delete_name": "카드 지우기",
    # UI-164
    "main.diagram_button_name": "다이어그램 만들기",
    # UI-165
    "ctl.activity": "다이어그램 만드는 중",
    # UI-166
    "main.diagram_retry_text": "다시 만들기",
    # UI-167
    "label.state_waiting": "대기 중",
    # UI-168
    "main.state_labels_2": "응답 중",
    # UI-169
    "main.judgment_line_169": "판단: 미확인",
    # UI-170
    "main.judgment_line_170": "판단: %s · %s",
    # UI-171
    "main.judgment_line_171": "판단: %s \"%s\"",
    # UI-172
    "main.judgment_line_172": "판단: %s",
    # UI-173
    "label.kind_error": "오류",
    # UI-174
    "main.jl": "요청 종류: %s",
    # UI-175
    "main.update_card_175": "전사 처리가 끝나지 않아 이 요청에서 제외한 조각: %s번",
    # UI-176
    "main.update_card_176": "싣지 못한 첨부 (%s): %s",
    # UI-177
    "main.diagram_done_177": "다이어그램을 표시하지 못했습니다",
    # UI-178
    "main.init___178": "고찰 %s",
    # UI-179
    "main.init___179": "액자 캡처",
    # UI-180
    "main.init___180": "Prompt",
    # UI-181
    "main.add_chip_181": "첨부 빼기: %s",
    # UI-182
    "main.ai_note": "판단 · 답변 · 고찰 · 화면 메모",
    # UI-183
    "main.init___183": "전사",
    # UI-184
    "main.init___184": "RAB",
    # UI-185
    "main.tick_clock_185": "세션 %02d:%02d:%02d",
    # UI-186
    "materials.cols": "이름",
    # UI-187
    "materials.cols_2": "형식",
    # UI-188
    "materials.cols_3": "크기",
    # UI-189
    "materials.cols_4": "문자 수",
    # UI-190
    "materials.file_filter": "자료 (*.md *.txt *.pdf *.png *.jpg *.jpeg *.gif *.webp);;모든 파일 (*)",
    # UI-191
    "materials.paste_name": "붙여넣은 글",
    # UI-192
    "materials.init___192": "추가할 수 없는 자료가 있습니다",
    # UI-193
    "materials.init___193": "선택한 자료 빼기",
    # UI-194
    "materials.init___194": "보류된 자료",
    # UI-195
    "materials.init___195": "사전 지식",
    # UI-196
    "materials.init___196": "파일 추가…",
    # UI-197
    "materials.init___197": "글 붙여넣기…",
    # UI-198
    "materials.init___198": "붙여넣을 글",
    # UI-199
    "materials.init___199": "사전 지식 없음",
    # UI-200
    "materials.title": "8. 사전 지식",
    # UI-201
    "materials.refresh_201": "사전 지식 %d개 · 합계 약 %s자",
    # UI-202
    "materials.chars": "%s자",
    "materials.chars.one": "%s자",
    # UI-203
    "materials.btn": "제거",
    # UI-204
    "materials.make_row_204": "자료 제거",
    # UI-205
    "materials.pick_files_205": "자료 파일 선택",
    # UI-206
    "materials.after_add_206": "추가: ",
    # UI-207
    "materials.after_remove_207": "단독으로 상한을 넘어 추가하지 않았습니다: ",
    # UI-208
    "materials.on_cancelled_208": "보류한 자료 %d건을 추가하지 않았습니다",
    "materials.on_cancelled_208.one": "보류한 자료 %d건을 추가하지 않았습니다",
    # UI-209
    "frame.tips": "액자 옮기기",
    # UI-210
    "frame.tips_2": "액자 숨기기",
    # UI-211
    "frame.tips_3": "액자 크기 바꾸기",
    # UI-212
    "ctl.diagram_fail_text": "다이어그램을 만들지 못했습니다: 시간 초과",
    # UI-213
    "ctl.diagram_fail_text_2": "다이어그램을 만들지 못했습니다: 파일이 만들어지지 않았습니다",
    # UI-214
    "ctl.diagram_fail_text_3": "다이어그램을 만들지 못했습니다: 인증 오류",
    # UI-215
    "ctl.diagram_fail_text_4": "다이어그램을 만들지 못했습니다: claude 를 실행하지 못했습니다",
    # UI-216
    "ctl.diagram_fail_text_5": "다이어그램을 만들지 못했습니다: 프로세스가 끝났습니다",
    # UI-217
    "ctl.diagram_fail_text_217": "다이어그램을 만들지 못했습니다: ",
    # UI-218
    "ctl.diagram_fail_text_218": "다이어그램을 만들지 못했습니다",
    # UI-219
    "ctl.permission_screen_text": "화면 기록 권한이 없습니다",
    # UI-220
    "ctl.notice_text": "응답이 진행 중이므로 고찰을 무시했습니다",
    # UI-221
    "ctl.notice_text_2": "대화 이력을 압축하는 중입니다",
    # UI-222
    "ctl.notice_text_3": "대화 이력을 압축했습니다",
    # UI-223
    "ctl.notice_text_4": "모델 프로세스를 다시 시작했습니다",
    # UI-224
    "ctl.init___224": "모델 프로세스의 시작 확인이 오지 않았습니다",
    # UI-225
    "ctl.wire_225": "붙여넣은 이미지.png",
    # UI-226
    "ctl.save_226": "설정을 저장하지 못했습니다: %s",
    # UI-227
    "ctl.save_227": "설정을 저장하지 못했습니다",
    # UI-228
    "ctl.capture_frame_228": "captures 폴더를 만들지 못했습니다",
    # UI-229
    "ctl.register_capture_229": "화면을 캡처했으나 이미지를 등록하지 못했습니다",
    # UI-230
    "ctl.on_frame_capture_failed_230": "화면을 캡처하지 못했습니다 (%s)",
    # UI-231
    "ctl.open_settings_231": "설정",
    # UI-235
    "ctl.no_key_banner": "API 키가 없어 세션을 시작할 수 없습니다",
    # UI-236
    "ctl.no_key_banner_2": "조치: 아래 5. claude 실행 파일의 “Claude API 키” 칸에 키를 입력하거나, 2. 모델 제공자에서 Claude 구독을 고르세요.",
    # UI-237
    "ctl.check_line_subscription": "claude 실행 파일을 확인하였습니다. 로그인은 세션을 시작할 때 확인합니다.",
    # UI-238
    "ctl.check_line_api": "Claude API 키가 저장되어 있습니다. claude 실행 파일을 확인하였습니다. 키는 세션을 시작할 때 확인합니다.",
    # UI-239
    "ctl.no_claude_banner_2": "조치: 터미널에서 claude 를 실행해 /login 으로 로그인한 뒤 [세션 시작]을 다시 누르세요. 찾지 못한 경우 아래 5. claude 실행 파일에서 경로를 지정하세요. API 키를 고른 경우 2. 모델 제공자에서 Claude API 를 고르고 5. claude 실행 파일의 “Claude API 키” 칸에 키를 입력하세요.",
    # UI-240
    "ctl.on_key_submitted_240": "API 키를 저장했습니다",
    # UI-241
    "ctl.on_key_submitted_241": "API 키를 저장하지 못했습니다",
    # UI-242
    "ctl.on_key_submitted_242": "API 키를 저장하지 못했습니다. 저장된 키는 그대로입니다",
    # UI-243
    "ctl.on_key_delete_243": "API 키를 삭제했습니다",
    # UI-244
    "ctl.on_key_delete_244": "API 키를 삭제하지 못했습니다",
    # UI-245
    "ctl.abort_start_245": "세션을 시작하지 않았습니다. ",
    # UI-246
    "ctl.start_session_246": "세션 폴더를 만들지 못했습니다",
    # UI-247
    "ctl.start_session_247": "저장 위치에 쓸 수 없습니다",
    # UI-248
    "ctl.start_session_248": "모델 프로세스를 시작하지 못했습니다",
    # UI-249
    "ctl.m_249": "%s · %s",
    # UI-250
    "ctl.enter_session_250": "시스템 음성",
    # UI-251
    "ctl.detail": "음성 수집을 시작하지 못했습니다: %s: %s",
    # UI-253
    "ctl.on_audio_state_253": "음성 수집이 중단되었습니다",
    # UI-254
    "ctl.names_3": "마이크",
    # UI-255
    "ctl.hint": "권한은 시스템 설정의 개인정보 보호 및 보안에서 직접 바꾸세요 (화면 및 시스템 오디오 녹음 · 마이크). 이 창은 상태를 읽기만 합니다.",
    # UI-256
    "ctl.diagram_gate_256": "세션이 시작되지 않았습니다",
    # UI-257
    "ctl.diagram_gate_257": "세션을 끝내는 중입니다",
    # UI-258
    "ctl.attach_paths_258": "파일을 읽지 못했습니다: %s",
    # UI-259
    "ctl.attach_259": "세션 중에만 이미지를 첨부할 수 있습니다",
    # UI-260
    "ctl.attach_260": "%s: 이미지가 너무 커서 첨부하지 못했습니다",
    # UI-261
    "ctl.attach_261": "%s: 이미지로 읽을 수 없습니다",
    # UI-262
    "ctl.attach_262": "%s: 저장하지 못했습니다",
    # UI-263
    "ctl.activity_2": "요청 진행 중",
    # UI-264
    "ctl.activity_3": "정리 문서 만드는 중",
    # UI-265
    "ctl.folder": "세션 폴더 선택",
    # UI-266
    "ctl.rebuild_summary_266": "선택한 폴더에 session.jsonl 이 없습니다",
    # UI-267
    "ctl.rebuild_summary_267": "전사 조각이 없어 정리 문서를 만들 수 없습니다",
    # UI-268
    "label.judgment_no_question": "질문 없음",
    # UI-269
    "label.allowed": "허용",
    # UI-270
    "label.stopped": "중단",
    # UI-271
    "label.kind_screen_note": "화면메모",
    # UI-272
    "label.kind_free_question": "자유질의",
    # UI-273
    "state.m_273": "입력 없음",
    # UI-274
    "state.appearance_choices": "시스템 설정 따르기",
    # UI-275
    "state.appearance_choices_2": "밝은 화면",
    # UI-276
    "state.appearance_choices_3": "어두운 화면",
    # UI-277
    "state.status_items_277": "입력: %s",
    # UI-278
    "state.status_items_278": "사전 지식: %d개",
    # UI-279
    "state.status_items_279": "캡처 %d",
    # UI-280
    "state.status_items_280": "전사 오류 %d회",
    # UI-282
    "state.status_items_282": "요청 대기열 %d",
    # UI-283
    "state.banner_no_input_title": "입력이 없습니다",
    # UI-284
    "state.banner_no_input_causes": "수집 설정(출력 장치 · 기본 입력 장치 등)이 맞지 않습니다",
    # UI-285
    "state.banner_no_input_causes_2": "재생되거나 들어오는 소리가 없습니다(회의 음소거 · 일시 정지 · 마이크 음소거)",
    # UI-286
    "state.banner_no_input_causes_3": "OS 권한이 없습니다",
    # UI-287
    "state.banner_permission_reason": "사유: 권한 없음",
    # UI-288
    "state.start_failed_prefix": "음성 수집을 시작하지 못했습니다",
    # UI-289
    "state.banner_start_failed_text": "필요한 구성 요소가 있는지 확인하고 앱을 다시 시작하세요. 계속되면 상세 내용을 개발자에게 알려 주세요",
    # UI-290
    "state.capture_banner_290": "사유: %s",
    # UI-291
    "endflow.on_event_291": "프로세스가 끝났으나 결과가 없습니다",
    # UI-292
    "endflow.finish_text_292": "정리 문서의 본문이 비어 있습니다",
    # UI-293
    "endflow.finish_text_293": "정리 문서를 저장하지 못했습니다: %s",
    # UI-294
    "err.error_text": "로그인이 없거나 만료되었습니다. 또는 인증 출처가 고른 방식과 다릅니다",
    # UI-295
    "err.error_text_2": "구독: 터미널에서 `claude` 를 실행하여 `/login` 으로 로그인한 뒤 다시 보내세요. API: 앱을 다시 시작해 시작 화면의 5. claude 실행 파일에서 Claude API 키를 확인하거나 다시 입력하세요",
    # UI-296
    "err.error_text_3": "`claude` 실행 파일을 찾지 못했습니다",
    # UI-297
    "err.error_text_4": "앱을 다시 시작해 시작 화면의 5. claude 실행 파일에서 경로를 지정하세요",
    # UI-298
    "err.error_text_5": "사용 한도를 넘었습니다 (구독 한도는 다른 세션과 공유됩니다)",
    # UI-299
    "err.error_text_6": "한도가 풀린 뒤에 같은 요청을 다시 보내세요",
    # UI-300
    "err.error_text_7": "네트워크에 연결하지 못했습니다",
    # UI-301
    "err.error_text_8": "네트워크 연결을 확인한 뒤 다시 보내세요",
    # UI-302
    "err.error_text_9": "모델 호출 프로세스가 응답 도중에 끝났습니다",
    # UI-303
    "err.error_text_10": "다음 요청에서 앱이 프로세스를 다시 시작합니다. 다시 시작하지 못하면 대기 중인 카드를 이 오류로 끝내고, 그다음 요청에서 다시 시도합니다. 같은 오류가 반복되면 앱을 다시 시작해 시작 화면의 5. claude 실행 파일에서 경로를 확인하세요",
    # UI-304
    "err.error_text_11": "전사에 실패했습니다",
    # UI-305
    "err.error_text_12": "음성 소스와 입력 소리를 확인하세요. 전사는 다음 조각부터 이어지며 오류 횟수는 상태 표시줄에 표시됩니다",
    # UI-306
    "err.error_text_13": "출력 장치(시스템 사운드)를 확인하세요. 장치가 복구되면 수집이 이어집니다",
    # UI-307
    "err.error_text_14": "수집은 스스로 이어지지 않습니다. 필요한 구성 요소(음성 수집 보조 프로그램)가 있는지 확인하고 앱을 다시 시작하세요. 계속되면 이 오류의 상세 내용을 개발자에게 알려 주세요",
    # UI-308
    "err.error_text_15": "필요한 권한이 없습니다 (화면 기록 · 시스템 오디오 녹음 · 마이크 · 문서 폴더)",
    # UI-309
    "err.error_text_16": "시스템 설정의 개인정보 보호 및 보안에서 해당 권한(카드에 표시한 권한 이름)에 Prof. Kang's RAB 을 허용한 뒤 앱을 다시 시작하세요",
    # UI-310
    "err.error_text_17": "파일을 읽거나 쓰지 못했습니다 (저장 위치 · 세션 폴더)",
    # UI-311
    "err.error_text_18": "저장 위치가 있고 쓸 수 있는지 확인하거나 다른 저장 위치를 고르세요",
    # UI-312
    "err.restart_failed": "프로세스를 다시 시작하지 못했습니다",
    # UI-313
    "err.reason_text_313": "알 수 없는 오류가 났습니다",
    # UI-314
    "err.action_text_314": "앱을 다시 시작하세요",
    # UI-315
    "matview.unreadable_text": "파일을 찾지 못했습니다",
    # UI-316
    "matview.unreadable_text_2": "파일의 위치를 확인한 뒤 다시 추가하세요",
    # UI-317
    "matview.unreadable_text_3": "파일을 읽을 권한이 없습니다",
    # UI-318
    "matview.unreadable_text_4": "파일의 읽기 권한을 확인하고 다시 추가하세요",
    # UI-319
    "matview.unreadable_text_5": "지원하지 않는 형식입니다",
    # UI-320
    "matview.unreadable_text_6": "md · txt · pdf · png · jpg · gif · webp 파일을 추가하세요",
    # UI-321
    "matview.unreadable_text_7": "열기 암호가 있는 PDF 라서 읽을 수 없습니다",
    # UI-322
    "matview.unreadable_text_8": "암호를 푼 파일을 추가하세요 (소유자 암호만 있는 PDF 는 추가됩니다)",
    # UI-323
    "matview.unreadable_text_9": "텍스트를 추출하지 못했습니다 (스캔한 PDF 등)",
    # UI-324
    "matview.unreadable_text_10": "텍스트 층이 있는 파일이나 이미지 파일로 추가하세요 (OCR 은 범위 밖)",
    # UI-325
    "matview.unreadable_text_11": "문자 인코딩을 읽을 수 없습니다",
    # UI-326
    "matview.unreadable_text_12": "UTF-8 또는 CP949 로 저장한 파일을 추가하세요",
    # UI-327
    "matview.unreadable_text_13": "텍스트를 추출하는 데 시간이 너무 걸렸습니다",
    # UI-328
    "matview.unreadable_text_14": "파일을 나누어 추가하세요",
    # UI-329
    "matview.unreadable_text_15": "파일을 읽는 중 오류가 났습니다",
    # UI-330
    "matview.unreadable_text_16": "파일을 다시 추가하세요. 반복되면 다른 위치에 복사하여 추가하세요",
    # UI-331
    "matview.unreadable_text_17": "텍스트를 추출하는 부품을 사용할 수 없습니다",
    # UI-332
    "matview.unreadable_text_18": "앱을 다시 시작하세요. 반복되면 앱의 설치를 확인하세요",
    # UI-333
    "matview.unreadable_text_19": "이미지 한 장의 크기가 상한({limit})을 넘습니다",
    # UI-334
    "matview.unreadable_text_20": "크기를 줄인 이미지를 추가하세요",
    # UI-335
    "matview.unreadable_text_21": "사전 지식 이미지의 합계가 상한({limit})을 넘습니다",
    # UI-336
    "matview.unreadable_text_22": "사전 지식 이미지를 빼거나 더 작은 이미지를 추가하세요",
    # UI-337
    "matview.held_reason_text": "글자 수 합계가 상한({limit})을 넘습니다",
    # UI-338
    "matview.held_reason_text_2": "선택 창에서 뺄 텍스트 자료를 고르세요 (이미지를 빼도 글자 수는 줄지 않습니다)",
    # UI-339
    "matview.held_reason_text_3": "이미지 장 수가 상한({limit})을 넘습니다",
    # UI-340
    "matview.held_reason_text_4": "선택 창에서 뺄 이미지를 고르세요",
    # UI-341
    "matview.held_reason_text_5": "파일 크기가 제한을 넘습니다",
    # UI-342
    "matview.held_reason_text_6": "다른 자료를 빼도 해소되지 않으므로 취소만 제공합니다. 파일을 나누어 추가하세요",
    # UI-343
    "matview.cap_chars_text_343": "%d만 자",
    # UI-344
    "matview.cap_chars_text_344": "%d자",
    "matview.cap_chars_text_344.one": "%d자",
    # UI-345
    "matview.row_of_345": "%s · %s · %d자",
    "matview.row_of_345.one": "%s · %s · %d자",
    # UI-346
    "matview.held_text_346": "자료를 추가하지 못했습니다",
    # UI-347
    "matview.detail": "%s (파일 크기 %s, 제한 %s)",
    # UI-348
    "matview.detail_2": "%s (이 자료 %d자)",
    "matview.detail_2.one": "%s (이 자료 %d자)",
    # UI-349
    "matview.detail_3": "%d장",
    "matview.detail_3.one": "%d장",
    # UI-350
    "matview.unreadable_text_350": "읽을 수 없습니다",
    # UI-351
    "matview.reason": "상한",
    # UI-352
    "matview.marked": " [단독으로 상한을 넘어 추가되지 않습니다]",
    # UI-353
    "matview.selection_353": "상한을 넘는 자료가 있습니다. 뺄 자료를 고르면 빼면 풀리는 보류 자료가 자동으로 추가됩니다. 단독으로 상한을 넘는 자료(%s)는 추가되지 않고 보류에서 빠집니다. 취소하면 목록은 바뀌지 않습니다.",
    # UI-354
    "matview.selection_354": "상한을 넘는 자료가 있습니다. 뺄 자료를 고르면 보류된 자료가 자동으로 추가됩니다. 취소하면 목록은 바뀌지 않습니다.",
    # UI-377
    "card.cancelled_view_377": "다시 시도",
    # UI-378
    "label.cmd_reflect": "/고찰",
    # UI-379
    "label.cmd_summary": "/요약",
    # UI-380
    "label.cmd_answer": "/답변",
    # UI-381
    "label.src_capture": "캡처",
    # UI-383
    "label.src_drop": "끌어다 놓기",
    # UI-384
    "label.result_violation": "외부 자원 위반",
    # UI-385
    "settings.load_settings_385": "설정 파일을 읽지 못해 기본값을 씁니다: %s",
    # UI-386
    "settings.effort_table_386": "계열 표가 없습니다",
    # UI-387
    "settings.effort_table_387": "계열 표가 사전이 아닙니다",
    # UI-388
    "settings.effort_table_388": "efforts 가 문자열 목록이 아닙니다",
    # UI-389
    "settings.resolve_selection_389": "사용할 수 없는 제공자라 Claude 구독으로 되돌렸습니다",
    # UI-390
    "settings.resolve_selection_390": "기억한 모델 계열이 표에 없어 기본으로 되돌렸습니다",
    # UI-391
    "settings.resolve_selection_391": "effort 표가 깨졌습니다: %s",
    # UI-392
    "settings.resolve_selection_392": "기억한 effort 가 표에 없어 기본값으로 되돌렸습니다",
    # UI-393
    "ctx.add_file_393": "지원하지 않는 형식(md · txt · pdf · png · jpg · gif · webp)",
    # UI-394
    "ctx.add_file_394": "UTF-8 · CP949 로 읽을 수 없습니다",
    # UI-395
    "ctx.extract_pdf_process_395": "추출 시간 초과(%g초)",
    # UI-396
    "ctx.extract_pdf_process_396": "추출 프로세스의 출력을 읽을 수 없습니다",
    # UI-397
    "ctx.extract_pdf_process_397": "암호화된 PDF",
    # UI-398
    "ctx.extract_pdf_process_398": "텍스트를 추출하지 못했습니다",
    # UI-399
    "ctx.register_399": "이미지 한 장의 바이트가 상한(%d)을 넘습니다",
    # UI-400
    "ctx.register_400": "이미지를 줄이지 못했습니다",
    # UI-401
    "ctx.register_401": "사전 지식 이미지 합계가 상한(%d)을 넘습니다",
    # UI-402
    "label.judgment_question": "질문",
    # UI-403
    "label.judgment_answered": "이미 답이 나온 질문",
    # UI-404
    "label.judgment_unconfirmed": "미확인",
    # UI-405
    "diag.reason_violation": "외부 자원 포함",
    # UI-406
    "diag.reason_outside": "허용된 위치 밖에 파일이 생겼습니다",
    # UI-407
    "diag.skill_state_407": "다이어그램 스킬 사본이 없습니다",
    # UI-408
    "diag.skill_state_408": "다이어그램 스킬 사본이 깨졌습니다 (plugin.json)",
    # UI-409
    "diag.skill_state_409": "다이어그램 스킬 사본이 깨졌습니다 (SKILL.md)",
    # UI-410
    "diag.can_start_410": "이 카드의 다이어그램을 만드는 중입니다",
    # UI-411
    "diag.can_start_411": "다이어그램을 동시에 만들 수 있는 수(%d개)에 이르렀습니다",
    # UI-412
    "diag.submit_412": "일회성 프로세스를 만들지 못했습니다",
    # UI-413
    "diag.resolve_413": "다이어그램 파일이 만들어지지 않았습니다",
    # UI-414
    "framegeom.off_screen_notice": "저장된 액자 위치가 지금의 화면에 없어 기본 위치로 되돌렸습니다",
    # UI-415
    "input.unknown_command_notice": "알 수 없는 명령",
    # UI-416
    "msession.start_416": "시스템 프롬프트 파일을 만들지 못했습니다: %s",
    # UI-417
    "msession.start_417": "실행 파일을 찾지 못했습니다",
    # UI-418
    "msession.start_418": "실행하지 못했습니다: %s",
    # UI-419
    "msession.send_419": "프로세스에 쓰지 못했습니다",
    # UI-420
    "msession.finalize_420": "프로세스가 예기치 않게 종료되었습니다(코드 %s)",
    # UI-421
    "msession.on_init_421": "인증 출처가 고른 방식과 다릅니다(기대 %s, 실제 %s)",
    # UI-422
    "msession.fire_422": "응답 시간 초과(%s초)",
    # UI-423
    "oneshot.run_423": "일회성 프로세스를 시작하지 못했습니다",
    # UI-424
    "oneshot.on_timeout_424": "시간 초과(%s초)",
    # UI-425
    "req.dropped_reason": "요청 크기",
    # UI-426
    "req.restart_426": "프로세스를 재시작했습니다",
    # UI-427
    "req.pump_queue_427": "프로세스에 전달하지 못했습니다",
    # UI-428
    "mic.open_428": "기본 입력 장치 없음",
    # UI-429
    "mic.open_429": "열기 실패: %s",
    # UI-430
    "label.device_changed": "장치 변경",
    # UI-431
    "mic.handle_block_431": "입력이 %.0f dBFS 이하로 %.0f초 계속되었습니다",
    # UI-432
    "mic.check_432": "%.0f초 동안 입력 블록이 없습니다",
    # UI-433
    "mic.handle_finished_433": "스트림이 끝났습니다",
    # UI-434
    "sysaudio.reason_text": "화면을 찾지 못했습니다",
    # UI-435
    "sysaudio.reason_text_2": "수집을 시작하지 못했습니다",
    # UI-436
    "sysaudio.reason_text_3": "수집 스트림이 오류로 중단되었습니다",
    # UI-437
    "sysaudio.reason_text_4": "수집 프로세스가 끝났습니다",
    # UI-438
    "sysaudio.reason_text_5": "수집 보조 프로그램이 없습니다",
    # UI-439
    "attach.judge_attachments_439": "png · jpg · gif · webp 만 첨부할 수 있습니다",
    # UI-440
    "attach.judge_attachments_440": "한 번에 최대 %d장까지 첨부할 수 있습니다",
    # UI-443
    "shot.capture_443": "screencapture 가 %.0f초 안에 끝나지 않았습니다",
    # UI-444
    "shot.capture_444": "종료 코드 %s",
    # UI-445
    "shot.capture_445": "결과 파일이 없습니다",
    # UI-446
    "shot.capture_446": "결과 파일이 비어 있습니다",
    # UI-447
    "shot.capture_447": "결과가 이미지가 아닙니다",
    # UI-448
    "perm.m_448": "허용되지 않음",
    # UI-449
    "perm.m_449": "아직 묻지 않음",
    # UI-450
    "perm.m_450": "확인할 수 없음",
    # NEW-1
    "newlang.new1": "언어",
    # NEW-2
    "newlang.new2": "앱 언어",
    # NEW-3
    "newlang.new3": "음성 인식 언어",
    # NEW-4
    "newlang.new4": "음성 인식 언어는 다음 세션부터 적용하며, 세션 중에는 바꿀 수 없습니다. Claude 의 답변과 정리 문서는 음성 인식 언어로 씁니다. 전사 문서는 인식한 언어 그대로입니다.",
    # NEW-5
    "newlang.new5": "(철회: 결정 0167 7항. 설정에 이 줄을 두지 않는다)",
    # NEW-6
    "newlang.new6": "다시 시작하면 앱 화면이 {chosen}로 바뀝니다. 지금은 {current}로 보입니다.",
    # NEW-7
    "newlang.new7": "세션 중에는 바꿀 수 없습니다 (도움말)",
    # NEW-8
    "newlang.new8": "(이름 없음)",
    # NEW-9
    "newlang.new9": "정리 문서",
    # NEW-10
    "newlang.new10": "다이어그램",
    # 단계 9 키 설정 표 (NEW-11 ~ NEW-16, KEY-1 ~ KEY-9)
    "keyset.new11": "고찰 키(전역)",
    "keyset.new12": "액자 캡처 키(전역)",
    "keyset.new13": "지정 안 함",
    "keyset.new14": "키를 누르세요…",
    "keyset.new15": "비우기",
    "keyset.new16": "취소하려면 Esc 를 누르세요.",
    "keyset.key1": "{key} 는 ‘{row}’ 에 지정되어 있어 받지 않았습니다. 다른 키를 누르세요.",
    "keyset.key2": "{key} 는 이 앱의 메뉴 단축키({item})와 겹쳐 받지 않았습니다. 다른 키를 누르세요.",
    "keyset.key3": "{key} 는 macOS 의 단축키({name})와 겹쳐 받지 않았습니다. 다른 키를 누르세요.",
    "keyset.key3n_spotlight": "Spotlight 검색(⌘Space)",
    "keyset.key3n_switcher": "앱 전환(⌘Tab)",
    "keyset.key3n_spaces": "스페이스 이동(⌃← · ⌃→)",
    "keyset.key3n_screenshot": "화면 캡처(⇧⌘3 · ⇧⌘4 · ⇧⌘5)",
    "keyset.key3n_system": "시스템 단축키",
    "keyset.key4": "{key} 는 글자를 입력하는 키라 받지 않았습니다. ⌘ · ⌃ · ⌥ 와 함께 누르거나 다른 키를 누르세요.",
    "keyset.key5": "세션이 진행되는 동안만 등록됩니다. 수식 키가 없는 키는 그동안 다른 앱에서 원래 기능을 하지 않습니다.",
    "keyset.key6": "등록됨 · ",
    "keyset.key7": "전역 키를 등록하지 못했습니다",
    "keyset.key8": "{key}: 설정의 단축키 표에서 다른 키를 지정하세요. 앱 창의 단추는 그대로 쓸 수 있습니다.",
    "keyset.key9": "저장되어 있던 키 {key} 는 글자를 입력하는 키라 기본값으로 되돌렸습니다.",
    # 단계 9 일시 정지 · 정지 확인 · 수집 전 · 진행 글 (NEW-19 ~ NEW-41)
    # NEW-19
    "pause.new19": "재생",
    # NEW-20
    "pause.new20": "일시 정지",
    # NEW-21
    "pause.new21": "정지",
    # NEW-22
    "pause.new22": "전사 조작",
    # NEW-23
    "pause.new23": "일시 정지",
    # NEW-24
    "pause.new24": "일시 정지 {start} ~ {end} ({duration})",
    # NEW-25
    "pause.new25": "일시 정지 {start} ~",
    # NEW-27
    "pause.new27": "(일시 정지)",
    # NEW-28
    "stopc.new28": "세션을 끝내시겠습니까?",
    # NEW-29
    "stopc.new29": "끝내기를 누르면 수집과 전사를 멈추고 세션을 끝냅니다. 전사가 있으면 이어서 정리 문서를 만듭니다. 이 창이 떠 있는 동안 수집과 전사는 계속됩니다. 계속을 누르면 세션이 이어집니다.",
    # NEW-30
    "stopc.new30": "끝내기를 누르면 세션을 끝냅니다. 전사가 있으면 이어서 정리 문서를 만듭니다. 계속을 누르면 세션이 이어지고 수집 상태는 그대로입니다.",
    # NEW-31
    "stopc.new31": "끝내기",
    # NEW-32
    "stopc.new32": "계속",
    # NEW-33
    "before.new33": "수집 전",
    # NEW-34
    "before.new34": "음성 수집을 시작하지 않았습니다",
    # NEW-35
    "before.new35": "재생 단추를 누르면 음성 수집과 전사가 시작됩니다.",
    # NEW-36
    "before.new36": "질문 · 고찰 · 캡처로 질의하면 답이 여기에 쌓입니다.",
    # NEW-37
    "ctl.card_q": "질문",
    # NEW-38
    "endprog.new38": "{n} / {N} 절",
    # NEW-39
    "endprog.new39": "준비 중",
    # NEW-40
    "endprog.new40": "{n} / {N} 절 · 마지막 절을 쓰는 중",
    # NEW-41
    "endprog.new41": "경과 {mm:ss}",
    # NEW-26
    "pause.dur_s": "{n}초",
    "pause.dur_ms": "{m}분 {s}초",
    "pause.dur_m": "{m}분",
    "pause.dur_hm": "{h}시간 {m}분",
    "pause.dur_h": "{h}시간",
    # NEW-17
    "newlang.new17": "다른 앱이 앞에 있어도 답변 또는 고찰을 요청합니다. 세션 중에만 동작합니다. 기본값은 비어 있습니다.",
    # NEW-18
    "newlang.new18": "다른 앱이 앞에 있어도 액자 안쪽을 캡처합니다. 세션 중에만 동작합니다. 기본값은 비어 있습니다.",
    # NEW-42
    "newlang.new42": "고찰",
    # NEW-44
    "newlang.new44": "액자 캡처",
    # NEW-45
    "newlang.new45": "[재생] 을 누르면 운영체제가 화면 기록 권한을 물을 수 있습니다.",
    # NEW-46
    "newlang.new46": "마이크 권한이 허용되지 않았습니다. 시스템 설정의 개인정보 보호 및 보안에서 Prof. Kang's RAB 의 마이크를 허용한 뒤 [재생] 을 누르세요. 그래도 수집되지 않으면 앱을 다시 시작하세요.",
    # NEW-47
    "newlang.new47": "음성 인식 모델을 준비하는 중입니다 ({pct}%)",
    # NEW-48
    "newlang.new48": "음성 인식 모델을 준비하는 중입니다",
    # NEW-49
    "newlang.new49": "음성 인식 모델을 준비하는 중입니다. 준비가 끝나면 [재생] 을 누를 수 있습니다.",
    # NEW-50
    "newlang.new50": "이 macOS 에서 선택한 음성 인식 언어를 지원하지 않습니다",
    # NEW-51
    "newlang.new51": "앱을 다시 시작해 시작 화면의 7. 음성 인식 언어에서 다른 언어를 선택하세요",
    # NEW-52
    "newlang.new52": "음성 인식 모델을 내려받지 못했습니다",
    # NEW-53
    "newlang.new53": "네트워크에 연결한 뒤 [다시 시도] 를 누르세요",
    # NEW-54
    "newlang.new54": "음성 인식 중 오류가 발생했습니다",
    # NEW-55
    "newlang.new55": "[다시 시도] 를 누르고, 반복되면 세션을 다시 시작하세요",
    # NEW-56
    "newlang.new56": "이 앱은 macOS 26.0 이상이 필요합니다",
    # NEW-57
    "newlang.new57": "macOS 를 업데이트하세요",
    # NEW-58
    "newlang.new58": "이 macOS 에서 지원하지 않습니다",
    # NEW-59
    "newlang.new59": "저장된 음성 인식 언어({language})는 지원하지 않게 되어 한국어로 바꾸었습니다.",
    # NEW-59N
    "newlang.new59n": "저장된 음성 인식 언어를 지원하지 않아 한국어로 바꾸었습니다.",
    # NEW-60
    "newlang.new60": "확정되기 전의 문장을 이 요청에 포함했습니다: {range}",
    # NEW-61
    "newlang.new61": "앱은 음성을 기기 밖으로 보내지 않습니다. 음성 인식 언어 모델은 macOS 가 내려받으며, Apple 은 전사가 기기 안에서 이루어진다고 밝힙니다.",
    # NEW-62
    "newlang.new62": "회의명",
    # NEW-63
    "newlang.new63": "기본 경로로 되돌리기",
    # NEW-64
    "newlang.new64": "자동으로 찾은 경로입니다.",
    # NEW-65
    "newlang.new65": "claude 실행 파일을 찾지 못했습니다. 경로를 지정하세요.",
    # NEW-66
    "newlang.new66": "지정한 경로에 claude 실행 파일이 없습니다. 경로를 확인하세요.",
    # NEW-67
    "newlang.new67": "화면 기록 권한이 필요합니다",
    # NEW-68
    "newlang.new68": "시스템 설정의 개인정보 보호 및 보안 > 화면 및 시스템 오디오 녹음에서 Prof. Kang's RAB 을 허용한 뒤 [재생] 을 다시 누르세요. 그래도 수집되지 않으면 앱을 다시 시작하세요.",
    # NEW-69
    "newlang.new69": "마이크 권한이 필요합니다",
    # NEW-70
    "newlang.new70": "시스템 설정의 개인정보 보호 및 보안 > 마이크에서 Prof. Kang's RAB 을 허용한 뒤 [재생] 을 다시 누르세요. 그래도 수집되지 않으면 앱을 다시 시작하세요.",
    # NEW-71
    "newlang.new71": "Claude 의 답변과 정리 문서도 이 언어로 씁니다.",
    # NEW-74
    "newlang.new74": "처음 문구",
    # NEW-75
    "newlang.new75": "기본값으로 저장",
    # NEW-76
    "newlang.new76": "칸의 글을 앱이 처음 가지고 있던 문구로 되돌립니다",
    # NEW-77
    "newlang.new77": "칸의 글을 저장해 둔 기본 문구로 되돌립니다",
    # NEW-78
    "newlang.new78": "칸의 글을 기본 문구로 저장합니다. 이후에 시작하는 세션은 이 문구로 시작합니다.",
    # NEW-43
    "newlang.new43": "(결정 0176 으로 삭제)",
    # NEW-79
    "newlang.new79": "1. 앱 언어",
    # NEW-80
    "newlang.new80": "7. 음성 인식 언어",
    # NEW-81
    "newlang.new81": "4. effort",
}
