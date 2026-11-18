# Changelog

What changed in each version, newest first. The release page on GitHub shows the section for that version.

## v0.9.2: Real news, a stop button, and thinking you can see

- **Alter Ego shows when it's thinking.** While it gets a reply ready, the chat shows `ALTER EGO > thinking...` with moving dots, so a pause no longer looks like the app froze. If it stops mid-reply to look something up, the dots come back after its words, with what it's doing: `(searching the web...)`.
- **Real news and weather.** Asking for the news used to find newspapers named "News Today" on Wikipedia, and the weather found the city's Wikipedia page, so Alter Ego made things up or said "I don't know". News now comes from Wikipedia's daily *Current events* pages (also "news about ..."), and weather from wttr.in, now and for the next days. Other answers come with the opening paragraph of the best pages instead of a one-line snippet, so "who won the 2026 World Cup?" has the answer in it.
- **Fix:** small models were handed search results and still said "I can't go online". The results now say plainly that they are live and should be answered from. A search whose words were wrapped one level too deep is understood too.
- **The chat opens at the newest message**, not at the top of a long remembered conversation.
- **A stop button.** While Alter Ego thinks, types or speaks, the **send** button becomes **stop**. It ends the reply at once (the words so far are kept) so you can talk again. You can type your next message meanwhile; **Enter** sends it once Alter Ego is done or stopped.
- **Thinking that shows what's happening.** Alter Ego's face and words follow what it's doing, not a clock: a side glance and "thinking..." to start, an eager face and "searching the web..." during a search, a focused one while reading, an "oh!" and "looking at what I found..." when results come back. If nothing new happens for a while it goes deeper: "thinking some more..." with a shy, pondering face, then "thinking really hard..." looking a little nervous.
- **The chat box shows everything you type.** It wraps long messages and grows up to five lines, then scrolls. **Enter** sends, **Shift+Enter** starts a new line.
- **Danganronpa only when you ask.** Alter Ego still talks like Alter Ego, but it no longer brings up the game, Master's past or the killing game on its own. Everyday words such as "strong", "school", "hope" or saying "Alter Ego" no longer pull the story in. Ask about Danganronpa, a character or a case and it remembers as before ([how](docs/CUSTOMIZING.md#what-alter-ego-knows-about-danganronpa)).
- **Internet first, when it's on.** With **AI** → **Allow internet** on, Alter Ego knows it can go online and today's date. It searches before answering news, weather and questions about the world ("who won...", "what is...", "how tall is..."), instead of saying "I don't know". Small talk and questions about its own story still don't go online. With the internet off, it says so kindly instead of guessing.
- **Fix:** some replies, such as one to "Can you tell me today's news?", showed tool code like `{"type":"function","function":...}` instead of words. That form of tool call is now recognised too: Alter Ego runs the web search and answers in words, and the code is never shown.
- **Fix:** a reply could start with a stray `}` or `"` left over from such tool code, and the voice then failed with "Nothing to synthesize". Those leftovers are removed now, and text with nothing to say aloud is simply not spoken.

## v0.9.1: Uninstall asks what to keep

- **Uninstalling asks what else should go.** A window lists your memories and settings, the voice files and GPU pack, the speech-recognition models, the files Alter Ego saved for you, Ollama's AI models and Ollama itself, each with its size, plus **Everything above**. Nothing is ticked, so a plain uninstall keeps your memories for a later reinstall. On Linux, `./uninstall.sh` asks the same questions in the terminal.
- **Fix:** a release-build test of the GPU pack check failed on machines whose Windows user folder has a short name (such as `RUNNER~1`). The check now compares real folder paths.
- **Fix:** Alter Ego could crash some time after a second copy was started and asked it to come forward. The connection from the second copy is now cleaned up right away.

## v0.9.0: Lighter, steadier, and your GPU for the voice

- **Much less memory.** Alter Ego's voice now runs in a separate helper process. Alter Ego itself uses about 200–300 MB instead of 2–4 GB. On computers with less than 16 GB of memory, the voice is closed after 10 quiet minutes and its memory goes back to your computer; it loads again when it next speaks. On bigger computers it stays loaded so replies stay quick, and it is restarted if it ever grows past 3.5 GB.
- **Use your NVIDIA graphics card for the voice.** On Windows, **Spoken replies** → **Use my NVIDIA GPU for my voice** (or the setup window) downloads the GPU pack once (about 2.8 GB). The voice then speaks about 3 times faster. It's never downloaded without asking, and **Stop using the GPU pack** removes it. **Spoken replies** shows where the voice runs.
- **Only one Alter Ego.** Starting it again while it's running brings the running one forward instead of opening a second copy.
- **A loading window.** At start-up a small window shows Alter Ego waking up (its AI model and its voice), and the character appears when it's ready.
- **Fix:** the chat jumped back down while you scrolled up during a reply. It now stays where you put it, and follows new text only when you're at the bottom.

## v0.8.1: Quicker to answer, and Alter Ego knows its story

