<#
.SYNOPSIS
  Start, capture and stop a 1C test client (/TestClient) for QA MCP in native mode.

.DESCRIPTION
  Shipped with the QA MCP rule qa-mcp-ui-testing. The agent runs it on the Windows
  machine of the test client; QA MCP itself never touches Windows.

    start   - start 1cv8c.exe /TestClient on -Port, visible or on a hidden desktop
              (-Hidden), and wait until the main window opens; -MaxSeconds closes
              it after a deadline; a failed start returns 1C's own message
    capture - save a PNG of the client's windows, also on the hidden desktop
    stop    - close a client that this script started
    status  - what this script started on -Port

  Every call prints one JSON object. On failure it has an "error" field and the
  exit code is 1.

.EXAMPLE
  .\qa-testclient.ps1 start -Base "C:\Bases\TestCopy" -User Admin -Hidden
  .\qa-testclient.ps1 capture
  .\qa-testclient.ps1 stop
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('start', 'capture', 'stop', 'status')]
    [string]$Action,
    [int]$Port = 1538,
    # File infobase path (/F) or server infobase "server\infobase" (/S).
    [string]$Base,
    [string]$Server,
    [string]$User,
    # Name of the environment variable that holds the 1C password; never the password itself.
    [string]$PasswordEnv,
    [switch]$Hidden,
    # Platform version, e.g. 8.3.27.2130; the newest installed one by default.
    [string]$Version,
    # capture: PNG path; default %TEMP%\mcp_qa_testclient\<port>-<time>.png
    [string]$Out,
    # start: close the client this many seconds after launch, startup included; 0 = no limit.
    [int]$MaxSeconds = 0,
    [int]$TimeoutSec = 180
)

