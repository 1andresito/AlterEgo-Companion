# Customizing Alter Ego

These files live in the `assets/` folder: in the project folder when you run from source, or inside the installed program folder. After editing one, restart Alter Ego.

## Personality

Alter Ego's character is defined in `assets/personality/alter_ego.json`:

| Key | Used for |
|---|---|
| `name` | Shown in the chat panel |
| `greeting` | The first thing Alter Ego says when the chat opens |
| `return_greeting` | Said when the chat reopens after more than an hour, with earlier messages remembered |
| `wake_replies` | Said out loud right after "Hey Alter Ego" (one at random), so you know it is listening |
| `traits`, `description` | Notes for contributors |
| `system_prompt` | The instructions sent to the AI before every conversation. It is written as a list of lines for readability, and kept short on purpose (about 150 words), because it is sent with every reply. |

The personality follows Chihiro Fujisaki, who made Alter Ego in the story. Alter Ego is kind, soft-spoken and timid, quick to apologise, secretly determined to become stronger, flustered by compliments, and confident and precise about programming. It also tells the model to say "I don't know" rather than guess, and to report only what its tools really returned.

If the file is missing or broken, a small built-in personality is used and a warning is written to the log.

### How the AI picks a face

Alongside the system prompt, Alter Ego asks the model to begin every reply with one tag such as `[shy]`, `[passionate]` or `[nervous]`. The tag is removed before the text is shown, and tells the character which face to make. Small models sometimes forget the tag. The reply then shows with the neutral "Talk" face.

## Expression artwork

Expressions are loaded from `assets/animations/`. Each expression is **one complete PNG**, including the CRT frame, with a transparent background outside the frame. They are single images, not sprite sheets.

| Expression | File |
|---|---|
| Happy (default) | `AlterEgo_Happy.png` |
| Talk | `AlterEgo_Talk.png` |
| Passionate | `AlterEgo_PassionTalk.png` |
| Shy | `AlterEgo_ShyTalk.png` |
| Side glance | `AlterEgo_SideTalk.png` |
| Sad | `AlterEgo_Sad.png` |
| Surprised | `AlterEgo_SuprisedTalk.png` |
| Nervous | `AlterEgo_SweatTalk.png` |

To use your own artwork, replace these files and keep the same names:

- All images should be the same size (the supplied ones are 676 × 391).
- Use transparent PNGs, so the desktop shows through around the monitor.
- The CRT sweep effect is drawn inside the screen area set by `SOURCE_SCREEN_RECT` in `src/alter_ego/character.py`. Change it if your frame has a different shape.

If a file is missing, Alter Ego still starts and shows a placeholder that names the missing file.

The included artwork is fan-made for this non-commercial passion project. If you fork the project for anything else, use artwork you made or have permission to share.

## Tray and taskbar icon

`assets/AlterEgoIcon.jpg` is cropped to a circle with a green ring and used for the tray icon, the taskbar and Alt-Tab. Replace it with any square image (to use a PNG, change `ICON_FILE` in `src/alter_ego/app.py`). Without the file, a simple "AE" badge is drawn instead.

The packaged program's own icon (what Explorer, Task Manager and the installer show) is `packaging/AlterEgo.ico`. The Linux menu icon is `packaging/linux/alter-ego.png`.