- **Faster first reply.** Alter Ego's voice now loads first thing at start-up and warms up before you talk, instead of during your first message. The chat shows "Waking up... loading my voice" meanwhile. The first words of a long reply are spoken sooner too.
- **Alter Ego knows Danganronpa.** It remembers Trigger Happy Havoc as the in-game Alter Ego would: Master (Chihiro), the other students, the cases and its own story. It talks about them when you ask, gently, and doesn't bring up spoilers on its own. The facts are in `assets/personality/knowledge.json`, which you can edit ([how](docs/CUSTOMIZING.md#what-alter-ego-knows-about-danganronpa)).
- **Fix:** replies sometimes showed tool code such as `{"name":"read_file","parameters":{...}}`. That is never shown now, and old replies with it no longer make the AI repeat it.
- **Fix:** the AI looked things up in files and on the web when you only wanted to chat, then said "I don't know". It now uses files only when you talk about files, and the web when you ask for something online (news, weather, a search).
- **Fix:** stage directions in brackets ("[pauses]") and a stray "assistant" at the start of a reply are no longer shown.
- Ollama gets more room for the conversation (8K tokens instead of 4K), so the start of a long chat isn't cut off.

## v0.8.0: Files anywhere, with your OK

- **Fix:** the "Is this okay?" question about files could open behind Alter Ego and the chat, where it couldn't be clicked. It now always comes up on top, in the middle of the screen.
- Alter Ego can work with files anywhere, not only in `Documents\Alter Ego`. It asks before every single change and shows the full path, and whether a file is new or will be replaced (**Show Details...** shows the new text). A bare file name still goes in `Documents\Alter Ego`. "Put it in my Downloads" (or Desktop, Documents, Pictures, Music, Videos) means your own folder, and the AI is told it may write there instead of refusing.
- Reading files outside `Documents\Alter Ego` asks first, once per folder.
- New: **AI** → **Edit files without asking (risky)**. It's off by default, and switching it on shows a warning first. Even when it's on, Alter Ego still asks before touching system folders or its own folders.

## v0.7.2: The character voice works in the downloads

- **Fix:** the downloaded app couldn't speak in Alter Ego's voice ("the voice-conversion package is missing"). Two parts of the voice converter were left out of the build; they are in now, and every release build checks that the voice loads before it is published.
- If part of the voice converter is ever missing in a download again, Alter Ego now says to update or reinstall, instead of giving `pip` instructions meant for running from source.
- On Linux, the app started from the applications menu now writes `alter_ego.log` in its data folder, like on Windows, so problems can be looked into.

## v0.7.1: Updates and a TV switch-on

- **Updates.** When a new version is out, Alter Ego asks at start-up and, if you say yes, downloads it, installs it and starts again by itself. Your settings and memories stay. Turn the check off, or check by hand, from the **AI** menu.
- **Like an old TV.** Alter Ego switches on like a CRT when it starts (a dot, a line, then the picture) and switches off the same way when you quit.
- **Fix:** downloads (the voice, Ollama, the voice model's helpers) no longer fail with `CERTIFICATE_VERIFY_FAILED` in the packaged app or on Windows: every download and API call now checks certificates with the computer's own certificate store.

## v0.7.0: Easy to install

- **Download and run.** Alter Ego now comes ready-made on the [Releases page](https://github.com/1andresito/AlterEgo-Companion/releases): a Windows installer, a portable Windows zip and a Linux download. You don't need Python, Git or a terminal.
- **First-run setup.** On first start, Alter Ego asks for what it needs: it can install Ollama (the free, local AI) for you, lets you pick an AI model to download (or none), and offers to download its voice. Nothing is downloaded unless you tick it. You can open the setup again from **AI** → **Set up Ollama and my voice...**.
- The character voice is part of the download: no extra install steps.
- The AI model is no longer downloaded silently on the first reply. The setup asks first.
- The packaged app writes its diagnostics to `alter_ego.log` in its data folder, because it has no terminal window.
- The README is rewritten for newcomers. Detailed reference moved to [`docs/`](docs/), and the [`AI/`](AI/) folder is now a guide for contributors.

## v0.6.0: Alter Ego talks back

- Spoken replies with a local, offline voice (Kokoro), sentence by sentence while the reply is still arriving, with the chat text typing along to the voice.
- One fixed voice, the character's own: Kokoro speech converted with an RVC voice model trained for this project. It runs on an NVIDIA graphics card when there is one, and on the CPU otherwise.
- The delivery follows the mood: shy replies are softer and slower, passionate ones quicker.
- Hands-free: after "Hey Alter Ego" it answers "Yes?" out loud. Optionally you can interrupt a hands-free reply just by talking.
- Internet and files: Alter Ego can search the web, read pages, and make and read files in one folder (it asks before the first change).
- Ollama looks after itself: it is started when needed and switched off when Alter Ego quits.
- Faster replies: about 0.1 s to the first word with a local model that is already loaded.

## v0.5.0: Voice input

- Push to talk: hold F9 anywhere (or the talk button) and speak.
- Hands-free: say "Hey Alter Ego".
- Speech is recognised on your computer with Whisper, or with an API if you choose one.

## v0.4.0: Memory

- Conversations are saved locally and restored after a restart, with day dividers and a "welcome back" after a long pause.
- **Memory** menu: switch saving off, or forget everything.

## v0.3.1: More AI choices

- Claude through your existing Claude Code login (no API key).
- Any OpenAI-compatible API (ChatGPT, Groq, LM Studio, ...).

## v0.3.0: AI chat

- Provider framework with Ollama, streaming replies, and the face following the mood the AI picks.

## v0.2.0: Chat panel

- Chat panel, character reactions, personality file.

## v0.1.x: The companion

- CRT desktop companion, draggable window, system tray, expressions with crossfades, CRT sweep, size presets.