$ErrorActionPreference = 'Stop'
$StateDir = Join-Path $env:LOCALAPPDATA 'mcp_qa_testclient'
$StateFile = Join-Path $StateDir "$Port.json"

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class QaTestClientNative {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct STARTUPINFO {
        public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct PROCESS_INFORMATION { public IntPtr hProcess, hThread; public int dwProcessId, dwThreadId; }
    [StructLayout(LayoutKind.Sequential)]
    struct RECT { public int Left, Top, Right, Bottom; }
    delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);

    const uint GENERIC_ALL = 0x10000000;
    const uint PW_RENDERFULLCONTENT = 2;

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr CreateDesktop(string name, IntPtr device, IntPtr devmode, int flags, uint access, IntPtr sa);
    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern IntPtr OpenDesktop(string name, int flags, bool inherit, uint access);
    [DllImport("user32.dll", SetLastError = true)] static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", SetLastError = true)] static extern bool SetThreadDesktop(IntPtr desktop);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool CreateProcess(string app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit,
        int flags, IntPtr env, string dir, ref STARTUPINFO si, out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("user32.dll")] static extern bool EnumDesktopWindows(IntPtr desktop, EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern int GetWindowThreadProcessId(IntPtr hwnd, out int pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int max);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, StringBuilder name, int max);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);

    // The caller keeps the handle until the client listens: a desktop without handles
    // or threads is destroyed, and the new process could not attach to it.
    public static IntPtr OpenHiddenDesktop(string name) {
        IntPtr desktop = CreateDesktop(name, IntPtr.Zero, IntPtr.Zero, 0, GENERIC_ALL, IntPtr.Zero);
        if (desktop == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateDesktop " + name);
        return desktop;
    }

    public static void Release(IntPtr desktop) { if (desktop != IntPtr.Zero) CloseDesktop(desktop); }

    public static int Spawn(string desktop, string commandLine, string dir) {
        STARTUPINFO si = new STARTUPINFO();
        si.cb = Marshal.SizeOf(typeof(STARTUPINFO));
        si.lpDesktop = "WinSta0\\" + desktop;
        PROCESS_INFORMATION pi;
        if (!CreateProcess(null, new StringBuilder(commandLine), IntPtr.Zero, IntPtr.Zero, false, 0,
                IntPtr.Zero, dir, ref si, out pi))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcess");
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
        return pi.dwProcessId;
    }

    // Both run on a fresh thread: SetThreadDesktop needs a thread without windows.
    public static string[] Capture(int pid, string desktop, string path) {
        return OnThread<string[]>(delegate() { return CaptureOnThread(pid, desktop, path); });
    }

    // The test port opens before the licence and sign-in checks; the main window means the client is up.
    public static bool HasMainWindow(int pid, string desktop) {
        return OnThread<bool>(delegate() {
            IntPtr handle = IntPtr.Zero;
            try {
                foreach (IntPtr hwnd in ClientWindows(pid, desktop, out handle)) {
                    StringBuilder cls = new StringBuilder(256);
                    GetClassName(hwnd, cls, cls.Capacity);
                    if (cls.ToString().StartsWith("V8TopLevelFrame", StringComparison.Ordinal)) return true;
                }
                return false;
            } finally {
                if (handle != IntPtr.Zero) CloseDesktop(handle);
            }
        });
    }

    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

    // A client killed by force keeps its place in the developer licence count of a file
    // infobase while another process holds the base open, so the main window is closed first.
    public static int CloseMainWindows(int pid, string desktop) {
        return OnThread<int>(delegate() {
            IntPtr handle = IntPtr.Zero;
            int posted = 0;
            try {
                foreach (IntPtr hwnd in ClientWindows(pid, desktop, out handle)) {
                    StringBuilder cls = new StringBuilder(256);
                    GetClassName(hwnd, cls, cls.Capacity);
                    if (cls.ToString().StartsWith("V8TopLevelFrame", StringComparison.Ordinal)
                            && PostMessage(hwnd, 0x0010 /* WM_CLOSE */, IntPtr.Zero, IntPtr.Zero)) posted++;
                }
                return posted;
            } finally {
                if (handle != IntPtr.Zero) CloseDesktop(handle);
            }
        });
    }

    delegate T Work<T>();

    static T OnThread<T>(Work<T> work) {
        T result = default(T);
        Exception error = null;
        Thread worker = new Thread(delegate() {
            try { result = work(); } catch (Exception e) { error = e; }
        });
        worker.Start();
        worker.Join();
        if (error != null) throw error;
        return result;
    }

    // Visible, not minimised top-level windows of the process, from the top of the z-order down.
    static List<IntPtr> ClientWindows(int pid, string desktop, out IntPtr handle) {
        try { SetThreadDpiAwarenessContext(new IntPtr(-4)); } catch (EntryPointNotFoundException) { }
        List<IntPtr> windows = new List<IntPtr>();
        EnumProc collect = delegate(IntPtr hwnd, IntPtr lParam) {
            int owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner != pid || !IsWindowVisible(hwnd) || IsIconic(hwnd)) return true;
            // Windows puts its UAC input indicator into the client process; it is not a 1C window.
            StringBuilder cls = new StringBuilder(256);
            GetClassName(hwnd, cls, cls.Capacity);
            if (!cls.ToString().StartsWith("UAC", StringComparison.Ordinal)) windows.Add(hwnd);
            return true;
        };
        handle = IntPtr.Zero;
        if (!String.IsNullOrEmpty(desktop)) {
            handle = OpenDesktop(desktop, 0, false, GENERIC_ALL);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "OpenDesktop " + desktop);
            if (!SetThreadDesktop(handle)) throw new Win32Exception(Marshal.GetLastWin32Error(), "SetThreadDesktop");
            EnumDesktopWindows(handle, collect, IntPtr.Zero);
        } else {
            EnumWindows(collect, IntPtr.Zero);
        }
        return windows;
    }

    static string[] CaptureOnThread(int pid, string desktop, string path) {
        IntPtr handle = IntPtr.Zero;
        try {
            List<IntPtr> windows = ClientWindows(pid, desktop, out handle);
            List<IntPtr> shown = new List<IntPtr>();
            List<RECT> rects = new List<RECT>();
            int left = Int32.MaxValue, top = Int32.MaxValue, right = Int32.MinValue, bottom = Int32.MinValue;
            foreach (IntPtr hwnd in windows) {
                RECT r;
                if (!GetWindowRect(hwnd, out r)) continue;
                if (r.Right - r.Left < 2 || r.Bottom - r.Top < 2 || r.Left <= -30000) continue;
                shown.Add(hwnd);
                rects.Add(r);
                left = Math.Min(left, r.Left); top = Math.Min(top, r.Top);
                right = Math.Max(right, r.Right); bottom = Math.Max(bottom, r.Bottom);
            }
            if (shown.Count == 0)
                throw new InvalidOperationException("No visible windows of process " + pid + " (minimized, or the client has not opened a window yet)");
            string[] titles = new string[shown.Count];
            using (Bitmap canvas = new Bitmap(right - left, bottom - top))
            using (Graphics g = Graphics.FromImage(canvas)) {
                g.Clear(Color.Black);
                // Enumeration goes from the top of the z-order down; paint the bottom first.
                for (int i = shown.Count - 1; i >= 0; i--) {
                    RECT r = rects[i];
                    int w = r.Right - r.Left, h = r.Bottom - r.Top;
                    using (Bitmap one = new Bitmap(w, h)) {
                        using (Graphics gw = Graphics.FromImage(one)) {
                            IntPtr hdc = gw.GetHdc();
                            try { PrintWindow(shown[i], hdc, PW_RENDERFULLCONTENT); } finally { gw.ReleaseHdc(hdc); }
                        }
                        g.DrawImage(one, new Rectangle(r.Left - left, r.Top - top, w, h));
                    }
                    StringBuilder text = new StringBuilder(512);
                    GetWindowText(shown[i], text, text.Capacity);
                    titles[i] = text.ToString();
                }
                canvas.Save(path, ImageFormat.Png);
            }
            return titles;
        } finally {
            if (handle != IntPtr.Zero) CloseDesktop(handle);
        }
    }
}
'@

