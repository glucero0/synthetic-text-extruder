# Synthetic Text Extruder

A single-window studio for general-purpose AI creation: **text**, **images**, **video**, and **music** — with built-in editors, an archive of everything you make, and Settings that save when you leave a Settings page.

> **Work in progress.** This project is under active development. Features, APIs, config, and storage formats may change without notice. **Use at your own risk** — there is no warranty of any kind. You are responsible for API costs and any data you generate or store. Do not rely on it for production, critical, or irreversible work.

**Backend: Google Gemini** — text, image, Veo video, and Lyria music via separate model pickers in Settings.

## Features

- Single-window app: pick a screen from the top dropdown. A hamburger menu holds occasional actions for the current screen; each screen keeps its contents when you switch
- **Creation Studio** — one freeform prompt box; the app infers text/image/video/music from your prompt and generation intent. Attach mixed **Sources** (image, video, text, PDF, audio) in Studio — it is the hub, so you do not have to load an image in the editor first. A **folder** (or more files than the 12-source tray) becomes one **Collection** chip you can prompt as a batch: OCR every scan, apply Image Editor-style filters, skip ads and rebuild a magazine as a selectable-text PDF, make a flipbook/slideshow, or build a contact sheet. Two or more tray sources (or a document/PDF/audio-only tray) **CREATE** a cited illustrated report: headings and prose in the Viewer, with source pictures (and video stills) kept on the page so **Export PDF** includes them. Prompt **summarize** for that document even when every source is a video — Viewer type is Report, not a new MP4. To OCR one picture among several, quote its title or filename (`extract the text from the image "a toaster on fire"`) or select that Sources row. One screenshot or clip still works as a visual basis: prompt **extract the text** (OCR), **transcribe** (speech from a clip), or **extract the layout** (UI chrome + coordinate JSON; then ask Studio to recreate it as HTML/CSS or an app). Turn on **Enable Tools** in Studio (or set the Settings default) to switch to **Search** (optional) + **Tool Use** for file, PowerShell, Gmail, Drive, Docs, Calendar, Tasks, and web-browse automation.
- **Gemini Use Tools** (optional) — attach built-in tools (`read_json`, `write_json`, `read_text`, `write_text`, `execute_powershell`, `search_gmail`, `search_drive`, `create_drive_file`, `read_google_doc`, `create_google_doc`, `edit_google_doc`, `list_calendar_events`, `create_calendar_event`, `edit_calendar_event`, `list_tasks`, `create_task`, `edit_task`, `browse_web`) and describe steps in natural language; Gemini calls them via function calling (text generations only, Windows for PowerShell)
- **Google Search enrichment** (optional, Gemini text) — when Search runs, the app can OCR images and pull YouTube captions from cited results before the tool or document pass
- **Gemini** text, image, video, and music generation with separate model pickers per modality. Music uses **Lyria** (Clip for 30-second previews, **Lyria 3.5 / Lyria Pro** for full songs). Tracks are SynthID-watermarked by Google. Use an image as a Studio basis to compose from a picture; an existing MP3 cannot be sent as audio input.
- **Archives** — every creation is saved automatically: text/lyrics/metadata in `archives.json`, binaries in the media folder; search, import/export JSON, or import existing text/image/video/audio files. PDFs imported as Studio sources are stored in the media folder too.
- **Viewer** — a generic shell for **text, images, video, audio, or PDF**. **Open…** a file (or pick an Archive item / generate in Studio) and tabs plus tools switch to that type: **Document** (plus **Sources** when Google Search was used) vs Image/Video/Audio. After Studio extracts text or a transcript, the **Extracted** tab shows it. After a magazine reconstruct, skipped ads are listed on the Document tab. After a flipbook job, the **Flipbook** tab turns pages. After Studio extracts a layout from a screenshot or video frame, the **Layout** tab shows UI chrome and coordinate JSON. **Save Layout PDF** is the paged document (boxed screenshot, then flags and JSON as black text). **Save Layout PNG** is one tall image of that same content — Windows Photos shrinks it to fit the window (it looks like a ribbon); Paint, a browser, or zoom shows it correctly. The Image tab still saves the original picture. **Save PNG / MP4 / MP3 / PDF** looks at the file itself (Gemini Embedding 2 on the image, clip, song, or document text), then prefills a short filename you can edit. Already-saved work does not need to be exported. A Studio **report** (including **summarize** on attached videos) is a formatted document with stills and captions — Viewer type is Report, and **Export PDF / PNG / TXT** write that layout, not Save MP4.
- **Image Edit** and **Video Edit** — standalone editors (and reachable via Viewer → Edit) for crop/rotate, color/filter adjustments, and (for video) a segment timeline for splitting/reordering/trimming clips
- **Settings** — left-hand list: Models, Generation, Google, Storage, Appearance. Paste a Gemini API key on **Models** or **Google** and click **Save API key** (writes `config.yaml`). Other changes save when you switch Settings pages or leave Settings. Open-source UI fonts and size; no CRT overlay or display scaling.
- Cancel a generation in progress
- "Use as Basis" / "Load…" / "Save and Send to Creator" — add the Viewer's active item, an imported file, or the image/video editor output to Studio **Sources** without replacing what is already there (tray cap 12, or one Collection for a folder). Studio is the hub: you do not have to open the image editor first. For songs this also reloads prompt and lyrics for a new Lyria clip (Lyria cannot take an MP3 as input) while attaching the track for reports/transcripts. For a screenshot or clip, prompt **extract the text**, **transcribe**, or **extract the layout** in Studio. After a layout extract, Studio keeps the image plus coordinate JSON so you can recreate the UI as text/code (or ask for an image/video instead).

