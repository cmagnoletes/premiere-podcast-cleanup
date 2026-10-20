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

Not tested by me; the Premiere MCP itself is only validated on macOS. These are the equivalent
steps and they should work, but expect to troubleshoot.

```powershell
winget install OpenJS.NodeJS.LTS
winget install Python.Python.3.12
winget install Gyan.FFmpeg
```

MCP:

```powershell
mkdir $HOME\mcp-servers; cd $HOME\mcp-servers
git clone https://github.com/hetpatel-11/Adobe_Premiere_Pro_MCP.git
cd Adobe_Premiere_Pro_MCP
npm install
npm run build
```

There is no Windows installer, so install the panel by hand:

1. Turn on Adobe extension debug mode (PowerShell, then restart Premiere):
   ```powershell
   foreach ($v in 10,11,12) { New-Item -Path "HKCU:\Software\Adobe\CSXS.$v" -Force | Out-Null; Set-ItemProperty -Path "HKCU:\Software\Adobe\CSXS.$v" -Name PlayerDebugMode -Value 1 -Type String }
   ```
2. Copy the panel:
   ```powershell
   $dst = "$env:APPDATA\Adobe\CEP\extensions\MCPBridgeCEP"
   New-Item -ItemType Directory -Force -Path $dst | Out-Null
   Copy-Item -Recurse -Force .\cep-plugin\* $dst
   ```
3. Pick a temp folder, e.g. `C:\Temp\premiere-mcp-bridge` (create it), and use it in both places:
   ```powershell
   claude mcp add premiere-pro --scope user -e PREMIERE_TEMP_DIR=C:\Temp\premiere-mcp-bridge -- node "$HOME\mcp-servers\Adobe_Premiere_Pro_MCP\dist\index.js"
   ```
   and in the panel's **Temp Directory** field.

Skill (no symlink needed, copy it):

```powershell
git clone https://github.com/cmagnoletes/premiere-podcast-cleanup.git
New-Item -ItemType Directory -Force -Path "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse -Force .\premiere-podcast-cleanup\skills\podcast-cleanup "$HOME\.claude\skills\"
```

On Windows run the script with `python` instead of `python3`. Re-copy the skill folder after a `git pull`.
