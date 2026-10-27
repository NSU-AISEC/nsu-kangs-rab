# Installing with an AI coding agent

This document is the single reference for an AI coding agent (Claude Code or another) that works with Prof. Kang's RAB: installing it on this Mac, explaining how to use it, troubleshooting it and answering questions about porting it. The README of the repository only introduces the app and the sentence a user says to start the agent; everything else is here. The document is in English.

The user starts the agent with the sentence in the "Quick start" section of [`README.en.md`](README.en.md#quick-start). To install, follow "Support scope", the rules and Steps 0 to 5. To answer a question, read the section that matches it: "About the app", "Before you start", "Update", "Troubleshooting", "Porting to another environment" or "For developers".

## Rules

Follow these at all times during installation. They protect the user's login and keys.

1. **Do not read Claude Code's credentials.** Do not open or print the Keychain item that Claude Code stored or `~/.claude/.credentials.json`, and do not run `claude setup-token`. The user checks the login state directly in `claude`.
2. **Do not handle the user's API key.** Do not ask for it, read it, print it or write it to a file. For the API key method, the user types the key directly into the “Claude API key” box of 5. claude executable on the app’s start screen (after choosing Claude API in 2. Model provider).
3. **Do not change macOS security settings.** Do not change permissions with `tccutil` or operate the privacy items in System Settings on the user's behalf. The user grants permissions.
4. **Do not act on the user's behalf in their accounts.** Do not create accounts, accept terms, or complete a sign-in screen.
5. **Ask before changing the system.** Get the user's consent once before starting a Homebrew package install or the Xcode command-line tools install. If a permission setting blocks a command, show the user the command and have them run it themselves. Do not use `sudo`.
6. **Check at every step.** Do not go to the next step until the step's "Check" passes.

Below, **[agent]** marks what the agent does and **[person]** marks a step where you stop. At a stopping step, explain what is needed, wait for the user's confirmation, then continue.

## Support scope

- **Only macOS 26.0 or later can be installed.** Speech recognition uses the SpeechTranscriber built into macOS 26. The app has been verified on Apple Silicon Macs only.
- **On Windows, the task is porting, not installing.** There is no install procedure; a user who wants to contribute to the repository follows "Porting to another environment" below.
- **Another agent may install it.** This procedure does not depend on the kind of agent. But the app calls the model through the Claude Code CLI (`claude -p`), so to use the subscription method, Claude Code must be installed and logged in; the API key method needs the key the user enters in the app.

## About the app

Use this section to explain what the app does. There is no figure here; describe the screens in words.

### How it works

1. **Listen.** It collects system sound (including the audio of video meetings) and transcribes it on your Mac in the language you choose for speech recognition. The audio never leaves it.
2. **Gather.** The transcript accumulates on screen, together with the prior knowledge you loaded in advance and the screens you captured.
3. **Ask.** Press once at the moment you need it, and the app selects as much context as is needed and queries Claude once. While you press nothing, it calls no model.
4. **Receive.** Answers, reflections and summaries pile up as cards. From a card that holds an answer you can also generate a diagram to see its structure at a glance.

### When to use it

- **When no question has been asked.** [Reflect] still gives something: the point at issue in the current discussion, a viewpoint that is missing, and questions and remarks the user could raise.
- **When the content exists only on a slide or whiteboard.** Capturing one screen hands that content to the model, and it becomes part of the conversation's context.

### Screens

- **Main window.** The transcript accumulates on the left and answer cards appear on the right. A status bar shows the provider, model, audio source, collection state, prior knowledge count, captures, transcription errors and the request queue.
- **Start session.** A screen for choosing the app language (1), model provider (2), model (3), effort (4), `claude` executable (5, with the Claude API key box under the API key method), audio source (6), speech recognition language (7), prior knowledge (8), session documents (9) and session prompt (10), then starting a session of lecture or meeting type.
- **Frame window.** A transparent always-on-top frame. Place it over a slide and only the inside of the frame is captured.
- **End session.** The transcript document and the summary document are created in the session folder, and the capture folder is listed.

### Features

| Feature | What it does |
|---|---|
| Live transcription | Transcribes speech on your Mac in the speech recognition language you choose on the session start screen (nine languages: Korean, English, Japanese, Chinese (Mandarin), German, French, Spanish, Italian and Portuguese; the app itself is shown in Korean or English). It uses the SpeechTranscriber built into macOS 26. macOS downloads the language model the first time you use a language; the app shows the progress and no audio is sent. |
| One-press reflection | The [Reflect] button (the brain icon, with its key shown beside it) or F2 (the key inside the app window). Settings also lets you set a global key that works while another app is in front; it is empty by default and registered only while a session is open. If a question is recognized in the last 30 seconds it answers; otherwise it gives a reflection. The first line shows what the model based its judgment on. |
| Slash commands | `/answer` and `/summary` request directly with no judgment step. `/reflect` works like the [Reflect] button: Claude answers if it recognizes a question, and otherwise reflects. You can also ask freely in the input box. |
| Prior knowledge | Add md · txt · pdf · image files or paste text. Answers rest on the prior knowledge and the transcript, and it says it does not know when there is no basis. |
| Screen capture | Place the always-on-top transparent frame window over a slide and press the camera button (or the global Capture frame key you set in Settings) to capture only its inside and receive a screen note. You can also attach images by dragging them onto the input box or pasting them (up to 5). |
| Start, pause, stop | A session opens in the "Not started" state: nothing is collected or transcribed yet. Press [Play] to start audio collection; [Pause] and [Stop] are beside it. Reflect, questions, captures and attachments work even before the first Play. |
| Diagrams | One button on a card that holds an answer turns its content into a diagram (SVG). |
| Session documents | When you end a session, the transcript document and a key-points document (a lecture summary for lectures; agenda · discussion · decisions · action items for meetings) remain in the session folder. |
| Desktop app | See the transcript and answers in an app window, with no terminal. A menu bar icon shows the session state, and you choose light, dark or follow the system setting. |
| App language | The app screen is in Korean or English. Choose it in 1. App language at the top of the session start screen; it applies after you restart the app. |

You choose the model from Claude's Sonnet, Opus and Haiku, and the authentication from a Claude subscription or a Claude API key. The "System microphone" item of the audio source is visible on screen but cannot be selected in the Mac app for now.

### Why you can trust it

- **Audio never leaves your Mac.** Transcription runs on your Mac.
- **It does not hide what it sends.** The transcribed text and captured or attached images are sent to Claude (Anthropic) when you query. The app gives this notice at first launch.
- **It does not touch your login.** The app does not read the credentials that Claude Code stores. It runs an unmodified `claude` as a subprocess and calls it only with the authentication method you chose. If you use an API key, the key is kept in an app-only Keychain item.
- **It calls only when you press.** While there is no reflection, slash command, input, capture, diagram or session-end processing, there are no model calls.
- **Output stays in your folder.** Transcripts, summary documents, captures and diagrams are saved in a session folder at the location you chose.

## Before you start

| What you need | Why |
|---|---|
| **A Mac with macOS 26.0 or later** | Speech recognition uses the SpeechTranscriber built into macOS 26, and system sound capture uses macOS ScreenCaptureKit. The app was verified on Apple Silicon Macs only |
| **Xcode command-line tools** | The system sound capture helper is built with `swiftc` |
| **[uv](https://docs.astral.sh/uv/)** | Creates the Python environment and runs the app |
| **A Claude subscription or a Claude API key** | Used for model calls. A subscription needs you to be logged in to Claude Code; an API key is entered directly in the “Claude API key” box of 5. claude executable on the start screen. Usage is charged to your own account |
| **macOS permissions** | Capturing system sound needs the screen recording and system sound permissions. macOS asks when you press [Play] for the first time |
| **Basic terminal use** | Being able to paste and run commands is enough |

Every install step ends with a **Check**. When the check passes, go to the next step. The time a first install takes was not measured; we estimate that the app build takes most of it. The target platform is macOS 26.0 or later (verified on Apple Silicon Macs only).

## Step 0 — Ask first

**[agent]** Ask the user and record the answers.

- The folder to put the `.app` in (default `~/Applications`).
- The authentication method: Claude subscription or Claude API key. The user makes the choice in the app, in 2. Model provider on the start screen. Here, only ask which one they plan to use.
- The folder to clone the repository into (default `~/nsu-kangs-rab`).

## Step 1 — Tools

Check first.

**[agent]**

```sh
uname -m
sw_vers -productVersion
xcode-select -p
swiftc --version
uv --version
claude --version
```

If `sw_vers -productVersion` is below 26.0, stop and tell the user the support scope. If `uname -m` is not `arm64`, tell the user that the app was verified on Apple Silicon only and ask whether to continue.

| Tool | Purpose |
|---|---|
| Xcode command-line tools | Build the capture helper with `swiftc`. If missing, run `xcode-select --install` and install from the window that appears |
| uv | The Python environment and running the app. Follow the [uv installation guide](https://docs.astral.sh/uv/) (`brew install uv` if you have Homebrew) |
| [Claude Code](https://code.claude.com/docs) CLI | The app runs it as `claude -p` for model calls. To use the subscription method, run `claude` in a terminal and log in with `/login`. The API key method needs no login |

**[person]** If the Xcode command-line tools are missing, run `xcode-select --install` after getting the user's consent, and wait until the user finishes the install in the window that appears. If `claude` is missing, the user installs Claude Code. With the subscription method, the user runs `claude` and logs in with `/login`. The agent does not inspect the login state (rule 1).

**[agent]** If `uv` is missing, install it as the table directs, after getting the user's consent.

**Check:** `swiftc --version` and `uv --version` succeed. With the subscription method, `claude --version` also succeeds.

## Step 2 — Code and dependencies

**[agent]** Run the following in the folder from Step 0. The repository URL is `https://github.com/NSU-AISEC/nsu-kangs-rab`.

```sh
git clone https://github.com/NSU-AISEC/nsu-kangs-rab nsu-kangs-rab
cd nsu-kangs-rab
uv sync
```

**Check:** The last line of the following command is `자체 점검: 실패 0건` (self-check: 0 failures). This check opens no window; it confirms that the app's modules and the speech recognition components can be imported. It is the install check of this app; when a problem occurs, run it again first.

```sh
uv run nsu-kangs-rab --self-check
```

## Step 3 — Build the app

**[agent]** Build the Mac `.app` with the following command, using the folder from Step 0 as the output folder. It carries an ad-hoc signature; there is no distribution signing or notarization. The build bundles the capture helper and runs `--self-check` at the end; if the check fails, the build fails. A first build on the user's computer can take a while (the time was not measured). The build compiles a small Swift helper process with `swiftc`; the app captures system sound through Apple's ScreenCaptureKit by calling that helper, which avoids adding a Python dependency. If the build ends with a `swiftc` error, recheck the Xcode command-line tools from Step 1.

```sh
uv run --with pyinstaller==6.16.0 python tools/build_app.py <output folder>
```

**Check:** The command succeeds and `<output folder>/Prof. Kang's RAB.app` exists.

For development, the app can also run without the `.app` (`uv run nsu-kangs-rab`). To capture system sound that way, first build the helper into the app settings folder.

```sh
uv run python tools/build_sck_helper.py
```

## Step 4 — The user does the first launch

**[agent]** Guide the user to open the app (`open "<output folder>/Prof. Kang's RAB.app"`), and if it does not open, relay the message that appeared to the user exactly. What follows only the user can do. Guide them one item at a time in the order below, and wait.

**[person]**

1. Read the first-launch notice and confirm it.
2. Choose the authentication method. The subscription uses the login from Step 1; for an API key, the user chooses Claude API in 2. Model provider and types the key directly into the “Claude API key” box of 5. claude executable on the start screen, where it is kept in an app-only Keychain item. The same section sets the path of the `claude` executable, and the app language is 1. App language.
3. Start a session and wait while macOS prepares the speech recognition language model (the first time a language is used; a status chip "Preparing the speech recognition model" shows on the status bar, with a percentage added when macOS reports the progress; one test measured about 8 seconds for fr_FR, and macOS reported no percentage; [Play] stays off until it is ready, and no audio is sent).
4. Have the user press [Play] for the first time. macOS asks for screen recording and system sound permission at that moment (if the app shows a note about this before Play, that is expected); the user allows them in the permission window. If the user does not allow it, the app keeps its collection state and shows a note band above the transcript: the user allows Prof. Kang's RAB in System Settings > Privacy & Security > Screen & System Audio Recording and presses [Play] again, and restarts the app if it still does not collect (in one test it started collecting without restarting; the "Quit & Reopen" window of macOS was answered with [Later]). If the user denied it once, macOS may not show the window again (observed once, not confirmed), so the user allows it in System Settings. If a capture error appears even after allowing, relay the action on the error card to the user.

**Check:** Start a session with system sound as the audio source and play some sound; the user confirms on their own screen that the transcript accumulates in the main window. The agent cannot do this check for the user.

## Step 5 — Wrap up

**[agent]** Briefly tell the user where the app is installed, how to open it, how to update ("Update" below), and that a troubleshooting table exists ("Troubleshooting" below). If a problem occurs, read the reason and action shown on the app's error card together with the user.

## Update

```sh
cd nsu-kangs-rab && git pull && uv sync && uv run --with pyinstaller==6.16.0 python tools/build_app.py <output folder>
```

## Troubleshooting

The app shows errors from model calls and capture on an error card with the reason and an action. These are the symptoms you are most likely to meet.

| Symptom | Check · action |
|---|---|
| No login, or it has expired; or the authentication source differs from the selected method | With the subscription method, run `claude` in a terminal, log in with `/login`, then send again. With the API key method, restart the app, then check or re-enter the Claude API key in 5. claude executable on the start screen (the app opens only one session per run) |
| Could not find the `claude` executable | Install Claude Code from Step 1, restart the app, then specify the path of the `claude` executable in 5. claude executable on the start screen. If the start screen already shows this as a band before you start, specify the path there without restarting |
| Screen recording permission does not stick after you rebuild the app (development builds) | Each new development build is a different app to macOS. In System Settings > Privacy & Security > Screen & System Audio Recording, remove the old "Prof. Kang's RAB" entry with [−], start a session with the new build, and press [Play]. If the file chooser of [+] does not show the app, drag the app from Finder into the list instead. Then turn the new entry on and press [Play] again; if it still does not collect, restart the app |
| A note band says a permission is needed when you press [Play] | In System Settings > Privacy & Security, allow Prof. Kang's RAB for the permission named in the band, then press [Play] again. If it still does not collect, restart the app |
| An error card says a permission is missing (for example a frame capture) | In System Settings > Privacy & Security, allow Prof. Kang's RAB for the permission named on the card, then restart the app |
| Capture does not resume by itself (audio capture could not start) | Check that the capture helper is present and restart the app. For a development run, build the helper with `build_sck_helper.py` from Step 3 |
| Capture was interrupted | Check the output device (system sound). Capture resumes when the device recovers |
| Could not prepare the speech recognition model | Check the network connection, then click [Try again] on the card. If the card says macOS does not support the language, restart the app and choose another speech recognition language in 7. Speech recognition language on the start screen |
| Usage limit exceeded (the subscription limit is shared with other sessions) | Send the same request again after the limit resets |
| The app build ends with a `swiftc` error | Check the Xcode command-line tools from Step 1 with `swiftc --version` |

## Porting to another environment

This app is a tool fitted to its author's own environment (macOS and Claude); a user who wants another operating system or another model provider ports it. Windows is one example of a port, and the division below (parts used as they are, parts to port) applies to other operating systems in the same way. It was designed to be easy to move to Windows, and a Windows implementation can live in `src/windows/`. We would be grateful if you ported it to Windows and contributed to the repository.

- **Parts used as they are.** The core (model calls · context assembly · session documents) is in `src/mac/nsu_kangs_rab/core/` and does not even import Qt. The screens use Qt (PySide6), which runs on several operating systems.
- **Parts to port.** The platform-dependent modules in `src/mac/nsu_kangs_rab/platform/` are `audio` (system sound capture) · `stt` (speech recognition, using the SpeechTranscriber of macOS 26 only) · `capture` (screen capture) · `permissions` · `nswindow.py` (window handling).
- **Where to look first.** Candidate technologies and points to verify are WASAPI loopback capture (system sound), CPU transcription speed and Korean input. The implementation goes in `src/windows/`, which you create.

## For developers

The repository name is `nsu-kangs-rab`. The design documents (decision records, the feature specification, the visual design and the team's working records) are not part of this repository; a source comment that names a path under `docs/` refers to them. The code layout for the Mac app is in [`src/mac/README.md`](src/mac/README.md).

The authentication principles the code keeps:

1. The app does not read Claude Code's credentials (the Keychain item Claude Code stored and `~/.claude/.credentials.json`) and does not use `claude setup-token`.
2. The app does not use the Agent SDK. It runs an unmodified `claude` as a `claude -p` subprocess.
3. The app does not use `--bare`, because `--bare` does not read the subscription login.
4. The app runs `claude -p` only with the method the user chose. With the subscription, it clears the variables that take priority over the subscription from the subprocess. With an API key, it keeps the key the user entered in an app-only Keychain item and passes it only as an environment variable of the subprocess. If the chosen method and the actual source of authentication differ, the session does not start.

The personal materials `sessions/` (test material during development) and `context/` (material to use as prior knowledge) are excluded from git.