## Requirements

- Python 3.10+
- A [Gemini API key](https://aistudio.google.com/apikey), set via **Settings** (saved to `config.yaml`)
- **ffmpeg + ffprobe** — needed for **Video Editor** (apply filters, split/reorder segments, export), to transcribe a video basis in Studio (pulls the audio track), and to extract layout from a video basis (grabs a still frame). See [Installing ffmpeg](#installing-ffmpeg) below.

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

python -m synthetic_text_extruder
```

Then open **Settings** → **Models** (or **Google**) → paste your Gemini API key → **Save API key**. Pick a **Text**, **Image**, **Video**, and/or **Audio (Lyria)** model. Other settings save when you switch Settings pages or leave Settings via the screen dropdown. Enable Lyria (and Lyria Pro / 3.5 if you want full-length songs) for that API key in [Google AI Studio](https://aistudio.google.com/) or the linked Cloud project if the Audio picker is empty after **Refresh…**.

## Installing ffmpeg

Video Editor shells out to system `ffmpeg` and `ffprobe`. They are **not** bundled with this app — install them yourself and put them on your `PATH` (or, on Windows, in a common install folder the app already checks).

Official builds and docs: [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)

### Windows

Pick one:

```bash
winget install ffmpeg
```

```bash
choco install ffmpeg
```

```bash
scoop install ffmpeg
```

Or download a build from [ffmpeg.org](https://ffmpeg.org/download.html) / [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) and add the `bin` folder (containing `ffmpeg.exe` and `ffprobe.exe`) to your user or system **PATH**. Then open a **new** terminal and confirm:

```bash
ffmpeg -version
ffprobe -version
```

### macOS

With [Homebrew](https://brew.sh/):

```bash
brew install ffmpeg
ffmpeg -version
ffprobe -version
```

### Linux

Use your distro package manager (names vary slightly):

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

Then confirm:

```bash
ffmpeg -version
ffprobe -version
```

Use a reasonably current build (roughly ffmpeg 4+). Very old copies on `PATH` (for example ancient helper scripts) can break Video Editor — remove or reorder `PATH` so the modern `ffmpeg` wins.
## The apps

| Screen | What it does |
| --- | --- |
| **Creation Studio** | Type a prompt and hit **Create**. With **Enable Tools** off, one prompt box handles text/image/video/music. With **Enable Tools** on (Studio checkbox; Settings → Use Tools is the default after launch), Studio shows **Search** (optional), a **Tools** panel, and **Tool Use** instead — text only. **Menu** → Load Files / Folder / Folder Recursively (or Load Text / Image / Video / PDF), or use the Viewer's active item as a source. Attachments appear in a **Sources** pane you can drag-resize; a large folder becomes one **Collection** chip (batch OCR, filters, magazine PDF, flipbook, contact sheet, or any per-file instruction). The last image or video still previews for extract / image-to-video. The pane width is remembered in `config.yaml`. Two or more tray sources: CREATE gathers a brief from each (transcript, image description, PDF/text extract) and writes a cited illustrated report — source pictures stay in the Viewer; **summarize** is that document (**Export PDF / PNG**), not a new video. One screenshot or clip: prompt **extract the text**, **transcribe**, or **extract the layout**; after a layout extract, ask Studio to rebuild the UI as HTML/CSS or an app. |
| **Archives** | The library of everything you've generated or imported (catalog in `archives.json`; PNG/MP4/MP3 files in the media folder). Search and sort stay on the page. The menu has import/export JSON and import text/image/video/audio. |
| **Viewer** | Generic viewer for text, images, video, audio, or PDF. **Menu → Open…** starts empty; opening a file or Archive item switches tabs/tools to that type. Switching away keeps the current item. Text uses **Document** (and **Sources** when Google Search was used) vs Image/Video/Audio. The menu has Use as Basis / Voice Reader, and Edit Image / Edit Video. OCR, transcription, and layout extract run from Creation Studio (prompt **extract the text**, **transcribe**, or **extract the layout** with the media as a source). A mixed-source report (including **summarize** on videos) is a **Report** document with stills and captions; **Export PDF / PNG / TXT** write that layout — not Save MP4. On the Layout tab, **Save Layout PDF** writes an A4 file (boxed screenshot, then flags and JSON as selectable black text). **Save Layout PNG** is one tall image of the same content. **Save PNG / MP4 / MP3** (and editor **Save As…**) looks at the actual image, video, song, or document — not the prompt — and prefills an embedding-ranked filename you can edit. If Gemini is unavailable it falls back to a short prompt slug. |
| **Image Editor** | Crop, rotate, and adjust (brightness/contrast/saturation/hue/sepia/blur/exposure/gamma/vignette/tint, grayscale, threshold, sharpen, background removal). The menu has Load / Save / Save As / Send to Creator. Opened standalone or via Viewer → **Edit Image**. |
| **Video Editor** | Same filter/crop/rotate toolset plus a **segment timeline**: split at the playhead, delete/reorder segments, then re-render. Requires ffmpeg. The menu has Load / Save / Save As / Send to Creator. Opened standalone or via Viewer → **Edit Video**. |
| **Settings** | Left-hand list: **Models** (Gemini API key + Text / Image / Video / Audio pickers), **Generation** (search, two-pass, Use Tools, OCR, YouTube captions, temperature, extra instructions), **Google** (same API key field, plus Workspace OAuth), **Storage** (media folder), **Appearance** (light / dark, open-source UI font and size, sound). **Save API key** writes `gemini.api_key` to `config.yaml` immediately. Other changes write when you switch Settings pages or leave Settings, then update Studio’s **Enable Tools** default (search field visibility and model labels also update). |

### Prompt Editor and Saved prompt

Use **Prompt Editor** to keep reusable snippets (a house style, a tool-use recipe, a search query, and so on). **Add** a prompt, give it a **Name**, write the **Prompt** body, then **Save**. **Delete** removes the selected snippet.

In **Creation Studio**, open the **Saved prompt** dropdown and pick a name. The body is inserted at the current cursor in the Prompt field — or in **Search** / **Tool Use** when **Enable Tools** is on, depending on which field last had the cursor.

### Send to Creator vs Use as Basis

- **Use as Basis** (Viewer) — add the Archive item to Studio **Sources** without copying it. The original stays in Archives. You can add several items (image, video, text, PDF, audio; tray cap 12, or one Collection for a whole folder). Two or more tray sources: CREATE writes a cited illustrated report (pictures stay on the document). For a single image or video, prompt **extract the text**, **transcribe**, or **extract the layout** in Studio. After a layout extract, Studio keeps the screenshot **and** the layout JSON so you can recreate the UI as HTML/CSS or an app (say “create an image…” if you want another mockup instead). For songs this attaches the track for reports/transcripts and reloads the prompt and lyrics as text for a new Lyria clip — Lyria still cannot take the MP3 as input.
- **Open…** (Viewer menu) — pick a text, image, video, song, or PDF file from disk. It is saved to Archives and the Viewer switches tabs/tools to that type. To OCR, transcribe, extract UI layout, or fold it into a report, add the file to Studio Sources. On the **Layout** tab, **Save Layout PDF** is a multi-page A4 document (screenshot, then flags and JSON as text); **Save Layout PNG** is one tall image of that same dump (Windows Photos fits the whole strip in the window; zoom or Paint to read it). Switch to Image to save the original picture. Switching away from Viewer keeps the current item; the file stays in Archives.
- **Save and Send to Creator** (Viewer, Image Editor, Video Editor) — for images and videos only. Saves the current editor/viewer state, then **adds** that media to Studio Sources (it does not replace other attachments). The next **CREATE** is stored as a **new** Archive item rather than overwriting the source.

### Studio Sources

Creation Studio is the hub. Attach an image, video, text file, PDF, or song in the **Sources** pane (Menu → **Load Files…** / **Load Folder…** / **Load Folder Recursively…**, or Viewer **Use as Basis**) instead of routing everything through the image editor. The tray holds up to 12 attachments. Larger folders (or more files than remaining tray slots) import as one **Collection** chip (up to 100 files).

- **Collection** (one chip for many files): prompt the folder. Examples: **OCR every scan**, **apply sepia and sharpen to every image**, **skip ads and reconstruct a magazine PDF**, **make a flipbook**, **contact sheet**, **put them all in one PDF**, or any per-file instruction (describe each photo, translate the text, …). Magazine PDFs are a **readable reconstructed article** (selectable text plus cropped photos), not a facsimile of the original layout. Ad skipping is model judgment — review the skipped-ads list. Files larger than the inline Gemini cap are uploaded through the Gemini Files API.
- **Two or more tray sources**, or a text/PDF/audio-only tray: CREATE gathers a brief from each file (transcript, image description, PDF/text extract) and writes one cited illustrated report. Prompt **summarize** (or **create a report**) for that document. Source pictures (and a still from each video) are copied onto the new Archive item so they stay in the Viewer after you clear Sources. Viewer treats the result as a **Report** document — **Export PDF / PNG / TXT**, not Save MP4.
- **Extract the text**, **transcribe**, or **extract the layout**: name the image or clip in quotes (`extract the text from the image "a toaster on fire"`), or select that Sources row. Other attachments stay in the tray; this is not a mixed-source report.
- **One screenshot or clip**: same as before — describe an edit, or prompt **extract the text**, **transcribe**, or **extract the layout**.
- Asking for an image, video, or song still routes to those models even with sources attached. Image-to-video and Lyria jobs are unchanged. **Create a report** or **summarize** (including a summary of attached video/image/text, even when you quote filenames) stays on the report path — it does not generate a new video just because the sources are clips.

Folder import reads the chosen folder’s immediate files by default (no hidden files, no symlinks). **Load Folder Recursively…** includes subfolders, still skipping hidden names and symlinks.

Each source has a **⋯** menu: **Add filename to prompt** inserts the original basename at the caret (Prompt, or Search / Tool Use when tools are on), **Copy filename** puts it on the clipboard, and **Remove** drops that attachment. The name is the file you loaded (`harbor-notes.pdf`), not the archive id on disk.

Click a source in the list to preview it at the top of the pane. Images and videos play there as before; text (and song lyrics, when present) show the full body with scrollbars if it does not fit. PDFs and audio use an inline viewer when the file can be loaded. Extract / image-to-video use the image or video you name in the prompt (quote the title or filename, e.g. extract the text from the image "a toaster on fire"). If you do not name one, they use the Sources row you have selected when it is an image or video; otherwise the last image or video in the tray.

### Image Editor / Video Editor: Apply vs. Save

- Opened **from the Viewer** on an existing Archive item: **Apply** writes the edit back onto that creation's media file.
- Opened **standalone** (Load Image/Video…): use **Save** to overwrite the loaded file, or **Save As…** to write a new file, via a native save dialog.

## Gemini setup

1. Create a key at https://aistudio.google.com/apikey
2. Open **Settings** → **Models** or **Google** → paste the key → **Save API key** → pick Text / Image / Video / Audio models
3. Model lists are fetched live from Google once a key is saved; each list only shows models compatible with that modality

### Settings → what affects Creation Studio

These settings apply on the next **Create** (no app restart):

| Setting | Effect on Studio |
| --- | --- |
| **Text / Image / Video / Audio models** | Shown on the Studio model field; routing still follows prompt intent (e.g. “generate a video” uses Veo, “compose a song” uses the Lyria Audio slot) |
| **Google Search grounding (text)** | When on, an optional **Search** field appears in tools mode. When off, Search is hidden and no web research pass runs |
| **Two-pass verify** | Gemini text only, when Google Search is on and tools are off — extract with sources, then verify at temperature 0 |
| **Use Tools** | Saved default for Studio’s **Enable Tools** checkbox (applied on launch and when Settings are saved). Studio can still toggle tools for the current session without opening Settings. Text generations only |
| **OCR search images** | When a Search pass returns cited pages, download and OCR images (diagrams, scanned tables) into the research brief |
| **YouTube search captions** | When Search cites YouTube URLs, pull captions into the research brief |
| **Temperature** | Generation temperature for Gemini |
| **Extra system instructions** | Appended to every generation prompt |
| **Media folder** | Where new **PNG / MP4 / MP3 / PDF** files are written — not text, lyrics, or metadata (those stay in `archives.json`). Changing the folder may offer to move existing media; declining leaves old files where they are |

## Lyria music generation (Gemini)

Music is a fourth Gemini slot (alongside text, image, and Veo). Studio routes prompts such as “compose a song”, “generate a music clip”, or “background music, instrumental only” to the **Audio (Lyria)** model.

Enable the music models for your Gemini API key in [Google AI Studio](https://aistudio.google.com/) or the Google Cloud project tied to that key, then Settings → **Refresh…** so they appear in the Audio picker.

| Picker label | Model id | Best for |
| --- | --- | --- |
| **Lyria 3 Clip** (default) | `lyria-3-clip-preview` | 30-second clips, loops, cheap prompt iteration |
| **Lyria 3.5 / Pro** | `lyria-3.5` | Full-length songs with verses, choruses, and bridges |
| **Lyria 3 Pro Preview** | `lyria-3-pro-preview` | Older full-song id — if Google blocks it, the app retries `lyria-3.5` |

Use Clip to try a prompt, then switch to **Lyria 3.5 / Pro** when you want a longer track. Duration for full songs is influenced in the prompt (for example “a 2-minute song”) or with `[Verse]` / `[Chorus]` tags. Custom lyrics **are** allowed — include them in the prompt with those structure tags. Output is 44.1 kHz stereo **MP3**. Viewer → **Save MP3…** always uses a `.mp3` save dialog and prefills a name from the track audio (you can edit it).

The app asks Lyria for lowercase `audio` and `text` response modalities so the track and lyrics both come back. If that field is rejected, it retries without it (uppercase `AUDIO` is invalid on this endpoint).

Full-length Pro / 3.5 generations run Google’s **input and output** safety filters (recitation and vocal-likeness). A prompt that works on Clip can still return `content_blocked` on Pro. Clip lyrics often include `[0.0:4.7]` timestamps; re-sending those on Pro can trip the filter even when custom `[Verse]` lyrics are fine. If that happens, the toast explains it; drop timestamped lines, try an instrumental-only wording, drop artist names, or fall back to Clip.

**Inputs the API accepts**

- **Text** — genre, instruments, BPM, key, mood, custom lyrics, `[Verse]` / `[Chorus]` / `[Bridge]` tags
- **Image** — Studio **Load Image…** / **Sources** or Viewer **Use as Basis** on a picture, then a music prompt (image-to-music)

**Not supported** (Google’s Lyria API, not an app limitation)

- Sending an existing **MP3** as a reference / “make a new version of this track”
- Multi-turn edit of a generated clip (“make the drums louder” on the audio itself)
- Lyria RealTime (streaming) — those live models stay hidden from the picker

**Use as Basis** on a song adds the track to Studio **Sources** (so you can transcribe it or fold it into a report) and reloads the **prompt and lyrics** into the prompt box for a new Lyria clip (timestamp lines are rewritten as `[Verse]` lyrics). Lyria still does not receive the MP3. Google also safety-filters prompts that ask for a specific artist’s voice or copyrighted lyrics. All generated audio includes a SynthID watermark.

Example prompts:

```
A 30-second lofi hip hop beat with dusty vinyl crackle, mellow Rhodes
piano, boom-bap drums at 85 BPM. Instrumental only.

An upbeat chiptune title theme in C major, retro 8-bit, 120 BPM,
instrumental only.

Create a 2-minute dreamy indie pop song.

[Verse]
Walking through the neon glow…
```

## Gemini Use Tools (optional)

In **Creation Studio**, check **Enable Tools**. That is a per-session override — you do not need to open Settings. Settings → **Use Tools (local file read/write)** is only the default after launch or when that setting changes.

When tools are on, Studio hides the normal prompt and shows:

1. **Search** *(optional)* — what Google should look up for this run. Leave blank for tool-only workflows. Hidden entirely when Google Search is off in Settings.
2. **Tools** — attach one or more built-in tools with **Add Tool…**
3. **Tool Use** — describe what to do. You must mention at least one attached tool alias (e.g. `execute_powershell`, `write_text`, `browse_web`) so the app knows which capabilities you intend.

### Built-in tools

| Alias | What it does |
| --- | --- |
| `read_json` | Read a JSON file (absolute path) |
| `write_json` | Write JSON to a file (overwrites) |
| `read_text` | Read a text file |
| `write_text` | Write text to a file (overwrites) |
| `execute_powershell` | Run a `.ps1` script (Windows only); returns `stdout`, `stderr`, and `exit_code` |
| `search_gmail` | Search your Gmail inbox using Gmail query syntax |
| `search_drive` | Search Google Drive files (name, MIME type, Drive query syntax) |
| `create_drive_file` | Create a Drive file (default `text/plain`) |
| `read_google_doc` | Read a Google Doc by document ID |
| `create_google_doc` | Create a Google Doc (optional initial body) |
| `edit_google_doc` | Replace or append text in a Google Doc |
| `list_calendar_events` | List Google Calendar events in a time range |
| `create_calendar_event` | Create a Google Calendar event |
| `edit_calendar_event` | Update an existing Google Calendar event |
| `list_tasks` | List Google Tasks (default list `@default`) |
| `create_task` | Create a Google Task (title, optional notes and due date/time) |
| `edit_task` | Update or complete a Google Task |
| `browse_web` | Fetch an http(s) URL, return readable text and links, then follow links to traverse |

### Google Workspace setup (Gmail, Drive, Docs, Calendar, Tasks)

One desktop OAuth client and one stored token cover all of these tools. **Google Keep is omitted** — the Keep API is not available on a personal Gmail account; it requires a Google Workspace (enterprise) account. Adding a product later does not require a new client secret — enable the API, add the scope, then Connect again.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail**, **Google Drive**, **Google Docs**, **Google Calendar**, and **Google Tasks** APIs.
2. Create an OAuth client (**Desktop application**) and download the client JSON file.
3. Settings → **Google**: paste the **Gemini API key** and **Save API key** if you have not already (generation does not use the OAuth token). Then **Pick OAuth JSON…**, then **Connect Google Workspace…** (browser sign-in). Re-connect after adding APIs so the new scopes are granted.
4. In Creation Studio, attach the tools you need (`search_gmail`, `search_drive`, `read_google_doc`, `create_calendar_event`, …) and describe the work in **Tool Use**.

When any Google Workspace tool is attached, the app injects the machine’s current date, time, timezone, and the upcoming week into the prompt behind the scenes. You can say “this coming Wednesday at 9:45am” or “mail from yesterday” — you do not type RFC3339 or today’s date. Calendar events and Task due times use that local clock with a UTC offset (not `Z` unless you asked for UTC). Gmail and Drive search resolve relative windows the same way (`after:`, `newer_than:`, `modifiedTime`). Local file tools and `browse_web` do not get the clock.

Example Gmail queries: `is:unread in:inbox`, `category:purchases`, `subject:tracking newer_than:7d`, `from:amazon.com`.

Example Drive queries: `name contains 'budget'`, `mimeType = 'application/vnd.google-apps.document'`.

**Security note:** the token can read and write Gmail, Drive, Docs, Calendar, and Tasks data you grant at consent. It is stored as `.synthetic-text-extruder/google_workspace_token.json` (the whole `.synthetic-text-extruder/` folder is gitignored). An OAuth app in Testing must reconnect about every 7 days. Tokens left under `.retro-98-ai-creator/` or as `gmail_token.json` are copied to the new path on the next successful connect or refresh.

All paths for file tools must be **absolute** (e.g. `C:\data\step1.json`). The model infers call order from your Tool Use text once tools are attached.

### Example: Browse a URL (no Google Search)

1. Studio: **Enable Tools** on (or Settings **Use Tools** on)
2. Attach `browse_web`
3. Tool Use:

   ```
   browse_web https://docs.python.org/3/ and follow the Tutorial link, then summarize the first page
   ```

4. **Create** — Gemini fetches the page, can follow returned links with more `browse_web` calls, then summarizes.

### Example: PowerShell → text file (no web search)

1. Studio: **Enable Tools** on; Settings **Google Search** off (or on with blank Search)
2. Studio: attach `execute_powershell` and `write_text`
3. Tool Use:

   ```
   execute_powershell on C:\scripts\getdir.ps1, then write_text the stdout to C:\output\dirs.txt
   ```

4. **Create** — Gemini runs the script, captures output, and writes the file.

### Example: Search + write JSON

1. Studio: **Enable Tools** on; Settings **Google Search** on
2. Studio: attach `write_json`
3. Search: `Watch Dogs PS4 DualShock button bindings complete table`
4. Tool Use: `write_json the findings to C:\output\bindings.json` (mention `write_json`)
5. **Create** — a dedicated Search pass gathers grounded research (with optional OCR/YouTube enrichment), then the tool loop writes JSON using that brief.

### How the pipeline works

- **Tools only** (no Search text, or Google Search off): one Gemini pass with function calling on your attached tools.
- **Search + tools**: Search pass first (Google Search + URL context, plus optional image OCR and YouTube captions), then a separate tool pass that uses the research brief. Search and file tools are not combined in a single Gemini call (avoids the model skipping search or inventing file contents).
- **Image/video/music prompts** with tools on: tools are dropped for that run; Search and Tool Use text are merged into a normal media prompt instead.

**Security note:** tools read and write files on your machine, `execute_powershell` runs scripts you point at, Google tools use your connected Gmail/Drive/Docs/Calendar account, and `browse_web` fetches http(s) pages you (or the model) choose. Only attach tools you trust.

## Appearance, sound, and storage

Settings uses a left-hand list (Models, Generation, Google, Storage, Appearance). Paste a Gemini API key on **Models** or **Google** and click **Save API key**. Theme, font, and font-size preview live as you change them; they write `config.yaml` when you switch pages or leave Settings.

Settings → **Appearance**:

- **Theme**: **Light Mode (Day)** (white, black text) or **Dark Mode (Night)** (black, white text)
- **UI font**: Inter by default, plus other open-source/free fonts (they load from the network the first time you pick them)
- **Font size**: 11–22 px (default 13). Preview live; applies to chrome, prompts, and document text
- **Sound effects** on/off and volume

Settings → **Storage**:

- **Media folder**: **Browse…** or **Use project default**. This folder holds PNG/MP4/MP3 only (text and lyrics stay in `archives.json`). Default is the project `media/` folder (you can also set an absolute path). Changing the folder can offer to move existing media. Declining leaves old files where they are; Archives still opens items left in the project `media/` folder.

## Data & storage

Creations are saved automatically when you generate or import. You do **not** have to Export or Save MP3/PNG/MP4 to keep them — those Viewer buttons only make an extra copy for sharing or another folder.

| What | Where it lives |
| --- | --- |
| **PNG, JPEG, MP4, MP3, WAV** (generated or imported) | **Media folder** — default `media/` next to the app, or the folder you pick in Settings → **Storage** |
| **Text documents** (full body) | `archives.json` (project root, gitignored) — not a `.txt` in the media folder |
| **Lyrics** (from Lyria) | `archives.json`, on the song’s Archive record |
| **Prompts, titles, model ids, timestamps, extracted text, extracted UI layout** | `archives.json` (each media item also stores a `mediaPath` pointer to its file) |
| **API keys and settings** | `config.yaml` (gitignored) |

Viewer **Export TXT** / **Export Lyrics** / **Export Metadata** dump what is already in `archives.json`. **Save PNG / MP4 / MP3** copies a file that is already in the media folder. The save dialog’s initial name comes from looking at that file: Gemini describes the image, clip, song, or document, then **gemini-embedding-2** ranks those titles against an embedding of the media itself. You can change the name before saving. Without an API key, or if that fails, the dialog uses a short slug of the existing title or first prompt line.

Changing the media folder does not move files by itself. The app can offer to move existing images/video/audio; declining leaves them in place. Leftover files in the project `media/` folder still open. Text and lyrics are unaffected — they stay in `archives.json`.

Everything above is local. Nothing is uploaded except your prompts (and any image basis) to Gemini.

## config.yaml (excerpt)

All settings, including API keys, live in `config.yaml` (gitignored). **Save API key** writes `gemini.api_key` immediately. Other Settings write when you switch pages or leave Settings. Browse / OAuth pickers, Refresh, and Recommend also save immediately so those actions have the latest key and paths. Copy `config.example.yaml` to get started, or just use Settings.

```yaml
backend:
  provider: gemini

gemini:
  text_model: gemini-2.5-flash
  image_model: gemini-2.5-flash-image
  video_model: veo-2.0-generate-001
  audio_model: lyria-3-clip-preview   # or lyria-3.5 / lyria-3-pro-preview
  api_key: your_key_here
  google_search: true
  two_pass_verify: true
  use_tools: false
  ocr_search_images: true
  youtube_search_captions: true
  temperature: 0.0

prompt:
  extra_instructions: ""

ui:
  app_theme: light    # light | dark
  sound_enabled: true
  ui_font: inter      # open-source UI fonts (Inter, Roboto, …)
  ui_font_size: 13    # UI font size in px (11–22)
  studio_basis_width: 280  # Creation Studio Sources pane (px)

paths:
  archives: archives.json
  media: media   # or an absolute folder set from Settings
```

## License

MIT — see [LICENSE](LICENSE). UI fonts are loaded from Google Fonts (open-source licenses such as OFL and Apache 2.0).
