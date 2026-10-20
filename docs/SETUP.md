# Setup

Four pieces: the tools (Node, Python, ffmpeg), the Premiere MCP, the panel inside Premiere, and
this skill. Do it once. Mac first; Windows notes at the bottom.

## 0. The tools (Mac)

```bash
# Homebrew, if you don't have it: https://brew.sh
brew install node ffmpeg
python3 --version    # 3.9 or newer; macOS ships one
```

Install Claude Code if you haven't: https://claude.com/claude-code

## 1. The Premiere MCP

The MCP is what lets Claude talk to Premiere. It is a separate open-source project:
https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP

```bash
mkdir -p ~/mcp-servers && cd ~/mcp-servers
git clone https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP.git
cd Adobe_Premiere_Pro_MCP
npm install
npm run build
npm run setup:mac        # installs the panel into Premiere and turns on Adobe's extension debug mode
```

`setup:mac` also writes a Claude **Desktop** config. That's harmless. For Claude **Code**, register
the server yourself (one line, your real path):

```bash
claude mcp add premiere-pro --scope user -e PREMIERE_TEMP_DIR=/tmp/premiere-mcp-bridge -- node "$HOME/mcp-servers/Adobe_Premiere_Pro_MCP/dist/index.js"
```

Check it registered:

```bash
claude mcp list
```

## 2. The panel inside Premiere

1. Quit and reopen Premiere Pro.
2. `Premiere Pro > Settings (Preferences) > Plugins` → tick **Enable developer mode** under UXP plugins → restart Premiere if you changed it.
3. Open a project, then `Window > Extensions > MCP Bridge (CEP)`.
4. Temp Directory: `/tmp/premiere-mcp-bridge` → **Save Configuration** → **Start Bridge** → **Test Connection**.

You start the bridge each time you open Premiere (step 4, just **Start Bridge**).

Test from Claude Code:

> What's my current Premiere Pro project info?

If Claude answers with your project name, the MCP works. If not, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md#the-mcp-doesnt-answer).
The MCP has a doctor too: `cd ~/mcp-servers/Adobe_Premiere_Pro_MCP && npm run setup:doctor`.

## 3. This skill

```bash
cd ~/mcp-servers   # or wherever you keep tools
git clone https://github.com/cmagnoletes/premiere-podcast-cleanup.git
cd premiere-podcast-cleanup
./install.sh
```

`install.sh` links `skills/podcast-cleanup` into `~/.claude/skills/`, so a `git pull` later updates
the skill in place. It also checks that Python and ffmpeg are present and runs the tests.

Restart Claude Code. Ask it: *"What skills do you have for podcast cleanup?"*; it should name
`podcast-cleanup`.

## 4. First real run

Use a short sequence first (5 minutes of an old episode):

1. Make a copy of an edited sequence (right-click → Duplicate) so you are relaxed about it.
2. `Window > Text` → **Transcript** → **Transcribe sequence** (all mic tracks included).
3. In Claude Code: *"Clean up the active sequence in Premiere."*
4. Follow its prompts (it will ask you for the transcript export).
5. Compare the two sequences. Read the report.

---

## Windows

Untested by me: I edit on a Mac, and the Premiere MCP is only validated on macOS. Its code does
have Windows paths in it, and every step below is the Windows version of a step that works on Mac.
Expect to troubleshoot once; after that it runs the same.

Use **PowerShell** (not Command Prompt) for everything below. After any `winget install`, close
PowerShell and open a new window, or the new command won't be found.

### 0. The tools

```powershell
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install Git.Git
```

Check, in a **new** window:

```powershell
node --version; py --version; ffmpeg -version; git --version
```

If `py` isn't found, try `python --version`. If typing `python` opens the Microsoft Store, that's a
fake shortcut: turn it off in Settings > Apps > Advanced app settings > **App execution aliases**
(switch off both "python" entries) and reopen PowerShell.