function Write-Result([hashtable]$Data) {
    [pscustomobject]$Data | ConvertTo-Json -Compress -Depth 5
}

function Read-State {
    if (Test-Path -LiteralPath $StateFile) { return Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json }
    return $null
}

function Test-Alive([int]$ProcessId) {
    return [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Stop-Watchdog($State) {
    # When the watchdog itself runs 'stop', it is this process's parent and ends on its own.
    $parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
    if ($State.watchdog -and $State.watchdog -ne $parent) {
        Get-Process -Id $State.watchdog -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -eq 'powershell' } | Stop-Process -Force
    }
}

function Get-Listener {
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Find-Client {
    $found = foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $root) { continue }
        Get-ChildItem -Path (Join-Path $root '1cv8') -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $parsed = $null
            $exe = Join-Path $_.FullName 'bin\1cv8c.exe'
            if ([version]::TryParse($_.Name, [ref]$parsed) -and (Test-Path -LiteralPath $exe)) {
                [pscustomobject]@{ Version = $parsed; Exe = $exe }
            }
        }
    }
    if ($Version) { $found = $found | Where-Object { $_.Version -eq [version]$Version } }
    $pick = $found | Sort-Object Version -Descending | Select-Object -First 1
    if (-not $pick) { throw "1cv8c.exe $Version not found under Program Files\1cv8" }
    return $pick
}

