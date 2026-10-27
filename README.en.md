<p align="center"><img src="docs/assets/readme/en/about.png" width="320" alt="Prof. Kang's RAB about image"></p>

<h1 align="center">Prof. Kang's RAB</h1>

<p align="center"><a href="README.md">한국어</a> | English</p>

<p align="center"><strong>Retrieval-Augmented Brain</strong></p>

<p align="center">A Mac app that keeps you from missing what is said in class and meetings, and combines what you know with AI answers so you can respond right away.</p>

It started from the meeting method that AI expert Prof. Jangmook Kang introduced in his lecture of September 19, 2026. During a meeting or class, it gathers live transcription, prior knowledge and the screen to augment the user's brain and knowledge. Words you missed in class can be read back from the live transcript, and when a question comes to you in a meeting, one press of [Reflect] gives an answer based on the material you prepared. It is not an app that speaks for you; it is an aid that you read and judge. It runs on a Mac with macOS 26.0 or later and has been verified on Apple Silicon Macs only.

<p align="center"><img src="docs/assets/readme/en/screens/main-window.png" width="800" alt="Main window while a response is being written: transcript on the left, answer card on the right"></p>

<p align="center">Mockups of every screen: <a href="https://claude.ai/artifact/SeosX2oTCiqQ6ctYebBzAW">https://claude.ai/artifact/SeosX2oTCiqQ6ctYebBzAW</a></p>

## What this project provides

The core value of this project lies in presenting a method, and the form of its process, for widening the channel through which information flows from the outside world to the brain and for extending context beyond the brain.

The author built this app as a tool fitted to the author's own environment (macOS and Claude), so its generality is limited. Other people are encouraged to port it to their own environment (operating system and model provider). [AGENT_INSTALL.md](AGENT_INSTALL.md#porting-to-another-environment) describes the parts to port, using Windows as the example.

## Quick start

You can leave the installation to an AI coding agent. On a Mac with [Claude Code](https://code.claude.com/docs), say:

> Install Prof. Kang's RAB on this Mac. Follow AGENT_INSTALL.md in `https://github.com/NSU-AISEC/nsu-kangs-rab`, and stop and ask me at any step that needs my account, keys or permissions.

The agent follows [AGENT_INSTALL.md](AGENT_INSTALL.md), checks the tools and builds the app. It stops at the steps only you can do: signing in to Claude Code (`/login`), entering the key in the app if you use the API key method, waiting while macOS prepares the speech recognition language model the first time you use a language, and granting macOS permissions (screen recording, system sound). The agent does not handle Claude Code's credentials or your API key. Questions about installing, using, troubleshooting and porting are answered by the agent from the same document. To install by hand, follow its procedure. The app calls the model through the Claude Code CLI (`claude -p`), so the subscription method needs Claude Code and its login, and the API key method needs the key you enter in the app.

## Credits and license

This project is released under the MIT License. The license text is in `LICENSE` at the repository root.

Material from other projects is kept in `third_party/`, each with its own license file:

- `third_party/diagram-design/`: a specific version of diagram-design (MIT license, <https://github.com/cathrynlavery/diagram-design>), used by the diagram feature. The folder has its `LICENSE` and `THIRD_PARTY_LICENSES.md`.
- `third_party/awesome-design-md/`: a copy of one design document from awesome-design-md (MIT license, <https://github.com/voltagent/awesome-design-md>), with its `LICENSE`.

The screens use PySide6 (Qt for Python) as a library. PySide6 is licensed under the LGPL v3 (<https://doc.qt.io/qtforpython-6/licenses.html>). The app installs it as a dependency with `uv sync` and does not modify it.