Install Claude Code: https://claude.com/claude-code

### 1. The Premiere MCP

```powershell
mkdir $HOME\mcp-servers; cd $HOME\mcp-servers
git clone https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP.git
cd Adobe_Premiere_Pro_MCP
npm install
npm run build
```

`npm run setup:mac` is Mac-only. On Windows, do its two jobs by hand:

**a. Allow unsigned panels in Premiere** (Adobe's "debug mode"; one command, then restart Premiere):

```powershell
foreach ($v in 9,10,11,12,13) { New-Item -Path "HKCU:\Software\Adobe\CSXS.$v" -Force | Out-Null; Set-ItemProperty -Path "HKCU:\Software\Adobe\CSXS.$v" -Name PlayerDebugMode -Value 1 -Type String }
```

**b. Copy the panel into Adobe's extensions folder:**

```powershell
$dst = "$env:APPDATA\Adobe\CEP\extensions\MCPBridgeCEP"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force .\cep-plugin\* $dst
```

### 2. One temp folder, the same in two places

The MCP and the panel talk by dropping files in a shared folder. **On Windows the panel ignores any
`/tmp/...` path** (you'll see the field go blank), so use a real Windows folder:

```powershell
mkdir C:\Temp\premiere-mcp-bridge -Force
claude mcp add premiere-pro --scope user -e PREMIERE_TEMP_DIR=C:\Temp\premiere-mcp-bridge -- node "$HOME\mcp-servers\Adobe_Premiere_Pro_MCP\dist\index.js"
claude mcp list
```

Then in Premiere: Window > Extensions > **MCP Bridge (CEP)** → Temp Directory
`C:\Temp\premiere-mcp-bridge` (exactly the same, character for character) → **Save Configuration**
→ **Start Bridge** → **Test Connection**.

Test from Claude Code: *"What's my current Premiere Pro project info?"*

If the panel isn't in Window > Extensions, the debug-mode step (1a) didn't take: rerun it and fully
quit Premiere (check Task Manager) before reopening.

### 3. This skill

```powershell
cd $HOME\mcp-servers
git clone https://github.com/cmagnoletes/premiere-podcast-cleanup.git
cd premiere-podcast-cleanup
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` links the skill into `%USERPROFILE%\.claude\skills\` (a folder junction: no admin
rights needed, and `git pull` updates it), checks Python and ffmpeg, and runs the tests.

### Differences when you use it

- Run the script with `py` (or `python`) instead of `python3`. Claude handles this when it runs it.
- Paths with spaces need quotes: `py ...\podcast_clean.py --xml "D:\Podcast\Ep 12\ep12.xml" ...`
- Media on a network drive works if the drive is reachable from this PC (`\\NAS\share\...` or a
  mapped letter). If not, export a WAV mixdown and pass `--audio`.
- Open the report by double-clicking `...-cleaned-report.html`, or `start ep12-cleaned-report.html`.
- If Premiere asks where media is when you import the cleaned XML, point it at the same files your
  original sequence uses.

### Windows-only problems

| Symptom | Fix |
|---|---|
| `py`/`python` not recognized | open a new PowerShell window; else reinstall Python with "Add to PATH" ticked |
| `python` opens the Microsoft Store | App execution aliases, see step 0 |
| `ffmpeg` not recognized | new PowerShell window; `winget install Gyan.FFmpeg` again |
| `install.ps1 cannot be loaded because running scripts is disabled` | use the exact `powershell -ExecutionPolicy Bypass -File .\install.ps1` line |
| panel Temp Directory goes blank | you typed a `/tmp/...` path; use `C:\Temp\premiere-mcp-bridge` |
| Claude can't reach Premiere | the two temp paths differ, or the bridge isn't started; `claude mcp list` shows the one Claude uses |
| antivirus quarantines files in the temp folder | add `C:\Temp\premiere-mcp-bridge` as an exclusion |