function Start-TestClient {
    if (-not $Base -and -not $Server) { throw 'Pass -Base <file infobase> or -Server <server\infobase>' }
    $state = Read-State
    if ($state -and (Test-Alive $state.pid)) { throw "A client started by this script already runs on port $Port (pid $($state.pid))" }
    $listener = Get-Listener
    if ($listener) { throw "Port $Port is already listening (pid $($listener.OwningProcess))" }

    $client = Find-Client
    $arguments = @('ENTERPRISE')
    if ($Base) { $arguments += "/F`"$Base`"" } else { $arguments += "/S`"$Server`"" }
    if ($User) { $arguments += "/N`"$User`"" }
    if ($PasswordEnv) {
        $password = [Environment]::GetEnvironmentVariable($PasswordEnv)
        if ($password) { $arguments += "/P`"$password`"" }
    }
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    # Start-up errors (licence, sign-in) are not shown with /DisableStartupDialogs; 1C writes them here.
    $log = Join-Path $StateDir "$Port.log"
    $arguments += @('/TestClient', "-TPort$Port", '/DisableStartupDialogs', '/DisableStartupMessages', "/Out `"$log`"")
    $workDir = Split-Path -Parent $client.Exe

    $desktop = ''
    $desktopHandle = [IntPtr]::Zero
    if ($Hidden) {
        $desktop = "mcpqa_$Port"
        $desktopHandle = [QaTestClientNative]::OpenHiddenDesktop($desktop)
    }
    try {
        if ($Hidden) {
            $commandLine = "`"$($client.Exe)`" " + ($arguments -join ' ')
            $processId = [QaTestClientNative]::Spawn($desktop, $commandLine, $workDir)
        } else {
            $processId = (Start-Process -FilePath $client.Exe -ArgumentList $arguments -WorkingDirectory $workDir -PassThru).Id
        }
        $state = [ordered]@{
            pid = $processId; port = $Port; hidden = [bool]$Hidden; desktop = $desktop
            base = $(if ($Base) { $Base } else { $Server }); version = "$($client.Version)"
            started = (Get-Date).ToString('s')
        }
        if ($MaxSeconds -gt 0) {
            # The watchdog checks the start time, so a reused process id is never touched,
            # and closes the client with 'stop' like the agent does.
            $startTime = (Get-Process -Id $processId).StartTime.ToFileTimeUtc()
            $self = $PSCommandPath -replace "'", "''"
            $report = (Join-Path $StateDir "$Port-deadline.json") -replace "'", "''"
            $watch = "Start-Sleep -Seconds $MaxSeconds; `$p = Get-Process -Id $processId -ErrorAction SilentlyContinue; " +
                "if (`$p -and `$p.StartTime.ToFileTimeUtc() -eq $startTime) { " +
                "& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '$self' stop -Port $Port | Set-Content -LiteralPath '$report' }"
            $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($watch))
            $watchdog = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru `
                -ArgumentList @('-NoProfile', '-NonInteractive', '-EncodedCommand', $encoded)
            $state.deadline = (Get-Date).AddSeconds($MaxSeconds).ToString('s')
            $state.watchdog = $watchdog.Id
        }
        $state | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8

        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        $listening = $false
        $ready = $false
        while ((Get-Date) -lt $deadline) {
            if (-not (Test-Alive $processId)) {
                $message = if (Test-Path -LiteralPath $log) { (Get-Content -LiteralPath $log -Tail 5) -join ' ' } else { '' }
                Stop-Watchdog $state
                Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
                throw "The client exited during start-up. $message"
            }
            if (-not $listening) {
                $listener = Get-Listener
                $listening = [bool]($listener -and $listener.OwningProcess -eq $processId)
            }
            if ($listening -and [QaTestClientNative]::HasMainWindow($processId, $desktop)) { $ready = $true; break }
            Start-Sleep -Seconds 2
        }
    } finally {
        [QaTestClientNative]::Release($desktopHandle)
    }
    $result = @{} + $state
    $result.listening = $listening
    $result.ready = $ready
    if (-not $ready) {
        $result.error = "No main window after $TimeoutSec s (port listening: $listening); a start-up dialog may be waiting - run 'capture', then 'stop'"
    }
    return $result
}

function Save-Capture {
    $state = Read-State
    if ($state -and (Test-Alive $state.pid)) {
        $processId = [int]$state.pid
        $desktop = [string]$state.desktop
    } else {
        $listener = Get-Listener
        if (-not $listener) { throw "Nothing listens on port $Port and this script started no client there" }
        $processId = [int]$listener.OwningProcess
        $desktop = ''
    }
    if (-not $Out) {
        $dir = Join-Path $env:TEMP 'mcp_qa_testclient'
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $Out = Join-Path $dir ("{0}-{1}.png" -f $Port, (Get-Date -Format 'yyyyMMdd-HHmmss'))
    }
    $Out = [IO.Path]::GetFullPath($Out)
    $titles = [QaTestClientNative]::Capture($processId, $desktop, $Out)
    return @{ path = $Out; pid = $processId; hidden = [bool]$desktop; windows = @($titles) }
}

function Stop-TestClient {
    $state = Read-State
    if (-not $state) { throw "This script started no client on port $Port; a client started by a person is closed by that person" }
    $alive = Test-Alive $state.pid
    $how = 'not running'
    if ($alive) {
        $how = 'closed'
        [void][QaTestClientNative]::CloseMainWindows([int]$state.pid, [string]$state.desktop)
        $wait = (Get-Date).AddSeconds(20)
        while ((Test-Alive $state.pid) -and (Get-Date) -lt $wait) { Start-Sleep -Milliseconds 500 }
        if (Test-Alive $state.pid) { Stop-Process -Id $state.pid -Force; $how = 'killed' }
    }
    Stop-Watchdog $state
    Remove-Item -LiteralPath $StateFile -Force
    return @{ port = $Port; pid = $state.pid; stopped = [bool]$alive; how = $how }
}

function Get-TestClientStatus {
    $state = Read-State
    $listener = Get-Listener
    $result = @{ port = $Port; listening = [bool]$listener; started_here = [bool]$state }
    if ($listener) { $result.listener_pid = $listener.OwningProcess }
    if ($state) {
        $result.pid = $state.pid; $result.hidden = $state.hidden; $result.base = $state.base
        if ($state.deadline) { $result.deadline = $state.deadline }
        $result.alive = Test-Alive $state.pid
    }
    return $result
}

try {
    switch ($Action) {
        'start' { $data = Start-TestClient }
        'capture' { $data = Save-Capture }
        'stop' { $data = Stop-TestClient }
        'status' { $data = Get-TestClientStatus }
    }
    Write-Result $data
    if ($data.error) { exit 1 }
} catch {
    Write-Result @{ error = $_.Exception.Message; action = $Action; port = $Port }
    exit 1
}
