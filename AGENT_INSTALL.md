# Installing with an AI coding agent

This document is the procedure that an AI coding agent (Claude Code or another) follows when a user asks it to install Prof. Kang's RAB on this Mac. The source of the install commands is the "Install" section of [`README.md`](README.md#install). This document does not repeat the commands; it fixes the order in which to run them, what to check, and where to hand over to the user.

The user starts the agent with the sentence in the "Quick start" section of [`README.md`](README.md#quick-start).

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
- **On Windows, the task is porting, not installing.** There is no install procedure; a user who wants to contribute to the repository follows the guidance in [`README.md`](README.md#for-windows-users).
- **Another agent may install it.** This procedure does not depend on the kind of agent. But the app calls the model through the Claude Code CLI (`claude -p`), so to use the subscription method, Claude Code must be installed and logged in.

## Step 0 — Ask first

**[agent]** Ask the user and record the answers.

- The folder to put the `.app` in (default `~/Applications`).
- The authentication method: Claude subscription or Claude API key. The user makes the choice in the app, in 2. Model provider on the start screen. Here, only ask which one they plan to use.
- The folder to clone the repository into (default `~/nsu-kangs-rab`).

## Step 1 — Tools

Follow step 1 of the README "Install" section. Check first.

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

**[person]** If the Xcode command-line tools are missing, run `xcode-select --install` after getting the user's consent, and wait until the user finishes the install in the window that appears. If `claude` is missing, the user installs Claude Code. With the subscription method, the user runs `claude` and logs in with `/login`. The agent does not inspect the login state (rule 1).

**[agent]** If `uv` is missing, install it as the README directs, after getting the user's consent.

**Check:** Same as the check of README step 1 (`swiftc --version` and `uv --version` succeed, and `claude --version` too with the subscription method).

## Step 2 — Code and dependencies

**[agent]** Run the commands of README "Install" step 2 in the folder from step 0. The repository URL is `https://github.com/NSU-AISEC/nsu-kangs-rab`.

**Check:** Same as the check of README step 2. The last line of `uv run nsu-kangs-rab --self-check` must be `자체 점검: 실패 0건` (self-check: 0 failures). This check is the install check of this app; when a problem occurs, run it again first.

## Step 3 — Build the app

**[agent]** Run the `.app` build command of README "Install" step 3, using the folder from step 0 as the output folder. A first build on the user's computer can take a while. The build compiles a small Swift helper process with `swiftc`; the app captures system sound through Apple's ScreenCaptureKit by calling that helper, which avoids adding a Python dependency. If the build ends with a `swiftc` error, recheck the Xcode command-line tools from step 1.

**Check:** Same as the check of README step 3. `Prof. Kang's RAB.app` exists in the output folder.

## Step 4 — The user does the first launch

**[agent]** Guide the user to open the app (`open "<output folder>/Prof. Kang's RAB.app"`), and if it does not open, relay the message that appeared to the user exactly. What follows only the user can do. Guide them one item at a time in the order of README "Install" step 4, and wait.

**[person]**

1. Read the first-launch notice and confirm it.
2. Choose the authentication method, and for an API key, type the key directly into the “Claude API key” box of 5. claude executable on the start screen.
3. Start a session and wait while macOS prepares the speech recognition language model (the first time a language is used; a status chip shows that it is preparing, with a percentage when macOS reports the progress, and [Play] stays off until it is ready).
4. Have the user press [Play] for the first time. macOS asks for screen recording and system sound permission at that moment (if the app shows a note about this before Play, that is expected); the user allows them in the permission window. If the user does not allow it, the app keeps its collection state and shows a note band above the transcript: the user allows Prof. Kang's RAB in System Settings > Privacy & Security > Screen & System Audio Recording and presses [Play] again, and restarts the app if it still does not collect. If a capture error appears even after allowing, relay the action on the error card to the user.

**Check:** Same as the check of README step 4. The user confirms on their own screen that the transcript accumulates. The agent cannot do this check for the user.

## Step 5 — Wrap up

**[agent]** Briefly tell the user where the app is installed, how to open it, how to update ([`README.md`](README.md#update)), and that a troubleshooting table exists ([`README.md`](README.md#troubleshooting)). If a problem occurs, read the reason and action shown on the app's error card together with the user.

## See Also

- [`README.md`](README.md): the source of the install commands (Install), Before you start, Update, Troubleshooting, the Windows porting guidance
