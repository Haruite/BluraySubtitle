$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$workspace = [IO.Path]::GetFullPath($PSScriptRoot)
$install = [IO.Directory]::GetParent($workspace).FullName
$plan = Get-Content -LiteralPath (Join-Path $workspace 'update.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime = Join-Path $install '_internal'
$archive = Join-Path $workspace 'package.7z'
$unpacked = Join-Path $workspace 'unpacked'
$previous = Join-Path $workspace 'previous'
$package = Join-Path $unpacked 'BluraySubtitle_windows_x64'
$nextExecutable = Join-Path $package 'BluraySubtitle_windows_x64.exe'
$nextRuntime = Join-Path $package '_internal'
$moves = [Collections.Generic.Stack[hashtable]]::new()

function Assert-PlainTree([string]$Path) {
    $pending = [Collections.Generic.Stack[IO.FileSystemInfo]]::new()
    $pending.Push((Get-Item -LiteralPath $Path -Force))
    while ($pending.Count -gt 0) {
        $entry = $pending.Pop()
        if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw $plan.unsafePath
        }
        if ($entry -is [IO.DirectoryInfo]) {
            foreach ($child in Get-ChildItem -LiteralPath $entry.FullName -Force) {
                $pending.Push($child)
            }
        }
    }
}

function Get-PackageHash([string]$Path) {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.File]::OpenRead($Path)
        try {
            return [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '')
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha256.Dispose()
    }
}

function Copy-InternalPreferences {
    if ($null -eq $plan.configDirectory) { return }
    $source = [IO.Path]::GetFullPath((Join-Path $runtime $plan.configDirectory))
    $target = [IO.Path]::GetFullPath((Join-Path $nextRuntime $plan.configDirectory))
    if (($source -ne $runtime -and -not $source.StartsWith("$runtime\", [StringComparison]::OrdinalIgnoreCase)) -or
        ($target -ne $nextRuntime -and -not $target.StartsWith("$nextRuntime\", [StringComparison]::OrdinalIgnoreCase))) {
        throw $plan.unsafePath
    }
    foreach ($name in @('config.json', 'logs')) {
        $from = Join-Path $source $name
        if (Test-Path -LiteralPath $from) {
            $to = Join-Path $target $name
            if (Test-Path -LiteralPath $to) { throw $plan.invalidPackage }
            [void][IO.Directory]::CreateDirectory($target)
            Copy-Item -LiteralPath $from -Destination $to -Recurse
        }
    }
}

function Move-ProgramItem([string]$Source, [string]$Target, [bool]$Directory) {
    if ($Directory) {
        [IO.Directory]::Move($Source, $Target)
    } else {
        [IO.File]::Move($Source, $Target)
    }
    $moves.Push(@{Source = $Target; Target = $Source; Directory = $Directory})
}

function Undo-ProgramMoves {
    while ($moves.Count -gt 0) {
        $move = $moves.Pop()
        if ($move.Directory) {
            [IO.Directory]::Move($move.Source, $move.Target)
        } else {
            [IO.File]::Move($move.Source, $move.Target)
        }
    }
}

function Start-BluraySubtitle([bool]$CheckStartup) {
    $directory = $install
    if (Test-Path -LiteralPath $plan.workingDirectory -PathType Container) {
        $directory = $plan.workingDirectory
    }
    $startInfo = [Diagnostics.ProcessStartInfo]::new($executable, '--detached-gui')
    $startInfo.WorkingDirectory = $directory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = [Diagnostics.Process]::Start($startInfo)
    try {
        if ($CheckStartup -and $process.WaitForExit(1500) -and $process.ExitCode -ne 0) {
            throw $plan.restartFailed
        }
    } finally {
        $process.Dispose()
    }
}

function Show-UpdateMessage([string]$Message) {
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($Message, $plan.title, 'OK', 'Warning')
}

$safeWorkspace = $false
$restartPrevious = $false
$keepWorkspace = $false
$updated = $false
$mutex = $null
$ownsMutex = $false
$failure = $null
try {
    if ([IO.Path]::GetFileName($workspace) -notlike '.bluraysubtitle-update-*' -or
        ((Get-Item -LiteralPath $workspace -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw $plan.unsafePath
    }
    $safeWorkspace = $true
    if ([IO.Path]::GetFileName($plan.executable) -ne $plan.executable -or
        [IO.Path]::GetExtension($plan.executable) -ne '.exe') {
        throw $plan.unsafePath
    }
    $executable = Join-Path $install $plan.executable

    $mutex = [Threading.Mutex]::new($false, [string]$plan.mutex)
    try {
        $ownsMutex = $mutex.WaitOne(0)
    } catch [Threading.AbandonedMutexException] {
        $ownsMutex = $true
    }
    if (-not $ownsMutex) { throw $plan.busy }
    $parentProcess = Get-Process -Id $plan.pid -ErrorAction SilentlyContinue
    if ($null -ne $parentProcess) { $parentProcess.WaitForExit() }
    $restartPrevious = $true
    Assert-PlainTree $executable
    Assert-PlainTree $runtime

    $uri = [Uri]$plan.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin @('github.com', 'sbx.mysmy.top')) {
        throw $plan.invalidPackage
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $archive
    if ($plan.sha256 -notmatch '^[0-9a-f]{64}$' -or (Get-PackageHash $archive) -ne $plan.sha256) {
        throw $plan.invalidDigest
    }

    [void][IO.Directory]::CreateDirectory($unpacked)
    $sevenZip = Join-Path $runtime '7z.exe'
    & $sevenZip x -y -bso0 -bsp0 "-o$unpacked" -- $archive
    if ($LASTEXITCODE -ne 0) { throw $plan.extractFailed }
    if (-not (Test-Path -LiteralPath $nextExecutable -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $nextRuntime 'build-commit.txt') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $nextRuntime '7z.exe') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $nextRuntime '7z.dll') -PathType Leaf)) {
        throw $plan.invalidPackage
    }

    # All directory moves and removals stay within the resolved installation and staging trees.
    Assert-PlainTree $unpacked
    Copy-InternalPreferences
    [void][IO.Directory]::CreateDirectory($previous)
    Move-ProgramItem $executable (Join-Path $previous $plan.executable) $false
    Move-ProgramItem $runtime (Join-Path $previous '_internal') $true
    Move-ProgramItem $nextRuntime $runtime $true
    Move-ProgramItem $nextExecutable $executable $false
    Start-BluraySubtitle $true
    $updated = $true
} catch {
    $failure = "$($plan.failure)`r`n$($_.Exception.Message)"
    try {
        Undo-ProgramMoves
        if ($restartPrevious) { Start-BluraySubtitle $false }
    } catch {
        $keepWorkspace = $true
        $failure += "`r`n$($_.Exception.Message)`r`n$($plan.backup)"
    }
} finally {
    if ($safeWorkspace -and -not $keepWorkspace) {
        try {
            Assert-PlainTree $workspace
            Remove-Item -LiteralPath $workspace -Recurse -Force
        } catch {
            if ($updated) { $failure = $plan.cleanupFailed }
            $failure += "`r`n$($plan.backup)"
        }
    }
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    if ($null -ne $mutex) { $mutex.Dispose() }
}
if ($failure) {
    Show-UpdateMessage $failure
    exit 1
}
