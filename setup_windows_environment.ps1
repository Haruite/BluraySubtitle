param(
    [ValidateSet("en", "zh")][string]$Language,
    [ValidateSet("Desktop", "Build")][string]$Mode = "Desktop",
    [string]$BuildCacheDirectory
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 3.0

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-NativeArgument {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Get-NativePowerShellPath {
    $windowsDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    if ([IntPtr]::Size -eq 4 -and [Environment]::Is64BitOperatingSystem) {
        $sysnativePowerShell = Join-Path $windowsDirectory "Sysnative\WindowsPowerShell\v1.0\powershell.exe"
        if (Test-Path -LiteralPath $sysnativePowerShell -PathType Leaf) {
            return $sysnativePowerShell
        }
    }

    return Join-Path $windowsDirectory "System32\WindowsPowerShell\v1.0\powershell.exe"
}

function Start-ElevatedSetup {
    if (-not $PSCommandPath) {
        throw "The setup script path cannot be resolved."
    }

    $arguments = @("-NoProfile")
    if (-not $Language) {
        $arguments += "-NoExit"
    }
    $arguments += @("-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    if ($Language) {
        $arguments += @("-Language", $Language)
    }

    $argumentLine = ($arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join " "
    $workingDirectory = (Get-Location).Path
    try {
        $process = Start-Process `
            -FilePath (Get-NativePowerShellPath) `
            -ArgumentList $argumentLine `
            -WorkingDirectory $workingDirectory `
            -Verb RunAs `
            -Wait `
            -PassThru
        return $process.ExitCode
    }
    catch {
        [Console]::Error.WriteLine("Administrator permission is required. / 需要管理员权限。 " + $_.Exception.Message)
        return 1223
    }
}

# Elevation is the first operation performed by the setup script.
if (-not (Test-Administrator)) {
    if ($Mode -eq "Build") {
        [Console]::Error.WriteLine("Build mode requires an elevated PowerShell session. / 构建模式需要管理员权限的 PowerShell 会话。")
        exit 1
    }
    $elevatedExitCode = Start-ElevatedSetup
    if ($elevatedExitCode -ne 0) {
        exit $elevatedExitCode
    }
    return
}

# Keep the API token out of the environment inherited by external build tools.
$script:GitHubApiToken = $env:BLURAYSUBTITLE_GITHUB_TOKEN
$env:BLURAYSUBTITLE_GITHUB_TOKEN = $null

$script:Utf8Encoding = New-Object Text.UTF8Encoding($false)
[Console]::InputEncoding = $script:Utf8Encoding
[Console]::OutputEncoding = $script:Utf8Encoding
$OutputEncoding = $script:Utf8Encoding

$script:SetupDirectory = $PSScriptRoot
$script:SelectedLanguage = "en"
$script:SystemTempRoot = ""
$script:TempRoot = ""
$commonApplicationData = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)
$script:ManifestPath = Join-Path $commonApplicationData "BluraySubtitle\environment-manifest.json"
$script:Manifest = $null
$script:RegisteredComponents = [ordered]@{}
$script:LatestPythonRelease = $null
$script:SelectedPythonRelease = $null
$script:BuildCacheRoot = ""
$script:NativeToolCacheRoot = Join-Path $commonApplicationData "BluraySubtitle\build-cache\artifacts"
$script:BuildRecipeHash = ""
# Retain the v3 recipe IDs for unchanged build outputs. Update the relevant ID when an artifact recipe changes.
$script:WindowsToolRecipeId = "ABE005A17FD8A3E7BE61BC884AC8EB55BC17BFA19F3A1AB25D2574C8ACEF835E"
$script:WindowsToolPathRecipeId = "7ECAA3E44A008A78519D6A9AE10C2BE6F4F6E50DEE1BC404FBBCC9BF05B6EF8F"
$script:VapourSynthComponentRecipeId = "8E3206EEECB37B7FE3EF3FC7D5723D0F937A6F8D8F51A04E94E87B79D9C192BD"
$script:BuildToolchains = @{
    msvc = @("git", "visual-studio-build-tools", "cmake", "ninja", "nasm")
    msys2 = @("git", "msys2", "msys2-packages")
}
$script:PreparedBuildTools = @{}
$script:DesktopVisualStudioEnterprise = $null
$script:VisualStudioBuildEnvironment = $null

function Select-SetupLanguage {
    Write-Host ""
    Write-Host "Please select a language / 请选择语言："
    Write-Host "  1) English"
    Write-Host "  2) 简体中文"
    Write-Host ""

    while ($true) {
        $choice = Read-Host "Enter 1 or 2 / 请输入 1 或 2"
        switch ($choice.Trim()) {
            "1" { return "en" }
            "2" { return "zh" }
            default {
                Write-Host "Invalid input. Please enter 1 or 2. / 输入无效，请输入 1 或 2。" -ForegroundColor Yellow
            }
        }
    }
}

$script:SelectedLanguage = if ($Language) { $Language } elseif ($Mode -eq "Build") { "en" } else { Select-SetupLanguage }
$script:ProxyAddress = "DIRECT"
$script:RestartRequired = $false
$script:ReleaseCache = [ordered]@{}
$script:BuildJobs = [Math]::Max(1, [Environment]::ProcessorCount)
$script:ToolPaths = [ordered]@{
    PythonRoot = "C:\Program Files\Python314"
    Python = "C:\Program Files\Python314\python.exe"
    PythonScripts = "C:\Program Files\Python314\Scripts"
    GitRoot = "C:\Program Files\Git"
    Git = "C:\Program Files\Git\cmd\git.exe"
    VisualStudioRoot = "C:\Program Files\Microsoft Visual Studio\18\BuildTools"
    VisualStudioInstaller = "C:\Program Files (x86)\Microsoft Visual Studio\Installer"
    CMake = "C:\Program Files\CMake\bin\cmake.exe"
    Ninja = "C:\Software\ninja.exe"
    Nasm = "C:\Software\nasm.exe"
    Msys2Root = "C:\msys64"
    Msys2Bash = "C:\msys64\usr\bin\bash.exe"
}
$script:PythonPackages = @(
    [pscustomobject]@{ Distribution = "pip"; Import = "import pip" },
    [pscustomobject]@{ Distribution = "setuptools"; Import = "import setuptools" },
    [pscustomobject]@{ Distribution = "wheel"; Import = "import wheel" },
    [pscustomobject]@{ Distribution = "Cython"; Import = "import Cython" },
    [pscustomobject]@{ Distribution = "numpy"; Import = "import numpy" },
    [pscustomobject]@{ Distribution = "pycountry"; Import = "import pycountry" },
    [pscustomobject]@{ Distribution = "PyQt6"; Import = "from PyQt6 import QtCore" },
    [pscustomobject]@{ Distribution = "soundfile"; Import = "import soundfile" },
    [pscustomobject]@{ Distribution = "pillow"; Import = "from PIL import Image" },
    [pscustomobject]@{ Distribution = "matplotlib"; Import = "import matplotlib" },
    [pscustomobject]@{ Distribution = "PyInstaller"; Import = "import PyInstaller" },
    [pscustomobject]@{ Distribution = "pefile"; Import = "import pefile" }
)
$script:Msys2Packages = @(
    "base-devel",
    "autoconf",
    "automake",
    "libtool",
    "make",
    "pkgconf",
    "diffutils",
    "patch",
    "tar",
    "unzip",
    "wget",
    "curl",
    "git",
    "mingw-w64-ucrt-x86_64-toolchain",
    "mingw-w64-ucrt-x86_64-cmake",
    "mingw-w64-ucrt-x86_64-ninja",
    "mingw-w64-ucrt-x86_64-nasm",
    "mingw-w64-ucrt-x86_64-yasm",
    "mingw-w64-ucrt-x86_64-meson",
    "mingw-w64-ucrt-x86_64-python",
    "mingw-w64-ucrt-x86_64-python-pip",
    "mingw-w64-ucrt-x86_64-autotools",
    "mingw-w64-ucrt-x86_64-pkgconf",
    "mingw-w64-ucrt-x86_64-libtool",
    "mingw-w64-ucrt-x86_64-freetype",
    "mingw-w64-ucrt-x86_64-fribidi",
    "mingw-w64-ucrt-x86_64-harfbuzz",
    "mingw-w64-ucrt-x86_64-libunibreak",
    "mingw-w64-ucrt-x86_64-libiconv",
    "mingw-w64-ucrt-x86_64-gettext-runtime",
    "mingw-w64-ucrt-x86_64-glib2",
    "mingw-w64-ucrt-x86_64-pcre2",
    "mingw-w64-ucrt-x86_64-graphite2",
    "mingw-w64-ucrt-x86_64-brotli",
    "mingw-w64-ucrt-x86_64-bzip2",
    "mingw-w64-ucrt-x86_64-libpng",
    "mingw-w64-ucrt-x86_64-zlib"
)

$script:FfmpegConfigureOptions = @(
    "--target-os=mingw32",
    "--arch=x86_64",
    "--enable-gpl",
    "--enable-version3",
    "--disable-debug",
    "--disable-doc",
    "--disable-ffplay",
    "--enable-static",
    "--disable-shared",
    "--enable-pic",
    "--disable-autodetect",
    "--enable-schannel",
    "--enable-bzlib",
    "--enable-iconv",
    "--enable-lzma",
    "--enable-zlib",
    "--enable-libdav1d",
    "--enable-libopus",
    "--optflags=-O2",
    "--pkg-config-flags=--static",
    "--extra-ldflags=-static",
    # With autodetection disabled, FFmpeg only probes for iconv in libc.
    "--extra-libs=-liconv"
)

function Get-SetupText {
    param(
        [Parameter(Mandatory = $true)][string]$English,
        [Parameter(Mandatory = $true)][string]$Chinese
    )

    if ($script:SelectedLanguage -eq "zh") {
        return $Chinese
    }
    return $English
}

function Write-SetupInfo {
    param(
        [Parameter(Mandatory = $true)][string]$English,
        [Parameter(Mandatory = $true)][string]$Chinese,
        [object[]]$FormatArgs = @()
    )

    $message = Get-SetupText $English $Chinese
    if ($FormatArgs.Count -gt 0) {
        $message = $message -f $FormatArgs
    }
    Write-Host ("[BluraySubtitle][SETUP] " + $message) -ForegroundColor Cyan
}

function Write-SetupWarning {
    param(
        [Parameter(Mandatory = $true)][string]$English,
        [Parameter(Mandatory = $true)][string]$Chinese
    )

    Write-Warning (Get-SetupText $English $Chinese)
}

function Get-WindowsOperatingSystem {
    if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {
        return Get-CimInstance -ClassName Win32_OperatingSystem
    }
    return Get-WmiObject -Class Win32_OperatingSystem
}

function Get-WindowsProcessor {
    if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) {
        return Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1
    }
    return Get-WmiObject -Class Win32_Processor | Select-Object -First 1
}

function Assert-SupportedWindows {
    $operatingSystem = Get-WindowsOperatingSystem
    $processor = Get-WindowsProcessor
    $caption = [string]$operatingSystem.Caption
    $build = [int]$operatingSystem.BuildNumber
    $productType = [int]$operatingSystem.ProductType
    $processorArchitecture = [int]$processor.Architecture
    $installationType = [string](Get-ItemPropertyValue `
        -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" `
        -Name "InstallationType")

    # Minimum build checks keep known-incompatible legacy systems out without rejecting future Windows releases.
    $isSupportedWindowsClient = $productType -eq 1 -and $build -ge 10240
    $isWindowsServer = $productType -in @(2, 3)
    # "Server" means Desktop Experience; "Server Core" has no desktop shell for the PyQt GUI.
    $isSupportedWindowsServer = `
        $isWindowsServer -and $build -ge 17763 -and `
        $installationType -eq "Server"
    $isAmd64 = [Environment]::Is64BitOperatingSystem -and $processorArchitecture -eq 9

    if ($isWindowsServer -and $installationType -eq "Server Core") {
        throw (Get-SetupText `
            "Windows Server requires the Desktop Experience installation option. Server Core cannot run the BluraySubtitle desktop GUI." `
            "Windows Server 必须安装桌面体验。Server Core 无法运行 BluraySubtitle 桌面 GUI。")
    }
    if (-not $isSupportedWindowsClient -and -not $isSupportedWindowsServer) {
        throw (Get-SetupText `
            "Supported systems are x64 Windows client releases based on Windows 10 or later and Windows Server 2019 or later with Desktop Experience. Detected: $caption (build $build)." `
            "支持 Windows 10 或更高版本的 x64 Windows 客户端，以及带桌面体验的 Windows Server 2019 或更高版本。检测到：$caption（内部版本 $build）。")
    }
    if (-not $isAmd64) {
        throw (Get-SetupText `
            "Only x64 (AMD64) Windows is supported." `
            "仅支持 x64（AMD64）Windows。")
    }
    if (-not [Environment]::Is64BitProcess) {
        throw (Get-SetupText `
            "A 64-bit PowerShell process is required." `
            "必须使用 64 位 PowerShell 进程。")
    }

    $family = $caption.Trim()
    return [pscustomobject]@{
        Family = $family
        Caption = $caption
        Build = $build
        Version = [string]$operatingSystem.Version
        InstallationType = $installationType
        Architecture = "AMD64"
    }
}

function Test-PathIsUnderRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $fullPath.StartsWith($fullRoot + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Initialize-SetupTempRoot {
    $script:SystemTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    do {
        $name = ".tmp" + [IO.Path]::GetRandomFileName().Replace(".", "").Substring(0, 6)
        $candidate = Join-Path $script:SystemTempRoot $name
    } while (Test-Path -LiteralPath $candidate)
    $script:TempRoot = [IO.Directory]::CreateDirectory($candidate).FullName

    if (-not (Test-PathIsUnderRoot $script:TempRoot $script:SystemTempRoot)) {
        throw (Get-SetupText `
            "The setup temporary directory is outside the system temporary directory." `
            "安装临时目录不在系统临时目录内。")
    }
    return $script:TempRoot
}

function Remove-SetupTempRoot {
    if (-not $script:TempRoot -or -not (Test-Path -LiteralPath $script:TempRoot)) {
        return
    }

    $resolvedTemp = [IO.Path]::GetFullPath($script:TempRoot)
    $leaf = Split-Path -Leaf $resolvedTemp
    if (-not (Test-PathIsUnderRoot $resolvedTemp $script:SystemTempRoot) -or
        $leaf -notmatch '^\.tmp[a-z0-9]{6}$') {
        Write-SetupWarning `
            "Refusing to remove an unexpected temporary path: $resolvedTemp" `
            "拒绝删除非预期的临时路径：$resolvedTemp"
        return
    }

    try {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
    catch {
        Write-SetupWarning `
            "Failed to remove the temporary directory: $resolvedTemp" `
            "无法删除临时目录：$resolvedTemp"
    }
}

function Get-SystemProxyDescription {
    $testUri = [Uri]"https://api.github.com/"
    $proxy = [Net.WebRequest]::DefaultWebProxy
    if ($null -eq $proxy) {
        return "DIRECT"
    }

    $proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
    $resolved = $proxy.GetProxy($testUri)
    if ($null -eq $resolved -or $resolved.AbsoluteUri -eq $testUri.AbsoluteUri) {
        return "DIRECT"
    }
    return $resolved.GetLeftPart([UriPartial]::Authority)
}

function New-SetupHttpClient {
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object Net.Http.HttpClientHandler
    $handler.UseProxy = $true
    $handler.Proxy = [Net.WebRequest]::DefaultWebProxy
    if ($null -ne $handler.Proxy) {
        $handler.Proxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials
    }

    $client = New-Object Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd("BluraySubtitle-Windows-Setup/1.0")
    return $client
}

function Invoke-SetupDownload {
    param(
        [Parameter(Mandatory = $true)][Uri]$Uri,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$Sha256 = "",
        [long]$ExpectedSize = 0,
        [ValidateRange(1, 5)][int]$Attempts = 3,
        [Uri]$FallbackUri
    )

    if (-not $script:TempRoot -or -not (Test-PathIsUnderRoot $Destination $script:TempRoot)) {
        throw (Get-SetupText `
            "Downloads may only be written inside the setup temporary directory." `
            "下载文件只能写入安装临时目录。")
    }

    $destinationDirectory = Split-Path -Parent $Destination
    [IO.Directory]::CreateDirectory($destinationDirectory) | Out-Null
    $fileName = [IO.Path]::GetFileName($Destination)
    $githubApiRequest = $Uri.Scheme -eq "https" -and $Uri.Host -eq "api.github.com"
    $githubReleaseAsset = $githubApiRequest -and (
        $Uri.AbsolutePath -match '^/repos/[^/]+/[^/]+/releases/assets/[0-9]+$'
    )
    $releaseDownload = $githubReleaseAsset -or (
        $Uri.Scheme -eq "https" -and $Uri.Host -eq "github.com" -and
        $Uri.AbsolutePath -match '^/[^/]+/[^/]+/releases/(?:latest/)?download/'
    )
    $client = New-SetupHttpClient
    try {
        if ($githubApiRequest -and $Uri.IsDefaultPort -and $script:GitHubApiToken) {
            # HttpClientHandler clears Authorization when following redirects.
            $client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new(
                "Bearer", $script:GitHubApiToken
            )
        }
        if ($githubReleaseAsset) {
            $client.DefaultRequestHeaders.Accept.ParseAdd("application/octet-stream")
            $client.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28")
        }
        $completionOption = [Net.Http.HttpCompletionOption]::ResponseHeadersRead
        for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
            Write-SetupInfo `
                "Downloading $fileName (attempt $attempt/$Attempts): $Uri" `
                "正在下载 $fileName（第 $attempt/$Attempts 次）：$Uri"
            try {
                $response = $client.GetAsync($Uri, $completionOption).GetAwaiter().GetResult()
                if ($null -ne $client.DefaultRequestHeaders.Authorization -and
                    [int]$response.StatusCode -in @(401, 403, 404)) {
                    # A job token may be denied access to an upstream repository.
                    $response.Dispose()
                    $client.DefaultRequestHeaders.Authorization = $null
                    $response = $client.GetAsync($Uri, $completionOption).GetAwaiter().GetResult()
                }
                try {
                    $response.EnsureSuccessStatusCode() | Out-Null
                    $contentType = $response.Content.Headers.ContentType
                    if ($releaseDownload -and $null -ne $contentType -and
                        ($contentType.MediaType -like "*json" -or $contentType.MediaType -eq "text/html")) {
                        throw (Get-SetupText `
                            "GitHub returned metadata or HTML for the release asset $fileName." `
                            "GitHub 为发布附件 $fileName 返回了元数据或网页。")
                    }
                    $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                    try {
                        $outputStream = New-Object IO.FileStream(
                            $Destination,
                            [IO.FileMode]::Create,
                            [IO.FileAccess]::Write,
                            [IO.FileShare]::None
                        )
                        try {
                            $buffer = New-Object byte[] (1MB)
                            $downloadedBytes = 0L
                            $contentLength = [long]$response.Content.Headers.ContentLength
                            $progressTimer = [Diagnostics.Stopwatch]::StartNew()
                            while (($bytesRead = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                                $outputStream.Write($buffer, 0, $bytesRead)
                                $downloadedBytes += $bytesRead
                                if ($contentLength -gt 0 -and $progressTimer.Elapsed.TotalSeconds -ge 10) {
                                    $downloadedMiB = [Math]::Round($downloadedBytes / 1MB, 1)
                                    $totalMiB = [Math]::Round($contentLength / 1MB, 1)
                                    $percent = [Math]::Round(($downloadedBytes * 100.0) / $contentLength, 1)
                                    Write-SetupInfo `
                                        "Downloading ${fileName}: $downloadedMiB/$totalMiB MiB ($percent%)" `
                                        "正在下载 ${fileName}：$downloadedMiB/$totalMiB MiB（$percent%）"
                                    $progressTimer.Restart()
                                }
                            }
                        }
                        finally {
                            $outputStream.Dispose()
                        }
                    }
                    finally {
                        $inputStream.Dispose()
                    }
                }
                finally {
                    $response.Dispose()
                }

                if ($ExpectedSize -gt 0 -and (Get-Item -LiteralPath $Destination).Length -ne $ExpectedSize) {
                    throw (Get-SetupText `
                        "Downloaded size mismatch for $Uri" `
                        "下载文件大小不匹配：$Uri")
                }
                if ($ExpectedSize -gt 0) {
                    Write-SetupInfo `
                        "Downloaded size verification succeeded for $fileName." `
                        "$fileName 的文件大小校验成功。"
                }
                if ($Sha256) {
                    $actualHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
                    if ($actualHash -ne $Sha256) {
                        throw "SHA-256 mismatch for $Uri"
                    }
                    Write-SetupInfo `
                        "SHA-256 verification succeeded for $fileName." `
                        "$fileName 的 SHA-256 校验成功。"
                }
                $sizeMiB = [Math]::Round(
                    (Get-Item -LiteralPath $Destination).Length / 1MB,
                    2
                )
                Write-SetupInfo `
                    "Download completed: $fileName ($sizeMiB MiB)" `
                    "下载完成：$fileName（$sizeMiB MiB）"
                return $Destination
            }
            catch {
                $downloadError = $_.Exception.Message
                if (Test-Path -LiteralPath $Destination) {
                    Remove-Item -LiteralPath $Destination -Force
                }
                if ($attempt -eq $Attempts) {
                    if ($githubReleaseAsset -and $null -ne $FallbackUri) {
                        Write-SetupWarning `
                            "GitHub API download failed for $fileName. Trying the official release link." `
                            "GitHub API 下载 $fileName 失败，改用官方发布链接。"
                        return (Invoke-SetupDownload -Uri $FallbackUri -Destination $Destination `
                            -Sha256 $Sha256 -ExpectedSize $ExpectedSize -Attempts $Attempts)
                    }
                    throw
                }
                Write-SetupWarning `
                    "Download attempt $attempt for $fileName failed: $downloadError. Retrying." `
                    "$fileName 第 $attempt 次下载失败：$downloadError。准备重试。"
                Start-Sleep -Seconds ([Math]::Min(2 * $attempt, 6))
            }
        }
    }
    finally {
        $client.Dispose()
    }
}
function Invoke-SetupInstaller {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int[]]$AcceptedExitCodes = @(0, 3010),
        [string]$NsisInstallDirectory = ""
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw (Get-SetupText "Installer not found: $FilePath" "未找到安装程序：$FilePath")
    }

    $installerName = [IO.Path]::GetFileName($FilePath)
    Write-SetupInfo `
        "Running installer: $installerName" `
        "正在运行安装程序：$installerName"
    $argumentLine = ($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join " "
    if ($NsisInstallDirectory) {
        # NSIS requires /D to be last and unquoted, including paths with spaces.
        $argumentLine += " /D=$NsisInstallDirectory"
    }
    $process = Start-Process -FilePath $FilePath -ArgumentList $argumentLine -Wait -PassThru
    if ($AcceptedExitCodes -notcontains $process.ExitCode) {
        throw (Get-SetupText `
            "Installer failed with exit code $($process.ExitCode): $FilePath" `
            "安装程序执行失败，退出码 $($process.ExitCode)：$FilePath")
    }
    Write-SetupInfo `
        "Installer completed successfully: $installerName (exit code $($process.ExitCode))" `
        "安装程序执行完成：$installerName（退出码 $($process.ExitCode)）"
    if ($process.ExitCode -eq 3010) {
        $script:RestartRequired = $true
        Write-SetupWarning `
            "A restart is required after the current setup run." `
            "本次安装结束后需要重新启动电脑。"
    }
}
function Invoke-SetupCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int[]]$AcceptedExitCodes = @(0)
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw (Get-SetupText "Executable not found: $FilePath" "未找到可执行文件：$FilePath")
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $textOutput = ($output | ForEach-Object { [string]$_ }) -join "`n"
    if ($AcceptedExitCodes -notcontains $exitCode) {
        throw (Get-SetupText `
            "Command failed with exit code ${exitCode}: $FilePath $($Arguments -join ' ')`n$textOutput" `
            "命令执行失败，退出码 ${exitCode}：$FilePath $($Arguments -join ' ')`n$textOutput")
    }
    return $textOutput.Trim()
}

function Assert-ValidAuthenticodeSignature {
    param([Parameter(Mandatory = $true)][string]$Path)

    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid) {
        throw (Get-SetupText `
            "The downloaded file does not have a valid Authenticode signature: $Path ($($signature.Status))" `
            "下载文件的 Authenticode 签名无效：$Path（$($signature.Status)）")
    }
}

function Expand-SetupZip {
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-PathIsUnderRoot $Destination $script:TempRoot)) {
        throw (Get-SetupText `
            "Archives may only be extracted inside the setup temporary directory." `
            "压缩包只能解压到安装临时目录。")
    }
    $archiveName = [IO.Path]::GetFileName($Archive)
    Write-SetupInfo "Extracting archive: $archiveName" "正在解压压缩包：$archiveName"
    [IO.Directory]::CreateDirectory($Destination) | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
    Write-SetupInfo "Archive extraction completed: $archiveName" "压缩包解压完成：$archiveName"
}

function Expand-SetupArchiveWithSevenZip {
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-PathIsUnderRoot $Destination $script:TempRoot)) {
        throw (Get-SetupText `
            "Archives may only be extracted inside the setup temporary directory." `
            "压缩包只能解压到安装临时目录。")
    }
    if (-not (Test-Path -LiteralPath $script:ToolPaths.SevenZip -PathType Leaf)) {
        throw (Get-SetupText "7-Zip is required to extract this archive." "解压此压缩包需要 7-Zip。")
    }
    $archiveName = [IO.Path]::GetFileName($Archive)
    Write-SetupInfo "Extracting archive: $archiveName" "正在解压压缩包：$archiveName"
    [IO.Directory]::CreateDirectory($Destination) | Out-Null
    Invoke-SetupCommand `
        -FilePath $script:ToolPaths.SevenZip `
        -Arguments @("x", $Archive, "-o$Destination", "-y", "-bso0", "-bsp0") | Out-Null
    Write-SetupInfo "Archive extraction completed: $archiveName" "压缩包解压完成：$archiveName"
}
function Get-SetupTextFromUri {
    param(
        [Parameter(Mandatory = $true)][Uri]$Uri,
        [Parameter(Mandatory = $true)][string]$CacheName
    )

    $cachePath = Join-Path $script:TempRoot $CacheName
    if (-not (Test-Path -LiteralPath $cachePath -PathType Leaf)) {
        Invoke-SetupDownload -Uri $Uri -Destination $cachePath | Out-Null
    }
    return [IO.File]::ReadAllText($cachePath)
}

function Get-SetupJsonFromUri {
    param(
        [Parameter(Mandatory = $true)][Uri]$Uri,
        [Parameter(Mandatory = $true)][string]$CacheName
    )

    return (Get-SetupTextFromUri -Uri $Uri -CacheName $CacheName | ConvertFrom-Json)
}

function Get-GitHubWebRelease {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $safeName = $Repository.Replace('/', '-')
    $releasePage = Get-SetupTextFromUri `
        -Uri ([Uri]"https://github.com/$Repository/releases/latest") `
        -CacheName "$safeName-latest.html"
    $fragment = [regex]::Match($releasePage,
        '(?i)<include-fragment\b[^>]*\bsrc="(?:https://github\.com)?(?<path>/(?<repo>[^/"]+/[^/"]+)/releases/expanded_assets/(?<tag>[^"?#]+))"')
    if (-not $fragment.Success) {
        throw (Get-SetupText `
            "Could not find the latest release assets on the GitHub page for $Repository." `
            "无法在 $Repository 的 GitHub 页面找到最新版附件。")
    }

    $assetsPath = [Net.WebUtility]::HtmlDecode($fragment.Groups["path"].Value)
    $assetsPage = Get-SetupTextFromUri -Uri ([Uri]("https://github.com" + $assetsPath)) -CacheName "$safeName-assets.html"
    $linkPattern = '(?i)\bhref="(?:https://github\.com)?(?<path>/' +
        [regex]::Escape($fragment.Groups["repo"].Value) + '/releases/download/[^"]+)"'
    $assets = @(
        foreach ($row in [regex]::Matches($assetsPage, '(?is)<li\b[^>]*>.*?</li>')) {
            $link = [regex]::Match($row.Value, $linkPattern)
            if (-not $link.Success) {
                continue
            }
            $path = [Net.WebUtility]::HtmlDecode($link.Groups["path"].Value)
            $uri = [Uri]("https://github.com" + $path)
            [pscustomobject]@{
                name = [Uri]::UnescapeDataString($uri.Segments[-1])
                url = $uri.AbsoluteUri
                browser_download_url = $uri.AbsoluteUri
                digest = [regex]::Match($row.Value, '(?i)\bsha256:[0-9a-f]{64}\b').Value
                size = 0L
                updated_at = [regex]::Match($row.Value, '\bdatetime="([^"]+)"').Groups[1].Value
            }
        }
    )
    return [pscustomobject]@{
        tag_name = [Uri]::UnescapeDataString([Net.WebUtility]::HtmlDecode($fragment.Groups["tag"].Value))
        assets = $assets
        body = [Net.WebUtility]::HtmlDecode([regex]::Replace($releasePage, '(?s)<[^>]+>', ' '))
    }
}

function Get-GitHubLatestReleaseAsset {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$AssetPattern
    )

    $cacheKey = "github:${Repository}:$AssetPattern"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $safeName = $Repository.Replace('/', '-')
    try {
        $release = Get-SetupJsonFromUri `
            -Uri ([Uri]"https://api.github.com/repos/$Repository/releases/latest") `
            -CacheName "$safeName-latest.json"
    }
    catch {
        Write-SetupWarning `
            "GitHub API release lookup failed for $Repository. Trying the release page." `
            "GitHub API 查询 $Repository 的发布信息失败，改用官方发布页面。"
        $release = Get-GitHubWebRelease -Repository $Repository
    }
    $assets = @($release.assets | Where-Object { [string]$_.name -match $AssetPattern })
    if ($assets.Count -ne 1) {
        throw (Get-SetupText `
            "Expected one release asset for $Repository matching $AssetPattern; found $($assets.Count)." `
            "$Repository 中应有一个匹配 $AssetPattern 的发布文件，实际找到 $($assets.Count) 个。")
    }

    $asset = $assets[0]
    $sha256 = ""
    $digest = [string]$asset.digest
    if ($digest -match '^sha256:([0-9a-fA-F]{64})$') {
        $sha256 = $Matches[1]
    }
    $version = ([string]$release.tag_name).TrimStart('v', 'V')
    $result = [pscustomobject]@{
        Version = $version
        Name = [string]$asset.name
        Uri = [Uri]$asset.url
        DirectUri = [Uri]$asset.browser_download_url
        Sha256 = $sha256
        Size = [long]$asset.size
        AssetUpdatedAtUtc = [string]$asset.updated_at
        ReleaseBody = [string]$release.body
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-GitHubTagsFromGit {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $refs = Invoke-SetupCommand -FilePath $script:ToolPaths.Git `
        -Arguments @("ls-remote", "--refs", "--tags", "https://github.com/$Repository.git")
    foreach ($line in $refs -split '\r?\n') {
        if ($line -match '^[0-9a-f]{40}\s+refs/tags/(.+)$') {
            $Matches[1]
        }
    }
}

function Get-GitHubLatestTaggedSource {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$TagPattern,
        [Parameter(Mandatory = $true)][string]$ArchiveBaseName
    )

    $cacheKey = "github-tagged-source:${Repository}:$TagPattern"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $safeName = $Repository.Replace('/', '-')
    try {
        $tags = @(Get-SetupJsonFromUri `
            -Uri ([Uri]"https://api.github.com/repos/$Repository/tags?per_page=100") `
            -CacheName "$safeName-tags.json")
        $tagNames = @($tags | ForEach-Object { [string]$_.name })
    }
    catch {
        $tagNames = @(Get-GitHubTagsFromGit -Repository $Repository)
    }
    $candidates = @(
        foreach ($tagName in $tagNames) {
            $match = [regex]::Match($tagName, $TagPattern)
            if ($match.Success -and $match.Groups["version"].Success) {
                [pscustomobject]@{
                    Tag = $tagName
                    Version = $match.Groups["version"].Value
                }
            }
        }
    )
    if ($candidates.Count -eq 0) {
        throw (Get-SetupText `
            "No stable source tag was found for $Repository." `
            "未找到 $Repository 的稳定源码标签。")
    }

    $selected = $candidates |
        Sort-Object { ConvertTo-ComparableVersion $_.Version } -Descending |
        Select-Object -First 1
    $escapedTag = [Uri]::EscapeDataString($selected.Tag)
    $result = [pscustomobject]@{
        Version = $selected.Version
        Tag = $selected.Tag
        Name = "$ArchiveBaseName-$($selected.Version).zip"
        Uri = [Uri]"https://codeload.github.com/$Repository/zip/refs/tags/$escapedTag"
        Sha256 = ""
        Size = 0L
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-SvtAv1SourceRelease {
    $cacheKey = "gitlab:svt-av1:latest-stable-source"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $releases = @(Get-SetupJsonFromUri `
        -Uri ([Uri]"https://gitlab.com/api/v4/projects/AOMediaCodec%2FSVT-AV1/releases?per_page=100") `
        -CacheName "svt-av1-releases.json")
    $candidates = @(
        foreach ($release in $releases) {
            $tag = [string]$release.tag_name
            $match = [regex]::Match($tag, '^v(?<version>[0-9]+(?:\.[0-9]+){1,3})$')
            if ($match.Success) {
                [pscustomobject]@{
                    Tag = $tag
                    Version = $match.Groups["version"].Value
                }
            }
        }
    )
    if ($candidates.Count -eq 0) {
        throw (Get-SetupText `
            "No stable SVT-AV1 release was found." `
            "未找到 SVT-AV1 稳定版本。")
    }

    $selected = $candidates |
        Sort-Object { ConvertTo-ComparableVersion $_.Version } -Descending |
        Select-Object -First 1
    $escapedTag = [Uri]::EscapeDataString($selected.Tag)
    $result = [pscustomobject]@{
        Version = $selected.Version
        Tag = $selected.Tag
        Name = "SVT-AV1-$($selected.Version).zip"
        Uri = [Uri]"https://gitlab.com/AOMediaCodec/SVT-AV1/-/archive/$escapedTag/SVT-AV1-$escapedTag.zip"
        Sha256 = ""
        Size = 0L
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Invoke-SetupBuildCommand {
    param(
        [Parameter(Mandatory = $true)][string]$DisplayName,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int[]]$AcceptedExitCodes = @(0)
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw (Get-SetupText "Build executable not found: $FilePath" "未找到编译程序：$FilePath")
    }
    Write-SetupInfo "Running build step: $DisplayName" "正在执行编译步骤：$DisplayName"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host ([string]$_) }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($AcceptedExitCodes -notcontains $exitCode) {
        throw (Get-SetupText `
            "Build step failed with exit code ${exitCode}: $DisplayName" `
            "编译步骤执行失败，退出码 ${exitCode}：$DisplayName")
    }
    $seconds = [Math]::Round($timer.Elapsed.TotalSeconds, 1)
    Write-SetupInfo "Build step completed in $seconds s: $DisplayName" "编译步骤耗时 $seconds 秒：$DisplayName"
}

function ConvertTo-Msys2Path {
    param([Parameter(Mandatory = $true)][string]$Path)

    $cygpath = Join-Path $script:ToolPaths.Msys2Root "usr\bin\cygpath.exe"
    return Invoke-SetupCommand -FilePath $cygpath -Arguments @("-u", $Path)
}

function Write-SetupTempScript {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $path = Join-Path $script:TempRoot $Name
    if (-not (Test-PathIsUnderRoot $path $script:TempRoot)) {
        throw "Generated build scripts must remain inside the setup temporary directory."
    }
    $normalized = $Content.Replace("`r`n", "`n")
    [IO.File]::WriteAllText($path, $normalized, (New-Object Text.UTF8Encoding($false)))
    return $path
}

function Set-SourceTextReplacement {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$OldText,
        [Parameter(Mandatory = $true)][string]$NewText,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $source = [IO.File]::ReadAllText($Path)
    $oldNormalized = $OldText.Replace("`r`n", "`n")
    $newNormalized = $NewText.Replace("`r`n", "`n")
    $first = $source.IndexOf($oldNormalized, [StringComparison]::Ordinal)
    $last = $source.LastIndexOf($oldNormalized, [StringComparison]::Ordinal)
    if ($first -ge 0 -and $first -eq $last) {
        [IO.File]::WriteAllText(
            $Path,
            $source.Replace($oldNormalized, $newNormalized),
            (New-Object Text.UTF8Encoding($false))
        )
        return
    }
    if ($source.Contains($newNormalized)) {
        return
    }
    throw (Get-SetupText `
        "Unable to apply source update: $Description" `
        "无法应用源码修改：$Description")
}
function Get-PythonStableVersions {
    $cacheKey = "python-windows-stable-versions"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return @($script:ReleaseCache[$cacheKey])
    }

    $releases = @(Get-SetupJsonFromUri `
        -Uri ([Uri]"https://www.python.org/api/v2/downloads/release/?is_published=true&pre_release=false") `
        -CacheName "python-stable-releases.json")
    $versions = @(
        $releases |
            ForEach-Object {
                $nameMatch = [regex]::Match(
                    [string]$_.name,
                    '^Python (3\.[0-9]+\.[0-9]+)$',
                    'IgnoreCase'
                )
                if ($nameMatch.Success) {
                    $nameMatch.Groups[1].Value
                }
            } |
            Sort-Object -Unique |
            Sort-Object { ConvertTo-ComparableVersion $_ } -Descending
    )
    if ($versions.Count -eq 0) {
        throw (Get-SetupText `
            "Unable to determine the latest stable Python release." `
            "无法确定最新的 Python 稳定版本。")
    }

    $script:ReleaseCache[$cacheKey] = $versions
    return $versions
}

function Get-PythonWindowsRelease {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Versions
    )

    foreach ($version in $Versions) {
        $name = "python-$version-amd64.exe"
        $releaseUri = [Uri]"https://www.python.org/ftp/python/$version/"
        $files = Get-SetupTextFromUri -Uri $releaseUri -CacheName "python-$version-files.html"
        # Security-only releases can omit Windows binaries.
        if (-not $files.Contains("href=`"$name`"")) {
            continue
        }
        return [pscustomobject]@{
            Version = $version
            Name = $name
            Uri = [Uri]::new($releaseUri, $name)
            Sha256 = ""
        }
    }
    throw (Get-SetupText `
        "No matching Python Windows package was found." `
        "未找到匹配的 Python Windows 发行包。")
}

function Get-LatestPythonRelease {
    return Get-PythonWindowsRelease -Versions @(Get-PythonStableVersions)
}

function Get-PreviousPythonRelease {
    param([Parameter(Mandatory = $true)][string]$Version)

    $currentVersion = ConvertTo-ComparableVersion $Version
    if ($currentVersion.Minor -le 0) {
        throw (Get-SetupText `
            "No previous Python minor version is available for fallback." `
            "没有可用于回退的 Python 次版本。")
    }
    $targetMinor = $currentVersion.Minor - 1
    $fallbackVersions = @(
        Get-PythonStableVersions |
            Where-Object {
                $candidate = ConvertTo-ComparableVersion $_
                $candidate.Major -eq $currentVersion.Major -and
                $candidate.Minor -eq $targetMinor
            }
    )
    if ($fallbackVersions.Count -eq 0) {
        throw (Get-SetupText `
            "Unable to determine the previous stable Python minor release." `
            "无法确定上一个 Python 稳定次版本。")
    }
    return Get-PythonWindowsRelease -Versions $fallbackVersions
}

function Set-PythonToolPathsForVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [switch]$RequireInstalled
    )

    $parsedVersion = ConvertTo-ComparableVersion $Version
    $directoryName = "Python{0}{1}" -f $parsedVersion.Major, $parsedVersion.Minor
    $root = Join-Path "C:\Program Files" $directoryName
    $python = Join-Path $root "python.exe"
    $installation = Get-DetectedPythonInstallation -PreferredExecutable $python -ExpectedVersion $Version
    if ($null -ne $installation) {
        if ($python -ne $installation.Executable) {
            Write-SetupInfo `
                "Using Python $Version at $($installation.Executable)." `
                "使用位于 $($installation.Executable) 的 Python $Version。"
        }
        $root = $installation.Root
        $python = $installation.Executable
    }
    elseif ($RequireInstalled) {
        throw (Get-SetupText `
            "Could not locate Python $Version (x64) after installation. Expected $python or a registered installation of that version." `
            "安装后未找到 Python $Version（x64）。预期路径为 $python，或使用该版本已注册的安装位置。")
    }

    $script:ToolPaths.PythonRoot = $root
    $script:ToolPaths.Python = $python
    $script:ToolPaths.PythonScripts = Join-Path $root "Scripts"
}

function Initialize-PythonRuntimeSelection {
    $latestRelease = Get-LatestPythonRelease
    $selectedRelease = $latestRelease
    $state = $script:Manifest.components["python-selection"]
    if ($null -ne $state -and [string]$state.status -eq "fallback") {
        $attemptedProperty = $state.PSObject.Properties["attempted_version"]
        if (
            $null -ne $attemptedProperty -and
            [string]$attemptedProperty.Value -eq $latestRelease.Version -and
            [string]$state.version
        ) {
            $selectedRelease = Get-PythonWindowsRelease -Versions @([string]$state.version)
            Write-SetupInfo `
                "Reusing Python $($selectedRelease.Version) because Python $($latestRelease.Version) previously failed dependency installation." `
                "继续使用 Python $($selectedRelease.Version)，因为 Python $($latestRelease.Version) 之前未能完成依赖安装。"
        }
    }

    $script:LatestPythonRelease = $latestRelease
    $script:SelectedPythonRelease = $selectedRelease
    Set-PythonToolPathsForVersion $selectedRelease.Version
}

function Set-PythonFallbackSelection {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$AttemptedVersion
    )

    $script:SelectedPythonRelease = $Release
    Set-PythonToolPathsForVersion $Release.Version
    $script:Manifest.components["python-selection"] = [ordered]@{
        version = $Release.Version
        status = "fallback"
        attempted_version = $AttemptedVersion
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    Save-SetupManifest
}

function Get-LatestNasmRelease {
    $cacheKey = "nasm-windows-latest"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $html = Get-SetupTextFromUri `
        -Uri ([Uri]"https://www.nasm.us/pub/nasm/releasebuilds/") `
        -CacheName "nasm-release-index.html"
    $versions = @(
        [regex]::Matches($html, 'href="([0-9]+\.[0-9]+(?:\.[0-9]+)?)/"', 'IgnoreCase') |
            ForEach-Object { $_.Groups[1].Value } |
            Sort-Object -Unique
    )
    if ($versions.Count -eq 0) {
        throw (Get-SetupText "No stable NASM release was found." "未找到 NASM 稳定版本。")
    }
    $version = $versions |
        Sort-Object { ConvertTo-ComparableVersion $_ } -Descending |
        Select-Object -First 1
    $result = [pscustomobject]@{
        Version = $version
        Name = "nasm-$version-win64.zip"
        Uri = [Uri]"https://www.nasm.us/pub/nasm/releasebuilds/$version/win64/nasm-$version-win64.zip"
        Sha256 = ""
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-LatestVisualStudioRelease {
    $cacheKey = "visual-studio-stable"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $channel = Get-SetupJsonFromUri `
        -Uri ([Uri]"https://aka.ms/vs/stable/channel") `
        -CacheName "visual-studio-stable-channel.json"
    $version = [string]$channel.info.buildVersion
    if (-not $version) {
        $manifest = $channel.channelItems |
            Where-Object { [string]$_.id -eq "Microsoft.VisualStudio.Manifests.VisualStudio" } |
            Select-Object -First 1
        $version = [string]$manifest.version
    }
    if (-not $version) {
        throw (Get-SetupText `
            "Unable to determine the latest Visual Studio Build Tools version." `
            "无法确定最新的 Visual Studio Build Tools 版本。")
    }

    $result = [pscustomobject]@{
        Version = $version
        Name = "vs_buildtools.exe"
        Uri = [Uri]"https://aka.ms/vs/stable/vs_buildtools.exe"
        Sha256 = ""
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-LatestPythonPackageVersion {
    param([Parameter(Mandatory = $true)][string]$Distribution)

    $python = Get-ActivePythonExecutable
    $cacheKey = "python-package:${python}:$Distribution"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return [string]$script:ReleaseCache[$cacheKey]
    }
    $arguments = @(
        "-m", "pip", "index", "versions", $Distribution,
        "--json",
        "--only-binary=:all:",
        "--disable-pip-version-check"
    )
    if ($script:ProxyAddress -ne "DIRECT") {
        $arguments += @("--proxy", $script:ProxyAddress)
    }
    $metadata = Invoke-SetupCommand -FilePath $python -Arguments $arguments | ConvertFrom-Json
    $version = [string]$metadata.latest
    if (-not $version) {
        throw ((Get-SetupText `
            "Unable to determine the latest compatible version for Python package {0}." `
            "无法确定 Python 包 {0} 的最新兼容版本。") -f $Distribution)
    }
    $script:ReleaseCache[$cacheKey] = $version
    return $version
}

function ConvertTo-ComparableVersion {
    param([Parameter(Mandatory = $true)][string]$VersionText)

    $match = [regex]::Match($VersionText, '\d+(?:\.\d+){0,3}')
    if (-not $match.Success) {
        throw "Unable to parse version: $VersionText"
    }

    $parts = @($match.Value.Split('.') | ForEach-Object { [int]$_ })
    while ($parts.Count -lt 4) {
        $parts += 0
    }
    return New-Object Version($parts[0], $parts[1], $parts[2], $parts[3])
}

function Compare-SetupVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    $leftVersion = ConvertTo-ComparableVersion $Left
    $rightVersion = ConvertTo-ComparableVersion $Right
    return $leftVersion.CompareTo($rightVersion)
}

function Register-SetupComponent {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EnglishName,
        [Parameter(Mandatory = $true)][string]$ChineseName,
        [Parameter(Mandatory = $true)][scriptblock]$GetInstalledVersion,
        [Parameter(Mandatory = $true)][scriptblock]$GetAvailableVersion,
        [Parameter(Mandatory = $true)][scriptblock]$Install,
        [Parameter(Mandatory = $true)][scriptblock]$Verify,
        [switch]$AlwaysRun,
        [switch]$ReuseInstalled,
        [string]$BuildToolchain
    )

    if ($script:RegisteredComponents.Contains($Name)) {
        throw "Duplicate setup component: $Name"
    }
    $script:RegisteredComponents[$Name] = [pscustomobject]@{
        Name = $Name
        EnglishName = $EnglishName
        ChineseName = $ChineseName
        GetInstalledVersion = $GetInstalledVersion
        GetAvailableVersion = $GetAvailableVersion
        Install = $Install
        Verify = $Verify
        AlwaysRun = [bool]$AlwaysRun
        ReuseInstalled = [bool]$ReuseInstalled
        BuildToolchain = $BuildToolchain
    }
}

function Initialize-SetupManifest {
    $components = [ordered]@{}
    if (Test-Path -LiteralPath $script:ManifestPath -PathType Leaf) {
        try {
            $loaded = Get-Content -Raw -Encoding UTF8 -LiteralPath $script:ManifestPath | ConvertFrom-Json
            if ($loaded.components) {
                foreach ($property in $loaded.components.PSObject.Properties) {
                    $components[$property.Name] = $property.Value
                }
            }
        }
        catch {
            Write-SetupWarning `
                "The existing installation manifest is invalid and will be rebuilt." `
                "现有安装清单无效，将重新创建。"
        }
    }

    $script:Manifest = [ordered]@{
        schema_version = 1
        updated_at_utc = [DateTime]::UtcNow.ToString("o")
        system = [ordered]@{}
        components = $components
    }
}

function Save-SetupManifest {

    if (-not $script:TempRoot) {
        throw "The temporary directory is not initialized."
    }

    $manifestDirectory = Split-Path -Parent $script:ManifestPath
    [IO.Directory]::CreateDirectory($manifestDirectory) | Out-Null
    $stagedManifest = Join-Path $script:TempRoot "environment-manifest.json"
    $json = $script:Manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($stagedManifest, $json, (New-Object Text.UTF8Encoding($false)))
    [IO.File]::Copy($stagedManifest, $script:ManifestPath, $true)
}

function Update-ManifestComponent {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$Status
    )

    $script:Manifest.components[$Name] = [ordered]@{
        version = $Version
        status = $Status
        verified_at_utc = [DateTime]::UtcNow.ToString("o")
    }
}

function Get-BuildFingerprint {
    param([string[]]$Inputs)

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes(($Inputs -join "`n"))
        return [BitConverter]::ToString($sha256.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
}

function Get-ComponentBuildCache {
    param([string]$Name)

    if (-not $script:BuildCacheRoot) {
        return $null
    }

    # The cache must be usable before querying releases or preparing a toolchain.
    $inputs = @($script:BuildRecipeHash, $Name)
    switch ($Name) {
        "7zip" {
            $directory = Split-Path -Parent $script:ToolPaths.SevenZip
            $files = @($script:ToolPaths.SevenZip, (Join-Path $directory "7z.dll"), (Join-Path $directory "License.txt"))
        }
        "ffmpeg" {
            $files = @($script:ToolPaths.Ffmpeg, $script:ToolPaths.Ffprobe, $script:ToolPaths.FfmpegNotices)
            $inputs += $script:FfmpegConfigureOptions
        }
        "flac" { $files = @($script:ToolPaths.Flac, $script:ToolPaths.FlacLibrary) }
        "tsmuxer" { $files = @($script:ToolPaths.TsMuxer) }
        "dovi-tool" { $files = @($script:ToolPaths.DoviTool) }
        "hdr10plus-tool" { $files = @($script:ToolPaths.Hdr10PlusTool) }
        "x264" { $files = @($script:ToolPaths.X264, $script:ToolPaths.X264Version) }
        "x265" { $files = @($script:ToolPaths.X265, $script:ToolPaths.X265Version) }
        "svt-av1" { $files = @($script:ToolPaths.SvtAv1) }
        "fdkaac" { $files = @($script:ToolPaths.FdkAac) }
        "libass" { $files = @($script:ToolPaths.Libass, $script:ToolPaths.LibassVersion) }
        "vapoursynth-classic" {
            $files = @(Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-build.json")
            $inputs += @(
                (Get-FileHash -LiteralPath (Join-Path $script:SetupDirectory "tools\build_vapoursynth_windows.py")).Hash
                (Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments @(
                    "-c", "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))"
                ))
            )
        }
        default { return $null }
    }

    return [pscustomobject]@{
        Name = $Name
        Archive = Join-Path $script:BuildCacheRoot "$Name.zip"
        Key = Get-BuildFingerprint $inputs
        Files = $files
        Artifacts = Join-Path $script:TempRoot "artifacts-$Name"
        Restored = Join-Path $script:TempRoot "restored-$Name"
    }
}

function Invoke-BuildArtifactCache {
    param([string]$Operation, [string]$Archive, [string]$Key, [string]$Directory)

    $helper = Join-Path $script:SetupDirectory "tools\windows_build_cache.py"
    return Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments @(
        $helper, $Operation, $Archive, $Key, $Directory
    )
}

function Restore-ComponentBuildCache {
    param($Cache)

    if ((Invoke-BuildArtifactCache "restore" $Cache.Archive $Cache.Key $Cache.Restored) -ne "hit") {
        return $false
    }
    if ($Cache.Name -eq "vapoursynth-classic") {
        Install-VapourSynthClassic -Artifacts $Cache.Restored
        return $true
    }
    foreach ($file in $Cache.Files) {
        $cachedFile = Join-Path $Cache.Restored ([IO.Path]::GetFileName($file))
        if (-not (Test-Path -LiteralPath $cachedFile -PathType Leaf)) {
            return $false
        }
    }
    foreach ($file in $Cache.Files) {
        $cachedFile = Join-Path $Cache.Restored ([IO.Path]::GetFileName($file))
        Install-ConfiguredFile -Source $cachedFile -Destination $file
    }
    return $true
}

function Save-ComponentBuildCache {
    param($Cache)

    [IO.Directory]::CreateDirectory($Cache.Artifacts) | Out-Null
    foreach ($file in $Cache.Files) {
        Copy-Item -LiteralPath $file -Destination $Cache.Artifacts -Force
    }
    Invoke-BuildArtifactCache "save" $Cache.Archive $Cache.Key $Cache.Artifacts | Out-Null
}

function Initialize-SetupBuildToolchain {
    param([string]$Name)

    if (-not $script:BuildCacheRoot -or -not $Name) {
        return
    }
    foreach ($tool in $script:BuildToolchains[$Name]) {
        if (-not $script:PreparedBuildTools.ContainsKey($tool)) {
            Invoke-SetupComponent $script:RegisteredComponents[$tool]
            $script:PreparedBuildTools[$tool] = $true
        }
    }
}

function Invoke-SetupComponent {
    param([Parameter(Mandatory = $true)]$Component)

    $displayName = Get-SetupText $Component.EnglishName $Component.ChineseName
    Write-SetupInfo "Checking $displayName" "正在检查 $displayName"

    if ($Mode -eq "Build" -and $Component.Name -in @("git", "cmake", "ninja", "nasm") -and
        -not (Test-Path -LiteralPath $script:ToolPaths[$Component.Name] -PathType Leaf)) {
        $command = Get-Command "$($Component.Name).exe" -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($command) {
            $script:ToolPaths[$Component.Name] = $command.Source
        }
    }

    $cache = Get-ComponentBuildCache $Component.Name
    $restored = $false
    $installedVersion = ""
    if ($null -ne $cache) {
        try {
            $restored = Restore-ComponentBuildCache $cache
            if ($restored) {
                $installedVersion = [string](& $Component.GetInstalledVersion)
            }
        }
        catch {
            $restored = $true
        }
        if ($restored -and -not $installedVersion) {
            Write-SetupWarning `
                "The cached $displayName did not pass verification. Installing it again." `
                "缓存中的 $displayName 未通过验证，将重新安装。"
        }
    }

    if (-not $restored) {
        $installedVersion = [string](& $Component.GetInstalledVersion)
    }
    if ($installedVersion) {
        Write-SetupInfo `
            "$displayName detected; installed version/status: $installedVersion" `
            "已检测到 $displayName；当前版本/状态：$installedVersion"
    }
    else {
        Write-SetupInfo `
            "$displayName is not installed or not configured." `
            "$displayName 未安装或尚未配置。"
    }

    if ($Component.ReuseInstalled -and $installedVersion) {
        if (-not [bool](& $Component.Verify)) {
            throw (Get-SetupText `
                "The existing $displayName did not pass build verification." `
                "现有 $displayName 未通过构建验证。")
        }
        Update-ManifestComponent $Component.Name $installedVersion "satisfied"
        Write-SetupInfo `
            "Reusing $displayName $installedVersion for the build." `
            "构建将复用 $displayName $installedVersion。"
        return
    }

    Write-SetupInfo `
        "Checking the target version/status for $displayName." `
        "正在查询 $displayName 的目标版本/状态。"
    $availableVersion = [string](& $Component.GetAvailableVersion)
    if ($null -ne $cache -and -not $availableVersion) {
        throw (Get-SetupText `
            "Unable to determine the upstream version for $displayName." `
            "无法确定 $displayName 的上游版本。")
    }
    Write-SetupInfo `
        "$displayName target version/status: $availableVersion" `
        "$displayName 目标版本/状态：$availableVersion"

    $needsInstall = $Component.AlwaysRun -or -not $installedVersion
    if (-not $needsInstall -and $availableVersion) {
        try {
            if ((Compare-SetupVersion $installedVersion $availableVersion) -lt 0) {
                $needsInstall = $true
                Write-SetupInfo `
                    "$displayName requires an upgrade: $installedVersion -> $availableVersion" `
                    "$displayName 需要升级：$installedVersion -> $availableVersion"
            }
        }
        catch {
            $needsInstall = $true
            Write-SetupInfo `
                "$displayName version comparison was inconclusive; installation will repair the component." `
                "$displayName 版本比较无法确定，将通过安装进行修复。"
        }
    }
    if (-not $needsInstall -and -not [bool](& $Component.Verify)) {
        $needsInstall = $true
        Write-SetupInfo `
            "$displayName did not pass verification and will be repaired." `
            "$displayName 未通过验证，将进行修复。"
    }

    if ($needsInstall) {
        Initialize-SetupBuildToolchain $Component.BuildToolchain
        Write-SetupInfo `
            "Starting installation or configuration of $displayName $availableVersion." `
            "开始安装或配置 $displayName $availableVersion。"
        & $Component.Install $availableVersion
        Write-SetupInfo `
            "Verifying $displayName after installation." `
            "正在验证安装后的 $displayName。"
        if (-not [bool](& $Component.Verify)) {
            throw (Get-SetupText `
                "$displayName verification failed after installation." `
                "$displayName 安装后验证失败。")
        }
        $installedVersion = [string](& $Component.GetInstalledVersion)
        if (-not $installedVersion) {
            throw ((Get-SetupText `
                "{0} did not report a satisfied version/status after installation." `
                "{0} 安装后未报告满足要求的版本/状态。") -f $displayName)
        }
        if ($null -ne $cache) {
            if ((Compare-SetupVersion $installedVersion $availableVersion) -lt 0) {
                throw (Get-SetupText `
                    "$displayName still reports version $installedVersion after installing $availableVersion." `
                    "$displayName 安装 $availableVersion 后仍报告版本 $installedVersion。")
            }
            Save-ComponentBuildCache $cache
        }
        Write-SetupInfo `
            "$displayName verification succeeded." `
            "$displayName 验证成功。"
        Update-ManifestComponent $Component.Name $installedVersion "installed"
        Write-SetupInfo `
            "$displayName installation/configuration completed: $installedVersion" `
            "$displayName 安装/配置完成：$installedVersion"
        return
    }

    if ($restored) {
        Update-ManifestComponent $Component.Name $installedVersion "cached"
        Write-SetupInfo `
            "Restored and verified current $displayName $installedVersion from the build cache." `
            "已从构建缓存恢复并验证当前版本 $displayName $installedVersion。"
        return
    }
    if ($null -ne $cache -and -not $Component.BuildToolchain) {
        Save-ComponentBuildCache $cache
    }
    Update-ManifestComponent $Component.Name $installedVersion "satisfied"
    Write-SetupInfo `
        "$displayName is already satisfied; skipping installation." `
        "$displayName 已满足要求，跳过安装。"
}
function Initialize-ConfiguredToolPaths {
    $settingsFile = Join-Path $script:SetupDirectory "src\core\settings.py"
    $pathSettings = [ordered]@{
        SevenZip = "SEVEN_ZIP_PATH"
        Flac = "FLAC_PATH"
        Ffmpeg = "FFMPEG_PATH"
        Ffprobe = "FFPROBE_PATH"
        X265 = "X265_PATH"
        X264 = "X264_PATH"
        SvtAv1 = "SVT_AV1_PATH"
        FdkAac = "FDK_AAC_PATH"
        DoviTool = "DOVI_TOOL_PATH"
        Hdr10PlusTool = "HDR10PLUS_TOOL_PATH"
        VsEdit = "VSEDIT_PATH"
        VsPipe = "VSPIPE_PATH"
        VapourSynthPlugins = "PLUGIN_PATH"
        Libass = "LIBASS_PATH"
        TsMuxer = "TS_MUXER_PATH"
        MkvInfo = "MKV_INFO_PATH"
        MkvMerge = "MKV_MERGE_PATH"
        MkvPropEdit = "MKV_PROP_EDIT_PATH"
        MkvExtract = "MKV_EXTRACT_PATH"
    }
    $reader = Join-Path $script:SetupDirectory "tools\windows_tool_paths.py"
    $arguments = @($reader, $settingsFile) + @($pathSettings.Values)
    $configured = Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments $arguments | ConvertFrom-Json
    foreach ($name in $pathSettings.Keys) {
        $script:ToolPaths[$name] = [string]$configured.PSObject.Properties[$pathSettings[$name]].Value
    }
    $script:ToolPaths["FfmpegNotices"] = Join-Path (Split-Path -Parent $script:ToolPaths.Ffmpeg) "ffmpeg-licenses.txt"
    $script:ToolPaths["FlacLibrary"] = Join-Path (Split-Path -Parent $script:ToolPaths.Flac) "libFLAC.dll"
    $script:ToolPaths["MkvToolNixRoot"] = Split-Path -Parent $script:ToolPaths.MkvMerge
    $script:ToolPaths["X264Version"] = Join-Path (Split-Path -Parent $script:ToolPaths.X264) "x264-version.txt"
    $script:ToolPaths["X265Version"] = Join-Path (Split-Path -Parent $script:ToolPaths.X265) "x265-version.txt"
    $script:ToolPaths["LibassVersion"] = Join-Path (Split-Path -Parent $script:ToolPaths.Libass) "libass-version.txt"
    $script:ToolPaths["VapourSynthRoot"] = Split-Path -Parent $script:ToolPaths.VsPipe
    $script:ToolPaths["VapourSynthSitePackages"] = Join-Path $script:ToolPaths.VapourSynthRoot "Lib\site-packages"
    if (-not $script:ToolPaths.VapourSynthPlugins) {
        $script:ToolPaths.VapourSynthPlugins = Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth64\plugins"
    }
    Write-SetupInfo `
        "Loaded Windows tool paths from {0}." `
        "已从 {0} 读取 Windows 工具路径。" `
        -FormatArgs @($settingsFile)
}

function Install-ConfiguredFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if ([IO.Path]::GetFullPath($Source) -eq [IO.Path]::GetFullPath($Destination)) {
        return
    }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Destination)) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

function Get-SevenZipRelease {
    return Get-GitHubLatestReleaseAsset -Repository "ip7z/7zip" -AssetPattern '^7z[0-9]+-x64\.exe$'
}

function Get-InstalledSevenZipVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.SevenZip -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.SevenZip
    $match = [regex]::Match($output, '7-Zip\s+([0-9]+\.[0-9]+)', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-SevenZip {
    param([string]$Version)

    $release = Get-SevenZipRelease
    if (-not $release.Sha256) {
        throw (Get-SetupText `
            "The 7-Zip release does not provide a SHA-256 digest." `
            "7-Zip 发布信息未提供 SHA-256 摘要。")
    }
    $installer = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $installer -Sha256 $release.Sha256 | Out-Null
    $directory = Split-Path -Parent $script:ToolPaths.SevenZip
    # The 7-Zip installer splits unquoted /D values at spaces.
    Invoke-SetupInstaller -FilePath $installer -Arguments @("/S", "/D=$directory")
    Install-ConfiguredFile -Source (Join-Path $directory "7z.exe") -Destination $script:ToolPaths.SevenZip
}

function Test-SevenZip {
    $version = Get-InstalledSevenZipVersion
    if (-not $version -or (Compare-SetupVersion $version "23.00") -lt 0) {
        return $false
    }
    if ($Mode -eq "Desktop") {
        return $true
    }
    $directory = Split-Path -Parent $script:ToolPaths.SevenZip
    $library = Get-Item -LiteralPath (Join-Path $directory "7z.dll") -ErrorAction SilentlyContinue
    return ($null -ne $library -and $library.VersionInfo.ProductVersion -eq $version) -and
        (Test-Path -LiteralPath (Join-Path $directory "License.txt") -PathType Leaf)
}

function Get-PythonVersionFromExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return ""
    }
    $version = Invoke-SetupCommand -FilePath $Path -Arguments @(
        "-I", "-c",
        "import sys; assert sys.implementation.name == 'cpython' and sys.maxsize > 2**32 and sys.version_info.releaselevel == 'final'; print('.'.join(map(str, sys.version_info[:3])))"
    )
    if ($version -match '^[0-9]+\.[0-9]+\.[0-9]+$') {
        return $version
    }
    return ""
}

function Get-DetectedPythonInstallation {
    param(
        [string]$PreferredExecutable = $script:ToolPaths.Python,
        [string]$ExpectedVersion = ""
    )

    $candidatePaths = @($PreferredExecutable)
    if ($ExpectedVersion) {
        if ($Mode -eq "Build" -and $env:RUNNER_TOOL_CACHE) {
            $cachedVersion = Join-Path $env:RUNNER_TOOL_CACHE "Python\$ExpectedVersion"
            if (Test-Path -LiteralPath (Join-Path $cachedVersion "x64.complete") -PathType Leaf) {
                $candidatePaths += Join-Path $cachedVersion "x64\python.exe"
            }
        }

        # A Python installer can retain the existing path for this minor version.
        $version = ConvertTo-ComparableVersion $ExpectedVersion
        $series = "$($version.Major).$($version.Minor)"
        $installKey = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey("Software\Python\PythonCore\$series\InstallPath", $false)
        if ($null -ne $installKey) {
            try {
                $registeredPython = [string]$installKey.GetValue("ExecutablePath", "")
                if (-not $registeredPython) {
                    $registeredRoot = [string]$installKey.GetValue("", "")
                    if ($registeredRoot) {
                        $registeredPython = Join-Path $registeredRoot "python.exe"
                    }
                }
                if ($registeredPython) {
                    $candidatePaths += $registeredPython
                }
            }
            finally {
                $installKey.Dispose()
            }
        }
    }

    foreach ($candidate in ($candidatePaths | Select-Object -Unique)) {
        try {
            $detectedVersion = Get-PythonVersionFromExecutable $candidate
        }
        catch {
            continue
        }
        if (-not $detectedVersion -or ($ExpectedVersion -and $detectedVersion -ne $ExpectedVersion)) {
            continue
        }

        $root = Split-Path -Parent $candidate
        return [pscustomobject]@{
            Version = $detectedVersion
            Executable = $candidate
            Root = $root
            Scripts = Join-Path $root "Scripts"
        }
    }
}

function Get-InstalledPythonVersion {
    $installation = Get-DetectedPythonInstallation
    if ($null -eq $installation) {
        return ""
    }
    return $installation.Version
}

function Get-ActivePythonExecutable {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Python -PathType Leaf)) {
        return ""
    }
    return $script:ToolPaths.Python
}

function Install-PythonRuntime {
    param([string]$Version)

    $release = Get-PythonWindowsRelease -Versions @($Version)
    $installer = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload -Uri $release.Uri -Destination $installer | Out-Null
    Assert-ValidAuthenticodeSignature $installer
    [IO.Directory]::CreateDirectory($script:ToolPaths.PythonRoot) | Out-Null
    $installLog = Join-Path $script:TempRoot "python-install.log"
    $desktopIntegration = [int]($Mode -eq "Desktop")
    Invoke-SetupInstaller -FilePath $installer -Arguments @(
        "/quiet",
        "/log", $installLog,
        "InstallAllUsers=1",
        "TargetDir=$($script:ToolPaths.PythonRoot)",
        "PrependPath=0",
        "Include_launcher=$desktopIntegration",
        "InstallLauncherAllUsers=$desktopIntegration",
        "Include_pip=1",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=$desktopIntegration"
    )
    Set-PythonToolPathsForVersion $Version -RequireInstalled
}

function Test-PythonRuntime {
    $python = Get-ActivePythonExecutable
    if (-not $python) {
        Write-SetupWarning `
            "The selected Python executable was not found at $($script:ToolPaths.Python)." `
            "未在 $($script:ToolPaths.Python) 找到选定的 Python 可执行文件。"
        return $false
    }
    try {
        Invoke-SetupCommand -FilePath $python -Arguments @(
            "-I", "-c",
            "import ssl, sqlite3, ctypes, ensurepip; print('ok')"
        ) | Out-Null
        return $true
    }
    catch {
        Write-SetupWarning `
            "Could not verify Python at $python. $($_.Exception.Message)" `
            "无法验证 $python 处的 Python。$($_.Exception.Message)"
        return $false
    }
}

function Get-MachinePathEntries {
    $registryPath = "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($registryPath, $false)
    if ($null -eq $key) {
        throw (Get-SetupText `
            "Unable to open the system environment registry key." `
            "无法打开系统环境变量注册表项。")
    }
    try {
        $pathValue = [string]$key.GetValue(
            "Path",
            "",
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
    }
    finally {
        $key.Dispose()
    }
    return @($pathValue.Split(';') | Where-Object { $_.Trim() })
}

function Test-PythonMachinePath {
    $installation = Get-DetectedPythonInstallation
    if ($null -eq $installation) {
        return $false
    }
    $requiredPaths = @($installation.Root, $installation.Scripts)
    $normalizedEntries = @(Get-MachinePathEntries | ForEach-Object {
        $_.Trim().Trim('"').TrimEnd('\')
    })
    if ($normalizedEntries.Count -lt $requiredPaths.Count) {
        return $false
    }
    for ($index = 0; $index -lt $requiredPaths.Count; $index++) {
        if ($normalizedEntries[$index] -ne $requiredPaths[$index].TrimEnd('\')) {
            return $false
        }
    }
    return $true
}

function Send-EnvironmentChangeNotification {
    if (-not ("BluraySubtitleEnvironmentNotifier" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class BluraySubtitleEnvironmentNotifier
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr window,
        uint message,
        UIntPtr messageParameter,
        string text,
        uint flags,
        uint timeout,
        out UIntPtr result);
}
"@
    }
    $notificationResult = [UIntPtr]::Zero
    [void][BluraySubtitleEnvironmentNotifier]::SendMessageTimeout(
        [IntPtr]0xffff,
        0x001A,
        [UIntPtr]::Zero,
        "Environment",
        0x0002,
        5000,
        [ref]$notificationResult
    )
}

function Add-PythonToMachinePath {
    $installation = Get-DetectedPythonInstallation
    if ($null -eq $installation) {
        throw (Get-SetupText `
            "No usable Python installation was detected." `
            "未检测到可用的 Python 安装。")
    }
    $requiredPaths = @($installation.Root, $installation.Scripts)
    $normalizedRequiredPaths = @($requiredPaths | ForEach-Object { $_.TrimEnd('\') })
    $entries = @(Get-MachinePathEntries)
    $retainedEntries = @(
        foreach ($entry in $entries) {
            $normalizedEntry = $entry.Trim().Trim('"').TrimEnd('\')
            if ($normalizedRequiredPaths -notcontains $normalizedEntry) {
                $entry
            }
        }
    )
    $updatedEntries = @($requiredPaths) + @($retainedEntries)
    $currentEntries = @($entries | ForEach-Object {
        $_.Trim().Trim('"').TrimEnd('\')
    })
    $updatedNormalizedEntries = @($updatedEntries | ForEach-Object {
        $_.Trim().Trim('"').TrimEnd('\')
    })
    if (($currentEntries -join ';') -eq ($updatedNormalizedEntries -join ';')) {
        return
    }

    $registryPath = "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($registryPath, $true)
    if ($null -eq $key) {
        throw (Get-SetupText "Unable to update the system PATH." "无法更新系统 PATH。")
    }
    try {
        $valueKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        $existingValue = $key.GetValue(
            "Path",
            $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        if ($null -ne $existingValue) {
            $valueKind = $key.GetValueKind("Path")
        }
        $key.SetValue("Path", $updatedEntries -join ';', $valueKind)
    }
    finally {
        $key.Dispose()
    }

    Send-EnvironmentChangeNotification
    Write-SetupInfo `
        "Added the selected Python and pip to the beginning of the system PATH." `
        "已将选定的 Python 和 pip 添加到系统 PATH 开头。"
}

function Get-PythonPackageVersion {
    param([Parameter(Mandatory = $true)][string]$Distribution)

    $python = Get-ActivePythonExecutable
    if (-not $python) {
        return ""
    }
    $code = "import importlib.metadata as metadata; print(metadata.version('$Distribution'))"
    try {
        return Invoke-SetupCommand -FilePath $python -Arguments @("-c", $code)
    }
    catch {
        return ""
    }
}

function Install-PythonPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Distribution,
        [switch]$ForceReinstall
    )

    $python = Get-ActivePythonExecutable
    if (-not $python) {
        throw (Get-SetupText `
            "No usable Python installation was detected." `
            "未检测到可用的 Python 安装。")
    }
    $arguments = @(
        "-m", "pip", "install",
        "--disable-pip-version-check",
        "--upgrade",
        "--only-binary=:all:",
        $Distribution
    )
    if ($ForceReinstall) {
        $arguments += "--force-reinstall"
    }
    if ($script:ProxyAddress -ne "DIRECT") {
        $arguments += @("--proxy", $script:ProxyAddress)
    }
    Invoke-SetupCommand -FilePath $python -Arguments $arguments | Out-Null
}

function Test-PythonPackageImport {
    param([Parameter(Mandatory = $true)][string]$ImportStatement)

    $python = Get-ActivePythonExecutable
    if (-not $python) {
        return $false
    }
    try {
        Invoke-SetupCommand -FilePath $python -Arguments @(
            "-c",
            "$ImportStatement; print('ok')"
        ) | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Test-PythonDependencies {
    foreach ($package in $script:PythonPackages) {
        if (-not (Test-PythonPackageImport ([string]$package.Import))) {
            return $false
        }
    }
    return $true
}

function Get-PythonDependenciesVersion {
    foreach ($package in $script:PythonPackages) {
        $distribution = [string]$package.Distribution
        $installedVersion = Get-PythonPackageVersion $distribution
        if (-not $installedVersion) {
            return ""
        }
        $availableVersion = Get-LatestPythonPackageVersion $distribution
        if ((Compare-SetupVersion $installedVersion $availableVersion) -lt 0) {
            return ""
        }
    }
    return "1.0"
}

function Install-AllPythonDependencies {
    foreach ($package in $script:PythonPackages) {
        $distribution = [string]$package.Distribution
        $importStatement = [string]$package.Import
        $installedVersion = Get-PythonPackageVersion $distribution
        $availableVersion = Get-LatestPythonPackageVersion $distribution
        $forceReinstall = $false
        if (
            $installedVersion -and
            (Compare-SetupVersion $installedVersion $availableVersion) -ge 0
        ) {
            if (Test-PythonPackageImport $importStatement) {
                Write-SetupInfo `
                    "Python package {0} {1} is already satisfied; skipping installation." `
                    "Python 包 {0} {1} 已满足要求，跳过安装。" `
                    -FormatArgs @($distribution, $installedVersion)
                continue
            }
            $forceReinstall = $true
        }
        Write-SetupInfo `
            "Installing or repairing Python package {0} (installed: {1}; target: {2})." `
            "正在安装或修复 Python 包 {0}（已安装：{1}；目标：{2}）。" `
            -FormatArgs @($distribution, $installedVersion, $availableVersion)
        Install-PythonPackage $distribution -ForceReinstall:$forceReinstall
        if (-not (Test-PythonPackageImport $importStatement)) {
            throw (Get-SetupText `
                "Python package $distribution could not be imported after installation." `
                "Python 包 $distribution 安装后无法导入。")
        }
    }
}

function Install-PythonDependenciesWithFallback {
    try {
        Install-AllPythonDependencies
        return
    }
    catch {
        $primaryError = $_.Exception.Message
    }

    if (
        $null -eq $script:LatestPythonRelease -or
        $null -eq $script:SelectedPythonRelease -or
        $script:SelectedPythonRelease.Version -ne $script:LatestPythonRelease.Version
    ) {
        throw (Get-SetupText `
            "Python dependency installation failed on the selected fallback version: $primaryError" `
            "在已选回退版本上安装 Python 依赖失败：$primaryError")
    }

    $fallbackRelease = Get-PreviousPythonRelease $script:LatestPythonRelease.Version
    Write-SetupWarning `
        "Python $($script:LatestPythonRelease.Version) could not install every dependency. Falling back to Python $($fallbackRelease.Version)." `
        "Python $($script:LatestPythonRelease.Version) 无法安装全部依赖，回退到 Python $($fallbackRelease.Version)。"
    Set-PythonFallbackSelection `
        -Release $fallbackRelease `
        -AttemptedVersion $script:LatestPythonRelease.Version

    try {
        if ((Get-InstalledPythonVersion) -ne $fallbackRelease.Version -or -not (Test-PythonRuntime)) {
            Install-PythonRuntime $fallbackRelease.Version
            if (-not (Test-PythonRuntime)) {
                throw (Get-SetupText `
                    "The fallback Python runtime failed verification." `
                    "回退后的 Python 运行环境验证失败。")
            }
        }
        Install-AllPythonDependencies
    }
    catch {
        $fallbackError = $_.Exception.Message
        throw (Get-SetupText `
            "Python dependency installation failed on both versions. Latest: $primaryError; fallback: $fallbackError" `
            "两个 Python 版本的依赖安装均失败。最新版：$primaryError；回退版：$fallbackError")
    }
}

function Get-GitRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "git-for-windows/git" `
        -AssetPattern '^PortableGit-[0-9]+(?:\.[0-9]+){2,3}-64-bit\.7z\.exe$'
}

function Get-DetectedGitPath {
    if (Test-Path -LiteralPath $script:ToolPaths.Git -PathType Leaf) {
        return $script:ToolPaths.Git
    }

    foreach ($registryRoot in @(
        [Microsoft.Win32.Registry]::LocalMachine,
        [Microsoft.Win32.Registry]::CurrentUser
    )) {
        $key = $registryRoot.OpenSubKey("Software\GitForWindows", $false)
        if ($null -eq $key) {
            continue
        }
        try {
            $installPath = [string]$key.GetValue(
                "InstallPath",
                "",
                [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
            )
        }
        finally {
            $key.Dispose()
        }
        if ($installPath) {
            $candidate = Join-Path $installPath "cmd\git.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return $candidate
            }
        }
    }
    return ""
}

function Get-GitVersionFromExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $Path -Arguments @("--version")
    $match = [regex]::Match(
        $output,
        'git version\s+([0-9]+\.[0-9]+\.[0-9]+(?:\.windows\.[0-9]+)?)',
        'IgnoreCase'
    )
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Get-InstalledGitVersion {
    return Get-GitVersionFromExecutable $script:ToolPaths.Git
}

function Install-Git {
    param([string]$Version)

    $release = Get-GitRelease
    if (-not $release.Sha256) {
        throw (Get-SetupText `
            "The Portable Git release does not provide a SHA-256 digest." `
            "Portable Git 发布信息未提供 SHA-256 摘要。")
    }
    $archive = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload `
        -Uri $release.Uri `
        -FallbackUri $release.DirectUri `
        -Destination $archive `
        -Sha256 $release.Sha256 | Out-Null

    $detectedPath = Get-DetectedGitPath
    if ($detectedPath -and $detectedPath -ne $script:ToolPaths.Git) {
        Write-SetupInfo `
            "Installing the fixed Git toolchain alongside the existing Git installation." `
            "正在保留现有 Git 的同时安装固定路径 Git 工具链。"
    }
    [IO.Directory]::CreateDirectory($script:ToolPaths.GitRoot) | Out-Null
    Invoke-SetupCommand -FilePath $script:ToolPaths.SevenZip -Arguments @(
        "x",
        "-y",
        "-aoa",
        "-o$($script:ToolPaths.GitRoot)",
        $archive
    ) | Out-Null
}

function Test-Git {
    return [bool](Get-GitVersionFromExecutable $script:ToolPaths.Git)
}

function Test-GitMachinePath {
    if (-not (Test-Git)) {
        return $false
    }
    $gitCommandPath = Join-Path $script:ToolPaths.GitRoot "cmd"
    $normalizedEntries = @(Get-MachinePathEntries | ForEach-Object {
        $_.Trim().Trim('"').TrimEnd('\')
    })
    return $normalizedEntries -contains $gitCommandPath.TrimEnd('\')
}

function Add-GitToMachinePath {
    if (-not (Test-Git)) {
        throw (Get-SetupText `
            "The fixed-path Git installation was not detected." `
            "未检测到固定路径的 Git 安装。")
    }
    $gitCommandPath = Join-Path $script:ToolPaths.GitRoot "cmd"
    $entries = @(Get-MachinePathEntries)
    $normalizedEntries = @($entries | ForEach-Object {
        $_.Trim().Trim('"').TrimEnd('\')
    })
    if ($normalizedEntries -contains $gitCommandPath.TrimEnd('\')) {
        return
    }

    $registryPath = "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($registryPath, $true)
    if ($null -eq $key) {
        throw (Get-SetupText "Unable to update the system PATH." "无法更新系统 PATH。")
    }
    try {
        $valueKind = [Microsoft.Win32.RegistryValueKind]::ExpandString
        $existingValue = $key.GetValue(
            "Path",
            $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        if ($null -ne $existingValue) {
            $valueKind = $key.GetValueKind("Path")
        }
        $key.SetValue("Path", (@($entries) + $gitCommandPath) -join ';', $valueKind)
    }
    finally {
        $key.Dispose()
    }

    Send-EnvironmentChangeNotification
    Write-SetupInfo `
        "Added Git to the system PATH." `
        "已将 Git 添加到系统 PATH。"
}

function Get-StartMenuShortcutDefinitions {
    $programs = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonPrograms)
    $pythonVersion = ConvertTo-ComparableVersion $script:SelectedPythonRelease.Version
    $pythonName = "Python {0}.{1}" -f $pythonVersion.Major, $pythonVersion.Minor
    $pythonMenu = Join-Path $programs $pythonName
    $gitMenu = Join-Path $programs "Git"
    return @(
        [pscustomobject]@{
            Path = Join-Path $pythonMenu "$pythonName (64-bit).lnk"
            TargetPath = $script:ToolPaths.Python
            Arguments = ""
            WorkingDirectory = $script:ToolPaths.PythonRoot
        },
        [pscustomobject]@{
            Path = Join-Path $gitMenu "Git Bash.lnk"
            TargetPath = Join-Path $script:ToolPaths.GitRoot "git-bash.exe"
            Arguments = "--cd-to-home"
            WorkingDirectory = "%HOMEDRIVE%%HOMEPATH%"
        },
        [pscustomobject]@{
            Path = Join-Path $gitMenu "Git CMD.lnk"
            TargetPath = Join-Path $script:ToolPaths.GitRoot "git-cmd.exe"
            Arguments = "--cd-to-home"
            WorkingDirectory = "%HOMEDRIVE%%HOMEPATH%"
        },
        [pscustomobject]@{
            Path = Join-Path $gitMenu "Git GUI.lnk"
            TargetPath = Join-Path $script:ToolPaths.GitRoot "cmd\git-gui.exe"
            Arguments = ""
            WorkingDirectory = "%HOMEDRIVE%%HOMEPATH%"
        }
    )
}

function Test-StartMenuShortcuts {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($definition in @(Get-StartMenuShortcutDefinitions)) {
        if (-not (Test-Path -LiteralPath $definition.Path -PathType Leaf) -or
            -not (Test-Path -LiteralPath $definition.TargetPath -PathType Leaf)) {
            return $false
        }
        try {
            $shortcut = $shell.CreateShortcut($definition.Path)
        }
        catch [Runtime.InteropServices.COMException] {
            return $false
        }
        if ($shortcut.TargetPath -ne $definition.TargetPath -or
            $shortcut.Arguments -cne $definition.Arguments -or
            $shortcut.WorkingDirectory -ne $definition.WorkingDirectory) {
            return $false
        }
    }
    return $true
}

function Install-StartMenuShortcuts {
    $definitions = @(Get-StartMenuShortcutDefinitions)
    foreach ($definition in $definitions) {
        if (-not (Test-Path -LiteralPath $definition.TargetPath -PathType Leaf)) {
            throw ((Get-SetupText `
                "Start menu shortcut target not found: {0}" `
                "开始菜单快捷方式的目标不存在：{0}") -f $definition.TargetPath)
        }
    }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($definition in $definitions) {
        [IO.Directory]::CreateDirectory((Split-Path -Parent $definition.Path)) | Out-Null
        $shortcut = $shell.CreateShortcut($definition.Path)
        $shortcut.TargetPath = $definition.TargetPath
        $shortcut.Arguments = $definition.Arguments
        $shortcut.WorkingDirectory = $definition.WorkingDirectory
        $shortcut.IconLocation = $definition.TargetPath + ",0"
        $shortcut.Save()
    }
    Write-SetupInfo `
        "Created Python and Git Start menu shortcuts for all users." `
        "已为所有用户创建 Python 和 Git 开始菜单快捷方式。"
}

function Invoke-VisualStudioWhere {
    param([string[]]$Arguments)

    $vswhere = Join-Path $script:ToolPaths.VisualStudioInstaller "vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        return ""
    }
    try {
        return Invoke-SetupCommand -FilePath $vswhere -Arguments (@("-version", "[18.0,19.0)") + $Arguments)
    }
    catch {
        return ""
    }
}

function Get-VisualStudioProperty {
    param([Parameter(Mandatory = $true)][string]$Property)

    if ($script:DesktopVisualStudioEnterprise) {
        return [string]$script:DesktopVisualStudioEnterprise.$Property
    }
    $productArguments = if ($Mode -eq "Build") {
        @("-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "Microsoft.Component.MSBuild")
    }
    else {
        @("-products", "Microsoft.VisualStudio.Product.BuildTools", "-requires", "Microsoft.VisualStudio.Workload.VCTools")
    }
    return Invoke-VisualStudioWhere (@("-latest") + $productArguments + @("-property", $Property))
}

function Install-VisualStudioBuildTools {
    param([string]$Version)

    $installationPath = Get-VisualStudioProperty "installationPath"
    if ($installationPath) {
        $clientInstaller = Join-Path $script:ToolPaths.VisualStudioInstaller "setup.exe"
        Write-SetupInfo "Updating the existing Visual Studio Build Tools instance: $installationPath" "正在升级现有 Visual Studio 编译工具实例：$installationPath"
        Invoke-SetupInstaller -FilePath $clientInstaller -Arguments @(
            "update",
            "--quiet",
            "--norestart",
            "--installPath", $installationPath,
            "--channelUri", "https://aka.ms/vs/stable/channel"
        )
        return
    }

    $release = Get-LatestVisualStudioRelease
    $installer = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload -Uri $release.Uri -Destination $installer | Out-Null
    Assert-ValidAuthenticodeSignature $installer
    Invoke-SetupInstaller -FilePath $installer -Arguments @(
        "--quiet",
        "--wait",
        "--norestart",
        "--nocache",
        "--channelUri", "https://aka.ms/vs/stable/channel",
        "--channelId", "VisualStudio.18.Stable",
        "--installPath", $script:ToolPaths.VisualStudioRoot,
        "--add", "Microsoft.VisualStudio.Workload.VCTools",
        "--includeRecommended"
    )
}

function Test-VisualStudioBuildTools {
    param([string]$InstallationPath = (Get-VisualStudioProperty "installationPath"))

    if (-not $InstallationPath) {
        return $false
    }
    $msbuild = Join-Path $InstallationPath "MSBuild\Current\Bin\MSBuild.exe"
    $vcvars = Join-Path $InstallationPath "VC\Auxiliary\Build\vcvars64.bat"
    if (-not (Test-Path -LiteralPath $msbuild -PathType Leaf) -or
        -not (Test-Path -LiteralPath $vcvars -PathType Leaf)) {
        return $false
    }
    $compiler = Get-ChildItem -LiteralPath (Join-Path $installationPath "VC\Tools\MSVC") `
        -Filter "cl.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\bin\\Hostx64\\x64\\cl\.exe$' } |
        Select-Object -First 1
    $windowsSdkHeaders = Get-ChildItem -LiteralPath "C:\Program Files (x86)\Windows Kits\10\Include" `
        -Filter "Windows.h" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\um\\Windows\.h$' } |
        Select-Object -First 1
    return $null -ne $compiler -and $null -ne $windowsSdkHeaders
}

function Find-VerifiedVisualStudioEnterprise {
    $installations = Invoke-VisualStudioWhere @(
        "-products", "Microsoft.VisualStudio.Product.Enterprise",
        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "Microsoft.Component.MSBuild",
        "-sort", "-format", "json", "-utf8"
    )
    if (-not $installations) {
        return $null
    }
    foreach ($instance in ($installations | ConvertFrom-Json)) {
        if ($instance.installationVersion -and (Test-VisualStudioBuildTools $instance.installationPath)) {
            return $instance
        }
    }
}

function Get-CMakeRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "Kitware/CMake" `
        -AssetPattern '^cmake-[0-9]+\.[0-9]+\.[0-9]+-windows-x86_64\.msi$'
}

function Get-InstalledCMakeVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.CMake -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.CMake -Arguments @("--version")
    $match = [regex]::Match($output, 'cmake version\s+([0-9]+\.[0-9]+\.[0-9]+)', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-CMake {
    param([string]$Version)

    $release = Get-CMakeRelease
    $installer = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $installer -Sha256 $release.Sha256 | Out-Null
    Assert-ValidAuthenticodeSignature $installer
    $windowsDirectory = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $msiexec = Join-Path $windowsDirectory "System32\msiexec.exe"
    Invoke-SetupInstaller -FilePath $msiexec -Arguments @(
        "/i", $installer,
        "/qn",
        "/norestart"
    )
}

function Test-CMake {
    if (-not (Get-InstalledCMakeVersion)) {
        return $false
    }
    if ($Mode -eq "Build") {
        $help = Invoke-SetupCommand -FilePath $script:ToolPaths.CMake -Arguments @("--help")
        return $help.Contains("Visual Studio 18 2026")
    }
    return $true
}

function Get-NinjaRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "ninja-build/ninja" `
        -AssetPattern '^ninja-win\.zip$'
}

function Get-InstalledNinjaVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Ninja -PathType Leaf)) {
        return ""
    }
    return Invoke-SetupCommand -FilePath $script:ToolPaths.Ninja -Arguments @("--version")
}

function Install-Ninja {
    param([string]$Version)

    $release = Get-NinjaRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "ninja-extracted"
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $source = Join-Path $extracted "ninja.exe"
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw (Get-SetupText "ninja.exe is missing from the release archive." "发布压缩包中缺少 ninja.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.Ninja)) | Out-Null
    Copy-Item -LiteralPath $source -Destination $script:ToolPaths.Ninja -Force
}

function Test-Ninja {
    return [bool](Get-InstalledNinjaVersion)
}

function Get-InstalledNasmVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Nasm -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.Nasm -Arguments @("-v")
    $match = [regex]::Match($output, 'NASM version\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-Nasm {
    param([string]$Version)

    $release = Get-LatestNasmRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "nasm-extracted"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $nasmExecutable = Get-ChildItem -LiteralPath $extracted -Filter "nasm.exe" -File -Recurse |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "ndisasm.exe") -PathType Leaf } |
        Select-Object -First 1
    if ($null -eq $nasmExecutable) {
        throw (Get-SetupText "NASM executables are missing from the release archive." "NASM 发布压缩包中缺少可执行文件。")
    }
    $sourceDirectory = $nasmExecutable.Directory
    $destinationDirectory = [IO.Path]::GetDirectoryName($script:ToolPaths.Nasm)
    [IO.Directory]::CreateDirectory($destinationDirectory) | Out-Null
    foreach ($name in @("nasm.exe", "ndisasm.exe")) {
        $source = Join-Path $sourceDirectory.FullName $name
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw (Get-SetupText "NASM release file is missing: $name" "NASM 发布文件缺失：$name")
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $destinationDirectory $name) -Force
    }
}

function Test-Nasm {
    return [bool](Get-InstalledNasmVersion)
}

function Get-InstalledMsys2Version {
    $pacman = Join-Path $script:ToolPaths.Msys2Root "usr\bin\pacman.exe"
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Msys2Bash -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pacman -PathType Leaf)) {
        return ""
    }
    $package = Invoke-Msys2Pacman -Arguments @("-Q", "msys2-runtime")
    $fields = $package -split '\s+', 2
    if ($fields.Count -eq 2) {
        return $fields[1]
    }
    return ""
}

function Install-Msys2 {
    $pacman = Join-Path $script:ToolPaths.Msys2Root "usr\bin\pacman.exe"
    $reuseExistingCore =
        (Test-Path -LiteralPath $script:ToolPaths.Msys2Bash -PathType Leaf) -and
        (Test-Path -LiteralPath $pacman -PathType Leaf)
    if ($reuseExistingCore) {
        Write-SetupInfo `
            "Existing MSYS2 core files detected; reusing the installation for a full system upgrade." `
            "检测到现有 MSYS2 核心文件；将复用现有安装并执行完整系统升级。"
    }
    else {
        $release = Get-GitHubLatestReleaseAsset `
            -Repository "msys2/msys2-installer" `
            -AssetPattern '^msys2-base-x86_64-latest\.sfx\.exe$'
        $installer = Join-Path $script:TempRoot $release.Name
        Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $installer -Sha256 $release.Sha256 | Out-Null
        if (-not $release.Sha256) {
            $checksumPath = "$installer.sha256"
            try {
                Invoke-SetupDownload `
                    -Uri ([Uri]($release.DirectUri.AbsoluteUri + ".sha256")) `
                    -Destination $checksumPath | Out-Null
                $checksumText = [IO.File]::ReadAllText($checksumPath)
                $checksumMatch = [regex]::Match($checksumText, '\b([0-9a-fA-F]{64})\b')
                if (-not $checksumMatch.Success) {
                    throw "MSYS2 checksum file is invalid."
                }
                $actualHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
                if ($actualHash -ne $checksumMatch.Groups[1].Value) {
                    throw (Get-SetupText "MSYS2 SHA-256 verification failed." "MSYS2 SHA-256 校验失败。")
                }
            }
            catch {
                throw (Get-SetupText `
                    "Unable to verify the official MSYS2 SHA-256 checksum: $($_.Exception.Message)" `
                    "无法验证 MSYS2 官方 SHA-256：$($_.Exception.Message)")
            }
        }

        Invoke-SetupInstaller -FilePath $installer -Arguments @("-y", "-oC:\") -AcceptedExitCodes @(0)
        if (-not (Test-Path -LiteralPath $script:ToolPaths.Msys2Bash -PathType Leaf) -or
            -not (Test-Path -LiteralPath $pacman -PathType Leaf)) {
            throw (Get-SetupText `
                "MSYS2 extraction did not create a valid C:\msys64." `
                "MSYS2 解压后未创建有效的 C:\msys64。")
        }
    }

    Write-SetupInfo `
        "Running MSYS2 first-start initialization." `
        "正在执行 MSYS2 首次启动初始化。"
    Invoke-SetupCommand -FilePath $script:ToolPaths.Msys2Bash -Arguments @("-lc", "true") | Out-Null
    Write-SetupInfo `
        "MSYS2 first-start initialization completed." `
        "MSYS2 首次启动初始化完成。"
    $certificateBundle = Join-Path $script:ToolPaths.Msys2Root "usr\ssl\certs\ca-bundle.crt"
    if (-not (Test-Path -LiteralPath $certificateBundle -PathType Leaf) -or
        (Get-Item -LiteralPath $certificateBundle).Length -eq 0) {
        Write-SetupInfo `
            "Repairing the MSYS2 CA certificate bundle." `
            "正在修复 MSYS2 CA 证书包。"
        Invoke-SetupCommand `
            -FilePath $script:ToolPaths.Msys2Bash `
            -Arguments @("-lc", "/usr/bin/update-ca-trust && test -s /usr/ssl/certs/ca-bundle.crt") | Out-Null
    }
    Write-SetupInfo `
        "Upgrading MSYS2 and all installed packages." `
        "正在升级 MSYS2 及所有已安装的软件包。"
    Invoke-Msys2Pacman -Arguments @("--noconfirm", "-Syu") | Out-Null
    # A core upgrade exits pacman before other packages; restart it to complete the full upgrade.
    Write-SetupInfo `
        "Completing the MSYS2 system upgrade with a new pacman process." `
        "正在启动新的 pacman 进程以完成 MSYS2 系统升级。"
    Invoke-Msys2Pacman -Arguments @("--noconfirm", "-Syu") | Out-Null
}
function Test-Msys2 {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Msys2Bash -PathType Leaf)) {
        return $false
    }
    $pacman = Join-Path $script:ToolPaths.Msys2Root "usr\bin\pacman.exe"
    if (-not (Test-Path -LiteralPath $pacman -PathType Leaf)) {
        return $false
    }
    try {
        Invoke-SetupCommand `
            -FilePath $script:ToolPaths.Msys2Bash `
            -Arguments @("-lc", "test -s /usr/ssl/certs/ca-bundle.crt") | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Get-Msys2PacmanConfigArguments {
    if ($script:ProxyAddress -eq "DIRECT") {
        return @()
    }

    $sourceConfig = Join-Path $script:ToolPaths.Msys2Root "etc\pacman.conf"
    $temporaryConfig = Join-Path $script:TempRoot "pacman-proxy.conf"
    if (-not (Test-Path -LiteralPath $temporaryConfig -PathType Leaf)) {
        $configText = [IO.File]::ReadAllText($sourceConfig)
        $proxyCommand = "XferCommand = /usr/bin/curl --location --continue-at - --fail --output %o --url %u --proxy '$($script:ProxyAddress)' --proxy-anyauth --proxy-user :"
        $configText = $configText.Replace("[options]", "[options]`n$proxyCommand")
        [IO.File]::WriteAllText($temporaryConfig, $configText, (New-Object Text.UTF8Encoding($false)))
    }

    $cygpath = Join-Path $script:ToolPaths.Msys2Root "usr\bin\cygpath.exe"
    $unixConfig = Invoke-SetupCommand -FilePath $cygpath -Arguments @("-u", $temporaryConfig)
    return @("--config", $unixConfig)
}

function Invoke-Msys2Pacman {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [int[]]$AcceptedExitCodes = @(0)
    )

    $pacman = Join-Path $script:ToolPaths.Msys2Root "usr\bin\pacman.exe"
    $effectiveArguments = @(Get-Msys2PacmanConfigArguments) + $Arguments
    $previousPath = $env:PATH
    try {
        # Package hooks need MSYS2 tools in the pacman process's inherited PATH.
        $msysBin = Join-Path $script:ToolPaths.Msys2Root "usr\bin"
        $env:PATH = "$msysBin;$previousPath"
        return Invoke-SetupCommand `
            -FilePath $pacman `
            -Arguments $effectiveArguments `
            -AcceptedExitCodes $AcceptedExitCodes
    }
    finally {
        $env:PATH = $previousPath
    }
}

function Get-Msys2PackagesVersion {
    if (-not (Test-Msys2)) {
        return ""
    }
    try {
        $individualPackages = @(
            $script:Msys2Packages |
                Where-Object { $_ -ne "mingw-w64-ucrt-x86_64-toolchain" }
        )
        Invoke-Msys2Pacman -Arguments (@("-Q") + $individualPackages) | Out-Null
        $gcc = Join-Path $script:ToolPaths.Msys2Root "ucrt64\bin\gcc.exe"
        if (-not (Test-Path -LiteralPath $gcc -PathType Leaf)) {
            return ""
        }
        return "1.0"
    }
    catch {
        return ""
    }
}

function Install-Msys2Packages {
    param([string]$Version)

    Write-SetupInfo `
        "Installing or upgrading required MSYS2 build packages." `
        "正在安装或升级所需的 MSYS2 编译依赖包。"
    Invoke-Msys2Pacman -Arguments (@("--noconfirm", "--needed", "-S") + $script:Msys2Packages) | Out-Null
}

function Test-Msys2Packages {
    return (Get-Msys2PackagesVersion) -eq "1.0"
}

function Get-FfmpegRelease {
    return Get-GitHubLatestTaggedSource `
        -Repository "FFmpeg/FFmpeg" `
        -TagPattern '^n(?<version>[0-9]+(?:\.[0-9]+){1,3})$' `
        -ArchiveBaseName "ffmpeg"
}

function Get-FfmpegExecutableInfo {
    param([string]$Path, [string]$Program)

    try {
        $output = Invoke-SetupCommand -FilePath $Path -Arguments @("-version")
    }
    catch {
        return $null
    }
    $match = [regex]::Match($output, "^$Program version\s+([0-9]+(?:\.[0-9]+){1,3})", "IgnoreCase")
    if ($match.Success) {
        return [pscustomobject]@{ Version = $match.Groups[1].Value; Output = $output }
    }
    return $null
}

function Get-InstalledFfmpegVersion {
    if (Test-Path -LiteralPath $script:ToolPaths.Ffprobe -PathType Leaf) {
        $info = Get-FfmpegExecutableInfo $script:ToolPaths.Ffmpeg "ffmpeg"
        if ($null -ne $info) {
            return $info.Version
        }
    }
    return ""
}

function Test-Ffmpeg {
    param(
        [string]$Ffmpeg = $script:ToolPaths.Ffmpeg,
        [string]$Ffprobe = $script:ToolPaths.Ffprobe,
        [string]$ExpectedVersion
    )

    $encoder = Get-FfmpegExecutableInfo $Ffmpeg "ffmpeg"
    $probe = Get-FfmpegExecutableInfo $Ffprobe "ffprobe"
    if ($null -eq $encoder -or $null -eq $probe -or
        (Compare-SetupVersion $encoder.Version $probe.Version) -ne 0 -or
        ($ExpectedVersion -and (Compare-SetupVersion $encoder.Version $ExpectedVersion) -ne 0)) {
        return $false
    }
    if ($Mode -ne "Build") {
        return $true
    }

    # A fixed profile with autodetection disabled rejects both extra and missing features.
    $configuration = "configuration: $($script:FfmpegConfigureOptions -join ' ')"
    foreach ($info in @($encoder, $probe)) {
        if (($info.Output -split '\r?\n').Trim() -cnotcontains $configuration) {
            Write-SetupInfo "FFmpeg or FFprobe differs from the package build profile." "FFmpeg 或 FFprobe 的构建参数与打包配置不符。"
            return $false
        }
    }
    $notices = Join-Path (Split-Path -Parent $Ffmpeg) "ffmpeg-licenses.txt"
    return (Test-Path -LiteralPath $notices -PathType Leaf) -and
        (Get-Content -LiteralPath $notices -Encoding UTF8 -TotalCount 1) -ceq "FFmpeg $($encoder.Version)"
}

function Install-Ffmpeg {
    param([string]$Version)

    $packagePrefix = "mingw-w64-ucrt-x86_64-"
    $packages = @("dav1d", "opus", "bzip2", "libiconv", "xz", "zlib" | ForEach-Object { "$packagePrefix$_" })
    Invoke-Msys2Pacman -Arguments (@("--noconfirm", "--needed", "-S") + $packages) | Out-Null

    $release = Get-FfmpegRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $buildRoot = Join-Path $script:TempRoot "ff"
    $sourceRoot = Join-Path $buildRoot "src"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive | Out-Null
    Expand-SetupZip -Archive $archive -Destination $buildRoot
    Rename-Item -LiteralPath (Join-Path $buildRoot "FFmpeg-$($release.Tag)") -NewName "src"
    # Source tag archives do not carry the release tarball's VERSION file.
    [IO.File]::WriteAllText((Join-Path $sourceRoot "VERSION"), "$Version`n", $script:Utf8Encoding)

    $buildScriptContent = @'
set -eu
export PATH=/ucrt64/bin:/usr/bin
unset PKG_CONFIG_PATH
export PKG_CONFIG_LIBDIR=/ucrt64/lib/pkgconfig
cd "$1"
jobs=$2
shift 2
export TMPDIR=.
/usr/bin/dash.exe src/configure "$@" || {
    if [ -f ffbuild/config.log ]; then tail -n 80 ffbuild/config.log; fi
    exit 1
}
make -j"$jobs" SHELL=/usr/bin/dash.exe ffmpeg.exe ffprobe.exe
'@
    $buildScript = Write-SetupTempScript -Name "build-ffmpeg.sh" -Content $buildScriptContent
    Invoke-SetupBuildCommand `
        -DisplayName "official FFmpeg and FFprobe source build" `
        -FilePath (Join-Path $script:ToolPaths.Msys2Root "usr\bin\dash.exe") `
        -Arguments (@(
            (ConvertTo-Msys2Path $buildScript),
            (ConvertTo-Msys2Path $buildRoot),
            [string]$script:BuildJobs
        ) + $script:FfmpegConfigureOptions)

    $installedPackages = Invoke-Msys2Pacman -Arguments (@("-Q") + $packages)
    $notices = @(
        "FFmpeg $Version"
        "Source: $($release.Uri.AbsoluteUri)"
        "Configuration: $($script:FfmpegConfigureOptions -join ' ')"
        foreach ($file in @("LICENSE.md", "COPYING.GPLv3", "COPYING.LGPLv3")) {
            ""
            "FFmpeg $file"
            [IO.File]::ReadAllText((Join-Path $sourceRoot $file))
        }
        foreach ($line in $installedPackages -split '\r?\n') {
            $package, $packageVersion = $line -split ' ', 2
            $library = $package.Substring($packagePrefix.Length)
            ""
            "$package $packageVersion"
            "Source: https://mirror.msys2.org/mingw/sources/mingw-w64-$library-$packageVersion.src.tar.zst"
            $licenseRoot = Join-Path $script:ToolPaths.Msys2Root "ucrt64\share\licenses\$library"
            foreach ($file in Get-ChildItem -LiteralPath $licenseRoot -File -Recurse | Sort-Object FullName) {
                $file.Name
                [IO.File]::ReadAllText($file.FullName)
            }
        }
    )
    $noticesPath = Join-Path $buildRoot "ffmpeg-licenses.txt"
    [IO.File]::WriteAllLines($noticesPath, [string[]]$notices, $script:Utf8Encoding)

    $ffmpegExecutable = Join-Path $buildRoot "ffmpeg.exe"
    $ffprobeExecutable = Join-Path $buildRoot "ffprobe.exe"
    if (-not (Test-Ffmpeg -Ffmpeg $ffmpegExecutable -Ffprobe $ffprobeExecutable -ExpectedVersion $Version)) {
        throw (Get-SetupText "The compiled FFmpeg and FFprobe failed verification." "编译生成的 FFmpeg 和 FFprobe 未通过验证。")
    }
    Install-ConfiguredFile -Source $noticesPath -Destination $script:ToolPaths.FfmpegNotices
    Install-ConfiguredFile -Source $ffmpegExecutable -Destination $script:ToolPaths.Ffmpeg
    Install-ConfiguredFile -Source $ffprobeExecutable -Destination $script:ToolPaths.Ffprobe
}

function Get-FlacRelease {
    $release = Get-GitHubLatestReleaseAsset `
        -Repository "xiph/flac" `
        -AssetPattern '^flac-[0-9]+(?:\.[0-9]+){1,3}-win\.zip$'
    if (-not $release.Sha256) {
        $checksumPattern = '(?im)`?([0-9a-fA-F]{64})`?\s+' + [regex]::Escape($release.Name)
        $checksumMatch = [regex]::Match($release.ReleaseBody, $checksumPattern)
        if (-not $checksumMatch.Success) {
            throw (Get-SetupText "The FLAC release does not provide a SHA-256 checksum." "FLAC 发布信息未提供 SHA-256。")
        }
        $release.Sha256 = $checksumMatch.Groups[1].Value
    }
    return $release
}

function Get-InstalledFlacVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Flac -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.Flac -Arguments @("--version")
    $match = [regex]::Match($output, 'flac\s+([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-Flac {
    param([string]$Version)

    $release = Get-FlacRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "flac-extracted"
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $flacExecutable = Get-ChildItem -LiteralPath $extracted -Filter "flac.exe" -File -Recurse |
        Where-Object { $_.FullName -match '\\Win64\\flac\.exe$' } |
        Select-Object -First 1
    if ($null -eq $flacExecutable) {
        throw (Get-SetupText "The Win64 FLAC executable is missing from the release archive." "发布压缩包中缺少 Win64 FLAC 可执行文件。")
    }
    $flacLibrary = Join-Path $flacExecutable.DirectoryName "libFLAC.dll"
    if (-not (Test-Path -LiteralPath $flacLibrary -PathType Leaf)) {
        throw (Get-SetupText "libFLAC.dll is missing from the release archive." "发布压缩包中缺少 libFLAC.dll。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.Flac)) | Out-Null
    Copy-Item -LiteralPath $flacExecutable.FullName -Destination $script:ToolPaths.Flac -Force
    Copy-Item -LiteralPath $flacLibrary -Destination $script:ToolPaths.FlacLibrary -Force
}

function Test-Flac {
    return [bool](Get-InstalledFlacVersion) -and
        (Test-Path -LiteralPath $script:ToolPaths.FlacLibrary -PathType Leaf)
}

function Get-MkvToolNixRelease {
    $cacheKey = "mkvtoolnix-windows-latest"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    [xml]$releaseMetadata = Get-SetupTextFromUri `
        -Uri ([Uri]"https://mkvtoolnix.download/latest-release.xml") `
        -CacheName "mkvtoolnix-latest-release.xml"
    $version = [string]$releaseMetadata.'mkvtoolnix-releases'.'latest-source'.version
    if ($version -notmatch '^[0-9]+(?:\.[0-9]+){1,3}$') {
        throw (Get-SetupText "Unable to parse the latest MKVToolNix version." "无法解析 MKVToolNix 最新版本。")
    }
    $name = "mkvtoolnix-$version.tar.xz"
    $sourceUri = [Uri]([string]$releaseMetadata.'mkvtoolnix-releases'.'latest-source'.'source-code-url')
    if ($sourceUri.Scheme -ne "https" -or $sourceUri.Host -ne "mkvtoolnix.download" -or
        $sourceUri.AbsolutePath -ne "/sources/$name") {
        throw (Get-SetupText "Unexpected MKVToolNix source archive URL." "MKVToolNix 源码压缩包地址与预期不符。")
    }
    $checksumText = Get-SetupTextFromUri `
        -Uri ([Uri]($sourceUri.AbsoluteUri + ".sha256")) `
        -CacheName "$name.sha256"
    $checksumPattern = '(?im)^([0-9a-fA-F]{64})\s+' + [regex]::Escape($name) + '\s*$'
    $checksumMatch = [regex]::Match($checksumText, $checksumPattern)
    if (-not $checksumMatch.Success) {
        throw (Get-SetupText "Unable to find the MKVToolNix source SHA-256 checksum." "无法找到 MKVToolNix 源码的 SHA-256。")
    }
    $result = [pscustomobject]@{
        Version = $version
        Uri = $sourceUri
        Sha256 = $checksumMatch.Groups[1].Value.ToLowerInvariant()
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-MkvToolNixBuildArguments {
    param([string]$Operation)

    return @(
        (Join-Path $script:SetupDirectory "tools\build_mkvtoolnix_windows.py"),
        $Operation, $script:ToolPaths.MkvToolNixRoot,
        [IO.Path]::GetFileName($script:ToolPaths.MkvMerge),
        [IO.Path]::GetFileName($script:ToolPaths.MkvInfo),
        [IO.Path]::GetFileName($script:ToolPaths.MkvPropEdit),
        [IO.Path]::GetFileName($script:ToolPaths.MkvExtract)
    )
}

function Get-InstalledMkvToolNixVersion {
    return Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments (Get-MkvToolNixBuildArguments "version")
}

function Install-MkvToolNix {
    param([string]$Version)

    $release = Get-MkvToolNixRelease
    $arguments = (Get-MkvToolNixBuildArguments "install") + @(
        "--version", $Version, "--source", $release.Uri.AbsoluteUri, "--sha256", $release.Sha256,
        "--cache", $script:NativeToolCacheRoot, "--work", (Join-Path $script:TempRoot "mkvtoolnix"),
        "--msys2-root", $script:ToolPaths.Msys2Root, "--jobs", [string]$script:BuildJobs
    )
    $msysRequired = 75
    Invoke-SetupBuildCommand -DisplayName "MKVToolNix build cache" -FilePath $script:ToolPaths.Python `
        -Arguments ($arguments + "--defer-msys2") -AcceptedExitCodes @(0, $msysRequired)
    if ($LASTEXITCODE -eq $msysRequired) {
        Initialize-SetupBuildToolchain "msys2"
        $packages = @("boost", "flac", "libdvdcss", "libdvdread", "libogg", "libvorbis", "libxslt",
            "docbook-xml", "docbook-xsl", "qt6-base", "ruby", "gettext-tools") |
            ForEach-Object { "mingw-w64-ucrt-x86_64-$_" }
        Invoke-Msys2Pacman -Arguments (@("--noconfirm", "--needed", "-S", "dash") + $packages) | Out-Null
        Invoke-SetupBuildCommand -DisplayName "MKVToolNix (MinGW QtCore)" -FilePath $script:ToolPaths.Python -Arguments $arguments
    }
    else {
        Write-SetupInfo "Restored the MKVToolNix build cache." "已恢复 MKVToolNix 构建缓存。"
    }
}

function Test-MkvToolNix {
    return [bool](Get-InstalledMkvToolNixVersion)
}

function Get-TsMuxerRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "justdan96/tsMuxer" `
        -AssetPattern '^tsMuxer-[0-9]+(?:\.[0-9]+){1,3}-win64\.zip$'
}

function Get-InstalledTsMuxerVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.TsMuxer -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand `
        -FilePath $script:ToolPaths.TsMuxer `
        -AcceptedExitCodes @(0, -1)
    $match = [regex]::Match($output, 'tsMuxeR version\s+([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-TsMuxer {
    param([string]$Version)

    $release = Get-TsMuxerRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "tsmuxer-extracted"
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $executable = Get-ChildItem -LiteralPath $extracted -Filter "tsMuxeR.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        throw (Get-SetupText "tsMuxeR.exe is missing from the release archive." "发布压缩包中缺少 tsMuxeR.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.TsMuxer)) | Out-Null
    Copy-Item -LiteralPath $executable.FullName -Destination $script:ToolPaths.TsMuxer -Force
}

function Test-TsMuxer {
    return [bool](Get-InstalledTsMuxerVersion)
}

function Get-DoviToolRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "quietvoid/dovi_tool" `
        -AssetPattern '^dovi_tool-[0-9]+(?:\.[0-9]+){1,3}-x86_64-pc-windows-msvc\.zip$'
}

function Get-InstalledDoviToolVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.DoviTool -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.DoviTool -Arguments @("--version")
    $match = [regex]::Match($output, 'dovi_tool\s+([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-DoviTool {
    param([string]$Version)

    $release = Get-DoviToolRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "dovi-tool-extracted"
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $executable = Get-ChildItem -LiteralPath $extracted -Filter "dovi_tool.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        throw (Get-SetupText "dovi_tool.exe is missing from the release archive." "发布压缩包中缺少 dovi_tool.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.DoviTool)) | Out-Null
    Copy-Item -LiteralPath $executable.FullName -Destination $script:ToolPaths.DoviTool -Force
}

function Test-DoviTool {
    return [bool](Get-InstalledDoviToolVersion)
}

function Get-Hdr10PlusToolRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "quietvoid/hdr10plus_tool" `
        -AssetPattern '^hdr10plus_tool-[0-9]+(?:\.[0-9]+){1,3}-x86_64-pc-windows-msvc\.zip$'
}

function Get-InstalledHdr10PlusToolVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Hdr10PlusTool -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.Hdr10PlusTool -Arguments @("--version")
    $match = [regex]::Match($output, 'hdr10plus_tool\s+([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-Hdr10PlusTool {
    param([string]$Version)

    $release = Get-Hdr10PlusToolRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "hdr10plus-tool-extracted"
    Invoke-SetupDownload -Uri $release.Uri -FallbackUri $release.DirectUri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $executable = Get-ChildItem -LiteralPath $extracted -Filter "hdr10plus_tool.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        throw (Get-SetupText "hdr10plus_tool.exe is missing from the release archive." "发布压缩包中缺少 hdr10plus_tool.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.Hdr10PlusTool)) | Out-Null
    Copy-Item -LiteralPath $executable.FullName -Destination $script:ToolPaths.Hdr10PlusTool -Force
}

function Test-Hdr10PlusTool {
    return [bool](Get-InstalledHdr10PlusToolVersion)
}

function Get-X264Release {
    $cacheKey = "gitlab:x264:official-master"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $commits = @(Get-SetupJsonFromUri `
        -Uri ([Uri]"https://code.videolan.org/api/v4/projects/videolan%2Fx264/repository/commits?ref_name=master&per_page=1") `
        -CacheName "x264-master-commit.json")
    $commit = $commits | Select-Object -First 1
    $commitId = [string]$commit.id
    $committedDate = [string]$commit.committed_date
    if (-not $commitId -or -not $committedDate) {
        throw (Get-SetupText `
            "The latest official x264 master revision could not be determined." `
            "无法确定官方 x264 master 的最新版本。")
    }
    $timestamp = [DateTimeOffset]::Parse(
        $committedDate,
        [Globalization.CultureInfo]::InvariantCulture
    ).UtcDateTime.ToString("yyyy.MM.dd.HHmmss", [Globalization.CultureInfo]::InvariantCulture)
    $result = [pscustomobject]@{
        Version = $timestamp
        Branch = "master"
        Repository = "https://code.videolan.org/videolan/x264.git"
        Commit = $commitId
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-InstalledX264Version {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.X264 -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:ToolPaths.X264Version -PathType Leaf)) {
        return ""
    }
    return ([IO.File]::ReadAllText($script:ToolPaths.X264Version)).Trim()
}

function Install-X264 {
    param([string]$Version)

    $release = Get-X264Release
    $sourceRoot = Join-Path $script:TempRoot "x264-source"
    Invoke-SetupBuildCommand `
        -DisplayName "latest official x264 source checkout" `
        -FilePath $script:ToolPaths.Git `
        -Arguments @("clone", $release.Repository, $sourceRoot)
    Invoke-SetupBuildCommand `
        -DisplayName "resolved official x264 master checkout" `
        -FilePath $script:ToolPaths.Git `
        -Arguments @("-C", $sourceRoot, "checkout", "--detach", $release.Commit)

    $trainingY4m = Join-Path $script:TempRoot "x264-pgo-training.y4m"
    Invoke-SetupBuildCommand `
        -DisplayName "x264 PGO training video generation" `
        -FilePath $script:ToolPaths.Ffmpeg `
        -Arguments @(
            "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", "testsrc2=size=1280x720:rate=24000/1001",
            "-frames:v", "120",
            "-pix_fmt", "yuv420p",
            "-f", "yuv4mpegpipe",
            "-y", $trainingY4m
        )

    $buildScriptContent = @(
        'set -euo pipefail',
        'export PATH=/ucrt64/bin:/usr/bin',
        'source_root=$1',
        'training_y4m=$2',
        'jobs=$3',
        'cd "$source_root"',
        './configure --enable-static --bit-depth=all --chroma-format=all --disable-opencl --enable-lto --extra-ldflags="-static -static-libgcc"',
        'sed -i -E ''/^LDFLAGS[[:space:]]*=/s/-flto([[:space:]]|$)/-flto=auto\1/g'' config.mak',
        'make -j"$jobs" fprofiled VIDS="$training_y4m"'
    ) -join "`n"
    $buildScript = Write-SetupTempScript -Name "build-x264.sh" -Content $buildScriptContent
    Invoke-SetupBuildCommand `
        -DisplayName "latest official x264 8/10-bit PGO compilation" `
        -FilePath $script:ToolPaths.Msys2Bash `
        -Arguments @(
            (ConvertTo-Msys2Path $buildScript),
            (ConvertTo-Msys2Path $sourceRoot),
            (ConvertTo-Msys2Path $trainingY4m),
            [string]$script:BuildJobs
        )

    $executable = Join-Path $sourceRoot "x264.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw (Get-SetupText `
            "The official x264 executable is missing after compilation." `
            "官方 x264 编译完成后未找到可执行文件。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.X264)) | Out-Null
    Copy-Item -LiteralPath $executable -Destination $script:ToolPaths.X264 -Force
    Add-StaticBuildArtifact "x264" (Join-Path $sourceRoot "libx264.a") "libx264.a"
    [IO.File]::WriteAllText(
        $script:ToolPaths.X264Version,
        $release.Version,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-X264 {
    try {
        if (-not (Get-InstalledX264Version)) {
            return $false
        }
        $help = Invoke-SetupCommand -FilePath $script:ToolPaths.X264 -Arguments @("--fullhelp")
        $requiredOptions = @(
            "--output-depth",
            "--mastering-display",
            "--cll",
            "--colorprim",
            "--transfer",
            "--colormatrix"
        )
        $missingOptions = @($requiredOptions | Where-Object {
            $help.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -lt 0
        })
        return $missingOptions.Count -eq 0
    }
    catch {
        return $false
    }
}
function Update-X265Hdr10PlusSource {
    param([Parameter(Mandatory = $true)][string]$SourceRoot)

    $sourceFile = Join-Path $SourceRoot "dynamicHDR10\json11\json11.cpp"
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
        throw (Get-SetupText "The x265 HDR10+ json11 source file is missing." "x265 HDR10+ json11 源文件不存在。")
    }
    $encoding = New-Object Text.UTF8Encoding($false)
    $source = [IO.File]::ReadAllText($sourceFile, $encoding)
    if ($source.Contains("#include <cstdint>")) {
        return
    }
    $lineEnding = if ($source.Contains("`r`n")) { "`r`n" } else { "`n" }
    $context = "#include <limits>$lineEnding"
    if (-not $source.Contains($context)) {
        throw (Get-SetupText "The x265 HDR10+ json11 compatibility patch context is missing." "x265 HDR10+ json11 兼容补丁上下文不存在。")
    }
    $updated = $source.Replace($context, "${context}#include <cstdint>$lineEnding")
    [IO.File]::WriteAllText($sourceFile, $updated, $encoding)
}

function Get-X265Release {
    return Get-GitHubLatestTaggedSource `
        -Repository "Multicorewareinc/x265" `
        -TagPattern '^(?<version>[0-9]+(?:\.[0-9]+){1,3})$' `
        -ArchiveBaseName "x265"
}
function Get-InstalledX265Version {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.X265 -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:ToolPaths.X265Version -PathType Leaf)) {
        return ""
    }
    $versionFile = [IO.File]::ReadAllText($script:ToolPaths.X265Version)
    return (($versionFile -split '\r?\n', 2)[0]).Trim()
}

function Get-NinjaCMakeArguments {
    return @(
        "-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=$($script:ToolPaths.Ninja)", "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_C_COMPILER=cl.exe", "-DCMAKE_CXX_COMPILER=cl.exe"
    )
}

function Invoke-VisualStudioBuild {
    param([scriptblock]$Build)

    if ($null -eq $script:VisualStudioBuildEnvironment) {
        $visualStudio = Get-VisualStudioProperty "installationPath"
        $vcvars = Join-Path $visualStudio "VC\Auxiliary\Build\vcvars64.bat"
        $processInfo = New-Object Diagnostics.ProcessStartInfo
        $processInfo.FileName = Join-Path $env:WINDIR "System32\cmd.exe"
        $processInfo.Arguments = '/d /u /s /c "call "' + $vcvars + '" >nul && set"'
        $processInfo.UseShellExecute = $false
        $processInfo.RedirectStandardOutput = $true
        $processInfo.StandardOutputEncoding = [Text.Encoding]::Unicode
        $process = [Diagnostics.Process]::Start($processInfo)
        try {
            $output = $process.StandardOutput.ReadToEnd()
            $process.WaitForExit()
            if ($process.ExitCode -ne 0) {
                throw (Get-SetupText "Could not initialize the x64 MSVC build environment." "无法初始化 x64 MSVC 构建环境。")
            }
        }
        finally {
            $process.Dispose()
        }
        $environment = @{}
        foreach ($line in $output -split '\r?\n') {
            $separator = $line.IndexOf("=")
            if ($separator -gt 0) {
                $name = $line.Substring(0, $separator)
                if ($name -in @("Path", "Include", "Lib", "LibPath", "VCINSTALLDIR", "VCToolsInstallDir",
                    "VCToolsVersion", "WindowsSdkDir", "WindowsSDKVersion", "UniversalCRTSdkDir", "UCRTVersion")) {
                    $environment[$name] = $line.Substring($separator + 1)
                }
            }
        }
        if (-not $environment["Path"] -or -not $environment["Include"] -or -not $environment["Lib"]) {
            throw (Get-SetupText "The x64 MSVC build environment is incomplete." "x64 MSVC 构建环境不完整。")
        }
        # Setuptools uses this initialized MSVC environment for native extensions.
        $environment["DISTUTILS_USE_SDK"] = "1"
        $script:VisualStudioBuildEnvironment = $environment
    }
    $previous = @{}
    try {
        foreach ($name in $script:VisualStudioBuildEnvironment.Keys) {
            $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
            [Environment]::SetEnvironmentVariable($name, $script:VisualStudioBuildEnvironment[$name], "Process")
        }
        & $Build
    }
    finally {
        foreach ($name in $previous.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}

function Add-StaticBuildArtifact {
    param([string]$Component, [string]$Source, [string]$Name)

    if ($script:BuildCacheRoot -and $Source -and (Test-Path -LiteralPath $Source -PathType Leaf)) {
        $directory = Join-Path $script:TempRoot "artifacts-$Component"
        [IO.Directory]::CreateDirectory($directory) | Out-Null
        Copy-Item -LiteralPath $Source -Destination (Join-Path $directory $Name) -Force
    }
}

function Install-X265 {
    param([string]$Version)

    $release = Get-X265Release
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "x265-extracted"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $sourceCmake = Get-ChildItem -LiteralPath $extracted -Filter "CMakeLists.txt" -File -Recurse |
        Where-Object {
            $_.Directory.Name -eq "source" -and
            (Test-Path -LiteralPath (Join-Path $_.DirectoryName "x265.h") -PathType Leaf)
        } |
        Select-Object -First 1
    if ($null -eq $sourceCmake) {
        throw (Get-SetupText "x265 source directory is missing." "未找到 x265 源码目录。")
    }
    $sourceRoot = $sourceCmake.Directory.FullName
    Update-X265Hdr10PlusSource -SourceRoot $sourceRoot

    $buildRoot = Join-Path $script:TempRoot "x265-build"
    $build12 = Join-Path $buildRoot "12bit"
    $build10 = Join-Path $buildRoot "10bit"
    $build8 = Join-Path $buildRoot "8bit"
    $nasmPath = $script:ToolPaths.Nasm.Replace('\', '/')
    $commonArguments = @(Get-NinjaCMakeArguments) + @(
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.10",
        "-DSTATIC_LINK_CRT=ON",
        "-DENABLE_SHARED=OFF",
        "-DENABLE_LIBNUMA=OFF",
        "-DENABLE_LSMASH=OFF",
        "-DENABLE_LAVF=OFF",
        "-DENABLE_AVISYNTH=OFF",
        "-DENABLE_VPYSYNTH=OFF",
        "-DNASM_EXECUTABLE=$nasmPath",
        "-DCMAKE_ASM_NASM_COMPILER=$nasmPath"
    )

    Invoke-SetupBuildCommand `
        -DisplayName "x265 12-bit core configuration" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments (@("-S", $sourceRoot, "-B", $build12) + $commonArguments + @(
            "-DHIGH_BIT_DEPTH=ON",
            "-DMAIN12=ON",
            "-DEXPORT_C_API=OFF",
            "-DENABLE_HDR10_PLUS=ON",
            "-DENABLE_CLI=OFF"
        ))
    Invoke-SetupBuildCommand `
        -DisplayName "x265 12-bit core compilation" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments @("--build", $build12, "--config", "Release", "--target", "x265-static", "--parallel", $script:BuildJobs)
    $library12 = Get-ChildItem -LiteralPath $build12 -Filter "x265-static.lib" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $library12) {
        throw (Get-SetupText "The x265 12-bit static library is missing." "未找到 x265 12-bit 静态库。")
    }

    Invoke-SetupBuildCommand `
        -DisplayName "x265 10-bit core configuration" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments (@("-S", $sourceRoot, "-B", $build10) + $commonArguments + @(
            "-DHIGH_BIT_DEPTH=ON",
            "-DMAIN12=OFF",
            "-DEXPORT_C_API=OFF",
            "-DENABLE_HDR10_PLUS=ON",
            "-DENABLE_CLI=OFF"
        ))
    Invoke-SetupBuildCommand `
        -DisplayName "x265 10-bit core compilation" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments @("--build", $build10, "--config", "Release", "--target", "x265-static", "--parallel", $script:BuildJobs)
    $library10 = Get-ChildItem -LiteralPath $build10 -Filter "x265-static.lib" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $library10) {
        throw (Get-SetupText "The x265 10-bit static library is missing." "未找到 x265 10-bit 静态库。")
    }

    $library10Path = $library10.FullName.Replace('\', '/')
    $library12Path = $library12.FullName.Replace('\', '/')
    Invoke-SetupBuildCommand `
        -DisplayName "x265 8/10/12-bit CLI configuration" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments (@("-S", $sourceRoot, "-B", $build8) + $commonArguments + @(
            "-DHIGH_BIT_DEPTH=OFF",
            "-DEXTRA_LIB=$library10Path;$library12Path",
            "-DLINKED_10BIT=ON",
            "-DLINKED_12BIT=ON",
            "-DENABLE_HDR10_PLUS=ON",
            "-DENABLE_CLI=ON"
        ))
    Invoke-SetupBuildCommand `
        -DisplayName "x265 8/10/12-bit CLI compilation" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments @("--build", $build8, "--config", "Release", "--target", "cli", "--parallel", $script:BuildJobs)
    $executable = Get-ChildItem -LiteralPath $build8 -Filter "x265.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        throw (Get-SetupText "The x265 executable is missing after compilation." "编译后未找到 x265 可执行文件。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.X265)) | Out-Null
    Copy-Item -LiteralPath $executable.FullName -Destination $script:ToolPaths.X265 -Force
    Add-StaticBuildArtifact "x265" $library12.FullName "x265-main12.lib"
    Add-StaticBuildArtifact "x265" $library10.FullName "x265-main10.lib"
    if ($script:BuildCacheRoot) {
        $library8 = Get-ChildItem -LiteralPath $build8 -Filter "x265-static.lib" -File -Recurse | Select-Object -First 1
        if ($library8) {
            Add-StaticBuildArtifact "x265" $library8.FullName "x265-main.lib"
        }
    }
    [IO.File]::WriteAllText(
        $script:ToolPaths.X265Version,
        "$($release.Version)`r`nhdr10plus-all-depths",
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-X265 {
    try {
        $output = Invoke-SetupCommand -FilePath $script:ToolPaths.X265 -Arguments @("--version")
        $help = Invoke-SetupCommand -FilePath $script:ToolPaths.X265 -Arguments @("--help") -AcceptedExitCodes @(0, 1)
        $buildMarker = [IO.File]::ReadAllText($script:ToolPaths.X265Version)
        return (
            $output.IndexOf("8bit+10bit+12bit", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $help.IndexOf("--dhdr10-info", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $help.IndexOf("--dolby-vision-profile", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $help.IndexOf("--dolby-vision-rpu", [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $buildMarker.IndexOf("hdr10plus-all-depths", [StringComparison]::OrdinalIgnoreCase) -ge 0
        )
    }
    catch {
        return $false
    }
}

function Get-SvtAv1Release {
    return Get-SvtAv1SourceRelease
}

function Get-InstalledSvtAv1Version {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.SvtAv1 -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.SvtAv1 -Arguments @("--version")
    $match = [regex]::Match($output, '\bv?(?<version>[0-9]+(?:\.[0-9]+){1,3})\b', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups['version'].Value } else { "" })
}

function Build-SvtAv1Executable {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$BuildRoot
    )

    $nasmPath = $script:ToolPaths.Nasm.Replace('\', '/')
    Invoke-SetupBuildCommand `
        -DisplayName "SVT-AV1 configuration" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments (@(
            "-S", $SourceRoot,
            "-B", $BuildRoot
        ) + @(Get-NinjaCMakeArguments) + @(
            "-DBUILD_SHARED_LIBS=OFF",
            "-DBUILD_TESTING=OFF",
            "-DBUILD_APPS=ON",
            "-DSVT_AV1_LTO=ON",
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
            "-DCMAKE_ASM_NASM_COMPILER=$nasmPath"
        ))
    Invoke-SetupBuildCommand `
        -DisplayName "SVT-AV1 compilation" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments @("--build", $BuildRoot, "--config", "Release", "--target", "SvtAv1EncApp", "--parallel", $script:BuildJobs)
    $executable = Get-ChildItem -LiteralPath $SourceRoot -Filter "SvtAv1EncApp.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        $executable = Get-ChildItem -LiteralPath $BuildRoot -Filter "SvtAv1EncApp.exe" -File -Recurse |
            Select-Object -First 1
    }
    if ($null -eq $executable) {
        throw (Get-SetupText "The SVT-AV1 executable is missing after compilation." "编译后未找到 SVT-AV1 可执行文件。")
    }
    if ($script:BuildCacheRoot) {
        $library = Get-ChildItem -LiteralPath $SourceRoot, $BuildRoot -Filter "SvtAv1Enc.lib" -File -Recurse |
            Select-Object -First 1
        if ($library) {
            Add-StaticBuildArtifact "svt-av1" $library.FullName $library.Name
        }
    }
    return $executable.FullName
}

function Install-SvtAv1 {
    param([string]$Version)

    $release = Get-SvtAv1Release
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "svt-av1-extracted"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $marker = Get-ChildItem -LiteralPath $extracted -Filter "enc_settings.c" -File -Recurse |
        Where-Object { $_.FullName -match '[\\/]Source[\\/]Lib[\\/]Globals[\\/]enc_settings\.c$' } |
        Select-Object -First 1
    if ($null -eq $marker) {
        throw (Get-SetupText "SVT-AV1 source directory is missing." "未找到 SVT-AV1 源码目录。")
    }
    $sourceRoot = $marker.Directory.Parent.Parent.Parent.FullName
    $executable = Build-SvtAv1Executable `
        -SourceRoot $sourceRoot `
        -BuildRoot (Join-Path $script:TempRoot "svt-av1-build")

    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.SvtAv1)) | Out-Null
    Copy-Item -LiteralPath $executable -Destination $script:ToolPaths.SvtAv1 -Force
}
function Test-SvtAv1 {
    return [bool](Get-InstalledSvtAv1Version)
}

function Get-FdkAacLibraryRelease {
    return Get-GitHubLatestTaggedSource `
        -Repository "mstorsjo/fdk-aac" `
        -TagPattern '^v(?<version>[0-9]+(?:\.[0-9]+){1,3})$' `
        -ArchiveBaseName "fdk-aac"
}

function Get-FdkAacRelease {
    return Get-GitHubLatestTaggedSource `
        -Repository "nu774/fdkaac" `
        -TagPattern '^v(?<version>[0-9]+(?:\.[0-9]+){1,3})$' `
        -ArchiveBaseName "fdkaac"
}

function Get-InstalledFdkAacVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.FdkAac -PathType Leaf)) {
        return ""
    }

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = (& $script:ToolPaths.FdkAac -h 2>&1 | Out-String)
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    # fdkaac returns 1 after printing its valid help/version banner.
    if ($exitCode -ne 0 -and $exitCode -ne 1) {
        return ""
    }
    $versionLine = $output.Replace("`r", "").Split([char]"`n") |
        Where-Object { $_.TrimStart().StartsWith("fdkaac ", [StringComparison]::OrdinalIgnoreCase) } |
        Select-Object -First 1
    if (-not $versionLine) {
        return ""
    }
    return $versionLine.Trim().Substring("fdkaac ".Length).Trim()
}

function Install-FdkAac {
    param([string]$Version)

    $libraryRelease = Get-FdkAacLibraryRelease
    $prefix = Join-Path $script:TempRoot "fdkaac-prefix"
    $restoredPrefix = Join-Path $script:TempRoot "fdkaac-restored-prefix"
    $libraryArchive = $null
    $libraryKey = $null
    if ($script:BuildCacheRoot) {
        $libraryArchive = Join-Path $script:BuildCacheRoot "fdkaac-library.zip"
        $libraryKey = Get-BuildFingerprint @($script:BuildRecipeHash, "fdkaac-library")
        $pkgConfig = Join-Path $restoredPrefix "lib\pkgconfig\fdk-aac.pc"
        if ((Invoke-BuildArtifactCache "restore" $libraryArchive $libraryKey $restoredPrefix) -eq "hit" -and
            (Test-Path -LiteralPath (Join-Path $restoredPrefix "lib\libfdk-aac.a") -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $restoredPrefix "lib\libfdk-xhe-aac.a") -PathType Leaf) -and
            (Test-Path -LiteralPath $pkgConfig -PathType Leaf) -and
            (Select-String -LiteralPath $pkgConfig -Pattern "^Version:\s+$([regex]::Escape($libraryRelease.Version))\s*$" -Quiet)) {
            $prefix = $restoredPrefix
            Write-SetupInfo "Restored FDK-AAC static libraries from the build cache." "已从构建缓存恢复 FDK-AAC 静态库。"
        }
    }

    if ($prefix -ne $restoredPrefix) {
        $archive = Join-Path $script:TempRoot $libraryRelease.Name
        $extracted = Join-Path $script:TempRoot "fdk-aac-extracted"
        Invoke-SetupDownload -Uri $libraryRelease.Uri -Destination $archive | Out-Null
        Expand-SetupZip -Archive $archive -Destination $extracted
        $cmakeFile = Get-ChildItem -LiteralPath $extracted -Filter "CMakeLists.txt" -File -Recurse |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "fdk-aac.pc.in") -PathType Leaf } |
            Select-Object -First 1
        if ($null -eq $cmakeFile) {
            throw (Get-SetupText "The FDK-AAC library source directory is missing." "未找到 FDK-AAC 库源码目录。")
        }
        $build = Join-Path $script:TempRoot "fdk-aac-build"
        $buildScriptContent = @(
            'set -euo pipefail',
            'export PATH=/ucrt64/bin:/usr/bin',
            'source=$1',
            'build=$2',
            'prefix=$3',
            'jobs=$4',
            'cmake -S "$source" -B "$build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -DBUILD_SHARED_LIBS=OFF -DBUILD_PROGRAMS=OFF -DFDK_AAC_INSTALL_CMAKE_CONFIG_MODULE=OFF -DFDK_AAC_INSTALL_PKGCONFIG_MODULE=ON -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_INSTALL_PREFIX="$prefix"',
            'cmake --build "$build" --parallel "$jobs"',
            'cmake --install "$build"',
            'sed -i ''s|^prefix=.*|prefix=${pcfiledir}/../..|'' "$prefix"/lib/pkgconfig/fdk*.pc'
        ) -join "`n"
        $buildScript = Write-SetupTempScript -Name "build-fdk-aac-library.sh" -Content $buildScriptContent
        Invoke-SetupBuildCommand `
            -DisplayName "FDK-AAC and xHE-AAC static libraries" `
            -FilePath $script:ToolPaths.Msys2Bash `
            -Arguments @(
                (ConvertTo-Msys2Path $buildScript),
                (ConvertTo-Msys2Path $cmakeFile.Directory.FullName),
                (ConvertTo-Msys2Path $build),
                (ConvertTo-Msys2Path $prefix),
                [string]$script:BuildJobs
            )
        if ($libraryArchive) {
            Invoke-BuildArtifactCache "save" $libraryArchive $libraryKey $prefix | Out-Null
        }
    }

    $cliRelease = Get-FdkAacRelease
    $cliArchive = Join-Path $script:TempRoot $cliRelease.Name
    $cliExtracted = Join-Path $script:TempRoot "fdkaac-extracted"
    Invoke-SetupDownload -Uri $cliRelease.Uri -Destination $cliArchive | Out-Null
    Expand-SetupZip -Archive $cliArchive -Destination $cliExtracted
    $cliConfigure = Get-ChildItem -LiteralPath $cliExtracted -Filter "configure.ac" -File -Recurse |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "src") -PathType Container } |
        Select-Object -First 1
    if ($null -eq $cliConfigure) {
        throw (Get-SetupText "The fdkaac source directory is missing." "未找到 fdkaac 源码目录。")
    }
    $cliScriptContent = @(
        'set -euo pipefail',
        'export PATH=/ucrt64/bin:/usr/bin',
        'cd "$1"',
        'prefix=$2',
        'jobs=$3',
        'autoreconf -fi',
        'PKG_CONFIG_PATH="$prefix/lib/pkgconfig" LDFLAGS="-static -static-libgcc" ./configure --host=x86_64-w64-mingw32 --prefix="$prefix" --disable-dependency-tracking --disable-shared --enable-static',
        'make -j"$jobs"'
    ) -join "`n"
    $cliScript = Write-SetupTempScript -Name "build-fdkaac.sh" -Content $cliScriptContent
    Invoke-SetupBuildCommand `
        -DisplayName "fdkaac static command-line build" `
        -FilePath $script:ToolPaths.Msys2Bash `
        -Arguments @(
            (ConvertTo-Msys2Path $cliScript),
            (ConvertTo-Msys2Path $cliConfigure.Directory.FullName),
            (ConvertTo-Msys2Path $prefix),
            [string]$script:BuildJobs
        )
    $executable = Get-ChildItem -LiteralPath $cliConfigure.Directory.FullName -Filter "fdkaac.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        throw (Get-SetupText "The fdkaac executable is missing after compilation." "编译后未找到 fdkaac 可执行文件。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.FdkAac)) | Out-Null
    Copy-Item -LiteralPath $executable.FullName -Destination $script:ToolPaths.FdkAac -Force
}

function Test-FdkAac {
    return [bool](Get-InstalledFdkAacVersion)
}

function Get-LibassRelease {
    return Get-GitHubLatestTaggedSource `
        -Repository "libass/libass" `
        -TagPattern '^(?<version>[0-9]+(?:\.[0-9]+){1,3})$' `
        -ArchiveBaseName "libass"
}

function Get-InstalledLibassVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Libass -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:ToolPaths.LibassVersion -PathType Leaf)) {
        return ""
    }
    return ([IO.File]::ReadAllText($script:ToolPaths.LibassVersion)).Trim()
}

function Install-Libass {
    param([string]$Version)

    $release = Get-LibassRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "libass-extracted"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $mesonFile = Get-ChildItem -LiteralPath $extracted -Filter "meson.build" -File -Recurse |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "RELEASEVERSION") -PathType Leaf } |
        Select-Object -First 1
    if ($null -eq $mesonFile) {
        throw (Get-SetupText "libass source directory is missing." "未找到 libass 源码目录。")
    }

    $build = Join-Path $script:TempRoot "libass-build"
    $buildScriptContent = @(
        'set -euo pipefail',
        'export PATH=/ucrt64/bin:/usr/bin',
        'source=$1',
        'build=$2',
        'jobs=$3',
        'meson setup "$build" "$source" --buildtype=release -Ddefault_library=shared -Dprefer_static=true -Db_lto=true -Dfontconfig=disabled -Ddirectwrite=enabled -Dlibunibreak=enabled -Dasm=enabled -Dtest=disabled -Dcompare=disabled -Dprofile=disabled -Dfuzz=disabled -Dcheckasm=disabled "-Dc_link_args=-static -static-libgcc" -Dc_winlibs=-lkernel32,-luser32,-lgdi32,-lwinspool,-lshell32,-lole32,-loleaut32,-luuid,-lcomdlg32,-ladvapi32,-lstdc++',
        'meson compile -C "$build" -j "$jobs"'
    ) -join "`n"
    $buildScript = Write-SetupTempScript -Name "build-libass.sh" -Content $buildScriptContent
    Invoke-SetupBuildCommand `
        -DisplayName "libass shared library with static dependencies" `
        -FilePath $script:ToolPaths.Msys2Bash `
        -Arguments @(
            (ConvertTo-Msys2Path $buildScript),
            (ConvertTo-Msys2Path $mesonFile.Directory.FullName),
            (ConvertTo-Msys2Path $build),
            [string]$script:BuildJobs
        )
    $library = Get-ChildItem -LiteralPath $build -Filter "*ass-9.dll" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $library) {
        throw (Get-SetupText "The libass-9 DLL is missing after compilation." "编译后未找到 libass-9 DLL。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.Libass)) | Out-Null
    Copy-Item -LiteralPath $library.FullName -Destination $script:ToolPaths.Libass -Force
    [IO.File]::WriteAllText(
        $script:ToolPaths.LibassVersion,
        $release.Version,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-Libass {
    if (-not (Get-InstalledLibassVersion)) {
        return $false
    }
    try {
        $objdump = Join-Path $script:ToolPaths.Msys2Root "ucrt64\bin\objdump.exe"
        if (Test-Path -LiteralPath $objdump -PathType Leaf) {
            $imports = Invoke-SetupCommand -FilePath $objdump -Arguments @("-p", $script:ToolPaths.Libass)
            if ($imports -match '(?i)DLL Name:\s+(?:libgcc|libstdc\+\+|libwinpthread|libfreetype|libfribidi|libharfbuzz|libunibreak|libiconv|libintl|libglib|libpcre|libgraphite|libbrotli|libbz2|libpng|zlib)[^\r\n]*\.dll') {
                return $false
            }
        }
        $pythonCode = "import ctypes; ctypes.WinDLL(r'$($script:ToolPaths.Libass)')"
        Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments @("-c", $pythonCode) | Out-Null
        return $true
    }
    catch {
        return $false
    }
}
function Get-VapourSynthClassicRelease {
    $cacheKey = "github:vapoursynth-classic:latest-source"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    try {
        $releases = @(Get-SetupJsonFromUri `
            -Uri ([Uri]"https://api.github.com/repos/AmusementClub/vapoursynth-classic/releases?per_page=100") `
            -CacheName "vapoursynth-classic-releases.json")
    }
    catch {
        $releases = @(Get-GitHubTagsFromGit -Repository "AmusementClub/vapoursynth-classic" |
            ForEach-Object { [pscustomobject]@{ draft = $false; tag_name = $_ } })
    }
    $candidates = @(
        foreach ($release in $releases) {
            if ([bool]$release.draft) {
                continue
            }
            $tag = ([string]$release.tag_name).Trim()
            $separatorIndex = $tag.IndexOf(".A", [StringComparison]::OrdinalIgnoreCase)
            if (-not $tag.StartsWith("R", [StringComparison]::OrdinalIgnoreCase) -or $separatorIndex -le 1) {
                continue
            }
            $releaseNumber = 0
            $apiNumber = 0
            if (-not [int]::TryParse($tag.Substring(1, $separatorIndex - 1), [ref]$releaseNumber) -or
                -not [int]::TryParse($tag.Substring($separatorIndex + 2), [ref]$apiNumber)) {
                continue
            }
            [pscustomobject]@{
                Version = "$releaseNumber.$apiNumber"
                Tag = $tag
                SortVersion = New-Object Version($releaseNumber, $apiNumber)
                Name = "vapoursynth-classic-$tag-source.zip"
                Uri = [Uri]"https://codeload.github.com/AmusementClub/vapoursynth-classic/zip/refs/tags/$tag"
            }
        }
    )
    if ($candidates.Count -eq 0) {
        throw (Get-SetupText `
            "No x64 vapoursynth-classic release was found." `
            "未找到 vapoursynth-classic 的 x64 发布版本。")
    }
    $result = $candidates | Sort-Object SortVersion -Descending | Select-Object -First 1
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-VapourSynthSourceDependencies {
    $cacheKey = "vapoursynth-source-dependencies"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }
    $dependencies = [ordered]@{}
    # Classic's resize integration uses the upstream v3.0 compatibility branch.
    foreach ($dependency in @(
        @{ Name = "zimg"; Repository = "AmusementClub/zimg"; Ref = "v3.0" },
        @{ Name = "libp2p"; Repository = "sekrit-twc/libp2p"; Ref = "HEAD" }
    )) {
        $repository = $dependency.Repository
        try {
            $commit = Get-SetupJsonFromUri -Uri ([Uri]"https://api.github.com/repos/$repository/commits/$($dependency.Ref)") -CacheName "vapoursynth-$($dependency.Name)-commit.json"
            $sha = [string]$commit.sha
        }
        catch {
            $ref = if ($dependency.Ref -eq "HEAD") { "HEAD" } else { "refs/heads/$($dependency.Ref)" }
            $refs = Invoke-SetupCommand -FilePath $script:ToolPaths.Git `
                -Arguments @("ls-remote", "--exit-code", "https://github.com/$repository.git", $ref)
            $match = [regex]::Match($refs, '(?m)^([0-9a-f]{40})\s')
            if (-not $match.Success) {
                throw
            }
            $sha = $match.Groups[1].Value
        }
        $dependencies[$dependency.Name] = [pscustomobject]@{
            Version = $sha
            Name = "vapoursynth-$($dependency.Name)-$sha.zip"
            Uri = [Uri]"https://codeload.github.com/$repository/zip/$sha"
        }
    }
    foreach ($dependency in @(
        @{ Name = "mimalloc"; Repository = "microsoft/mimalloc" },
        @{ Name = "AviSynthPlus"; Repository = "AviSynth/AviSynthPlus" }
    )) {
        $dependencies[$dependency.Name] = Get-GitHubLatestTaggedSource -Repository $dependency.Repository -TagPattern '^v(?<version>[0-9]+\.[0-9]+\.[0-9]+)$' -ArchiveBaseName "vapoursynth-$($dependency.Name)"
    }
    $script:ReleaseCache[$cacheKey] = $dependencies
    return $dependencies
}

function Get-InstalledVapourSynthClassicVersion {
    $marker = Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-classic-version.txt"
    foreach ($file in @(
        $marker,
        (Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-build.json"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "python-runtime.ini"),
        $script:ToolPaths.VsPipe,
        (Join-Path $script:ToolPaths.VapourSynthRoot "VapourSynth.dll"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "VSScript.dll"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth64\coreplugins\RemoveGrainVS.dll")
    )) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            return ""
        }
    }
    return ([IO.File]::ReadAllText($marker)).Trim()
}

function Install-VapourSynthClassic {
    param([string]$Version, [string]$Artifacts)

    $buildFromSource = -not $Artifacts
    if ($buildFromSource) {
        $dependencies = Get-VapourSynthSourceDependencies
        $dependencyVersions = [ordered]@{}
        foreach ($name in $dependencies.Keys) {
            $dependencyVersions[$name] = $dependencies[$name].Version
        }
    }
    else {
        $state = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Artifacts "vapoursynth-build.json") |
            ConvertFrom-Json
        $Version = [string]$state.version
        $dependencyVersions = $state.dependencies
    }
    $dependencyState = Join-Path $script:TempRoot "vapoursynth-dependencies.json"
    [IO.File]::WriteAllText($dependencyState, ($dependencyVersions | ConvertTo-Json), $script:Utf8Encoding)
    $buildArguments = @(
        (Join-Path $script:SetupDirectory "tools\build_vapoursynth_windows.py"),
        "--runtime-root", $script:ToolPaths.VapourSynthRoot,
        "--vspipe-path", $script:ToolPaths.VsPipe,
        "--version", $Version,
        "--dependencies", $dependencyState
    )
    if ($buildFromSource) {
        $release = Get-VapourSynthClassicRelease
        $archive = Join-Path $script:TempRoot $release.Name
        $extracted = Join-Path $script:TempRoot "vapoursynth-classic"
        Invoke-SetupDownload -Uri $release.Uri -Destination $archive | Out-Null
        Expand-SetupZip -Archive $archive -Destination $extracted
        $source = (Get-ChildItem -LiteralPath $extracted -Directory | Select-Object -First 1).FullName
        foreach ($name in $dependencies.Keys) {
            $dependency = $dependencies[$name]
            $dependencyArchive = Join-Path $script:TempRoot $dependency.Name
            $dependencyExtracted = Join-Path $script:TempRoot "vapoursynth-dependency-$name"
            Invoke-SetupDownload -Uri $dependency.Uri -Destination $dependencyArchive | Out-Null
            Expand-SetupZip -Archive $dependencyArchive -Destination $dependencyExtracted
            $dependencySource = Get-ChildItem -LiteralPath $dependencyExtracted -Directory | Select-Object -First 1
            Copy-Item -LiteralPath $dependencySource.FullName -Destination (Join-Path $source $name) -Recurse
        }
        $Artifacts = Join-Path $script:TempRoot "artifacts-vapoursynth-classic"
        $msbuild = Join-Path (Get-VisualStudioProperty "installationPath") "MSBuild\Current\Bin\MSBuild.exe"
        $buildArguments += @(
            "--source", $source,
            "--msbuild", $msbuild,
            "--cmake", $script:ToolPaths.CMake,
            "--ninja", $script:ToolPaths.Ninja,
            "--jobs", [string]$script:BuildJobs
        )
    }
    $buildArguments += @("--artifacts", $Artifacts)
    $displayName = Get-SetupText "VapourSynth source and system Python module" "VapourSynth 源码及系统 Python 模块"
    $build = {
        Invoke-SetupBuildCommand -DisplayName $displayName -FilePath $script:ToolPaths.Python -Arguments $buildArguments
    }
    if ($buildFromSource) {
        Invoke-VisualStudioBuild $build
    }
    else {
        & $build
    }
}

function Test-VapourSynthClassic {
    $installedVersion = Get-InstalledVapourSynthClassicVersion
    if (-not $installedVersion) {
        return $false
    }
    if (-not $script:BuildCacheRoot -and $installedVersion -ne (Get-VapourSynthClassicRelease).Version) {
        return $false
    }
    $dependencies = Get-VapourSynthSourceDependencies
    try {
        $statePath = Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-build.json"
        $state = Get-Content -Raw -Encoding UTF8 -LiteralPath $statePath | ConvertFrom-Json
        foreach ($name in $dependencies.Keys) {
            if ([string]$state.dependencies.$name -ne [string]$dependencies[$name].Version) {
                return $false
            }
        }
        $escapedStatePath = $statePath.Replace('\', '\\').Replace("'", "\'")
        $pythonCode = "import json,sys,vapoursynth as vs; state=json.load(open('$escapedStatePath',encoding='utf-8-sig')); assert state['python_tag']==sys.implementation.cache_tag; assert state['python_executable'].lower()==sys.executable.lower(); assert hasattr(vs.core,'rgvs'); print(vs.core.version())"
        Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments @("-c", $pythonCode) | Out-Null
        Invoke-SetupCommand -FilePath $script:ToolPaths.VsPipe -Arguments @("--version") | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Install-VapourSynthScripts {
    $installer = Join-Path $script:SetupDirectory "tools\install_vapoursynth_scripts.py"
    Write-SetupInfo `
        "Synchronizing repository-managed VapourSynth scripts and copyright notices." `
        "正在同步仓库中的 VapourSynth 脚本和版权说明。"
    $result = Invoke-SetupCommand `
        -FilePath $script:ToolPaths.Python `
        -Arguments @($installer, "--destination", $script:ToolPaths.VapourSynthSitePackages) |
        ConvertFrom-Json
    $status = if ($result.updated -gt 0) { "installed" } else { "satisfied" }
    Update-ManifestComponent "vapoursynth-scripts" $result.sha256 $status
    Write-SetupInfo `
        "Verified $($result.scripts) VapourSynth scripts and their notices; $($result.updated) files updated." `
        "已校验 $($result.scripts) 个 VapourSynth 脚本及其版权说明；更新了 $($result.updated) 个文件。"
}

function Install-VapourSynthUpstreamComponents {
    $installer = Join-Path $script:SetupDirectory "tools\install_vapoursynth_windows_components.py"
    $arguments = @(
        $installer,
        "--runtime-root", $script:ToolPaths.VapourSynthRoot,
        "--plugins-dir", $script:ToolPaths.VapourSynthPlugins,
        "--editor-path", $script:ToolPaths.VsEdit,
        "--editor-cache", $script:NativeToolCacheRoot,
        "--work-root", (Join-Path $script:TempRoot "vapoursynth-components"),
        "--msys2-root", $script:ToolPaths.Msys2Root,
        "--seven-zip", $script:ToolPaths.SevenZip,
        "--jobs", [string]$script:BuildJobs,
        "--language", $script:SelectedLanguage
    )
    $runInstaller = {
        param([string[]]$InstallArguments, [int[]]$AcceptedExitCodes = @(0))
        $env:BLURAYSUBTITLE_GITHUB_TOKEN = $script:GitHubApiToken
        try {
            Invoke-SetupBuildCommand -DisplayName "VapourSynth upstream components" `
                -FilePath $script:ToolPaths.Python -Arguments $InstallArguments -AcceptedExitCodes $AcceptedExitCodes
        }
        finally {
            $env:BLURAYSUBTITLE_GITHUB_TOKEN = $null
        }
    }
    if ($script:BuildCacheRoot) {
        $keyInputs = @(
            $script:BuildRecipeHash
            $script:VapourSynthComponentRecipeId
            (Get-FileHash -LiteralPath (Join-Path $script:SetupDirectory "tools\vapoursynth_plugin_versions.py")).Hash
            (Get-FileHash -LiteralPath (Join-Path $script:ToolPaths.VapourSynthRoot "VapourSynth.dll")).Hash
            (Get-FileHash -LiteralPath (Join-Path $script:ToolPaths.VapourSynthRoot "VSScript.dll")).Hash
            (Get-FileHash -LiteralPath $script:ToolPaths.Libass).Hash
        )
        $arguments += @("--build-cache", $script:BuildCacheRoot,
            "--build-fingerprint", (Get-BuildFingerprint $keyInputs))
        $msysRequired = 75
        & $runInstaller ($arguments + "--defer-msys2") @(0, $msysRequired)
        if ($LASTEXITCODE -eq $msysRequired) {
            Initialize-SetupBuildToolchain "msys2"
            & $runInstaller $arguments
        }
    }
    else {
        & $runInstaller $arguments
    }
    $statePath = Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-components.json"
    $state = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json
    foreach ($component in $state.components.PSObject.Properties) {
        Update-ManifestComponent ("vapoursynth-" + $component.Name) $component.Value.ref "satisfied"
    }
    $script:Manifest.components.Remove("vapoursynth-tools")
}

function Register-StageTwoComponents {
    Register-SetupComponent `
        -Name "python" `
        -EnglishName "Python runtime" `
        -ChineseName "Python 运行环境" `
        -GetInstalledVersion { Get-InstalledPythonVersion } `
        -GetAvailableVersion { $script:SelectedPythonRelease.Version } `
        -Install { param($Version) Install-PythonRuntime $Version } `
        -Verify { Test-PythonRuntime }

    Register-SetupComponent `
        -Name "7zip" `
        -EnglishName "7-Zip" `
        -ChineseName "7-Zip" `
        -GetInstalledVersion { Get-InstalledSevenZipVersion } `
        -GetAvailableVersion { (Get-SevenZipRelease).Version } `
        -Install { param($Version) Install-SevenZip $Version } `
        -Verify { Test-SevenZip }

    Register-SetupComponent `
        -Name "python-dependencies" `
        -EnglishName "Python dependencies" `
        -ChineseName "Python 依赖" `
        -GetInstalledVersion { Get-PythonDependenciesVersion } `
        -GetAvailableVersion { "1.0" } `
        -Install { param($Version) Install-PythonDependenciesWithFallback } `
        -Verify { Test-PythonDependencies }

    Register-SetupComponent `
        -Name "git" `
        -EnglishName "Git for Windows" `
        -ChineseName "Git for Windows" `
        -GetInstalledVersion { Get-InstalledGitVersion } `
        -GetAvailableVersion { (Get-GitRelease).Version } `
        -Install { param($Version) Install-Git $Version } `
        -Verify { Test-Git } `
        -ReuseInstalled:($Mode -eq "Build")

    if ($Mode -eq "Desktop") {
        Register-SetupComponent `
            -Name "python-system-path" `
            -EnglishName "Python and pip system PATH" `
            -ChineseName "Python 和 pip 系统 PATH" `
            -GetInstalledVersion { if (Test-PythonMachinePath) { "1.0" } else { "" } } `
            -GetAvailableVersion { "1.0" } `
            -Install { param($Version) Add-PythonToMachinePath } `
            -Verify { Test-PythonMachinePath }

        Register-SetupComponent `
            -Name "git-system-path" `
            -EnglishName "Git system PATH" `
            -ChineseName "Git 系统 PATH" `
            -GetInstalledVersion { if (Test-GitMachinePath) { "1.0" } else { "" } } `
            -GetAvailableVersion { "1.0" } `
            -Install { param($Version) Add-GitToMachinePath } `
            -Verify { Test-GitMachinePath }

        Register-SetupComponent `
            -Name "start-menu-shortcuts" `
            -EnglishName "Python and Git Start menu shortcuts" `
            -ChineseName "Python 和 Git 开始菜单快捷方式" `
            -GetInstalledVersion { if (Test-StartMenuShortcuts) { "1.0" } else { "" } } `
            -GetAvailableVersion { "1.0" } `
            -Install { param($Version) Install-StartMenuShortcuts } `
            -Verify { Test-StartMenuShortcuts }
    }

    $visualStudioEnglishName = "Visual Studio 2026 C++ Build Tools"
    $visualStudioChineseName = "Visual Studio 2026 C++ 编译工具"
    if ($Mode -eq "Desktop") {
        $script:DesktopVisualStudioEnterprise = Find-VerifiedVisualStudioEnterprise
        if ($script:DesktopVisualStudioEnterprise) {
            $visualStudioEnglishName = "Visual Studio Enterprise 2026"
            $visualStudioChineseName = $visualStudioEnglishName
        }
    }
    Register-SetupComponent `
        -Name "visual-studio-build-tools" `
        -EnglishName $visualStudioEnglishName `
        -ChineseName $visualStudioChineseName `
        -GetInstalledVersion { Get-VisualStudioProperty "installationVersion" } `
        -GetAvailableVersion { (Get-LatestVisualStudioRelease).Version } `
        -Install { param($Version) Install-VisualStudioBuildTools $Version } `
        -Verify { $null -ne $script:DesktopVisualStudioEnterprise -or (Test-VisualStudioBuildTools) } `
        -ReuseInstalled:($Mode -eq "Build" -or $null -ne $script:DesktopVisualStudioEnterprise)

    Register-SetupComponent `
        -Name "cmake" `
        -EnglishName "CMake" `
        -ChineseName "CMake" `
        -GetInstalledVersion { Get-InstalledCMakeVersion } `
        -GetAvailableVersion { (Get-CMakeRelease).Version } `
        -Install { param($Version) Install-CMake $Version } `
        -Verify { Test-CMake } `
        -ReuseInstalled:($Mode -eq "Build")

    Register-SetupComponent `
        -Name "ninja" `
        -EnglishName "Ninja" `
        -ChineseName "Ninja" `
        -GetInstalledVersion { Get-InstalledNinjaVersion } `
        -GetAvailableVersion { (Get-NinjaRelease).Version } `
        -Install { param($Version) Install-Ninja $Version } `
        -Verify { Test-Ninja } `
        -ReuseInstalled:($Mode -eq "Build")

    Register-SetupComponent `
        -Name "nasm" `
        -EnglishName "NASM" `
        -ChineseName "NASM" `
        -GetInstalledVersion { Get-InstalledNasmVersion } `
        -GetAvailableVersion { (Get-LatestNasmRelease).Version } `
        -Install { param($Version) Install-Nasm $Version } `
        -Verify { Test-Nasm } `
        -ReuseInstalled:($Mode -eq "Build")

    Register-SetupComponent `
        -Name "msys2" `
        -EnglishName "MSYS2 UCRT64" `
        -ChineseName "MSYS2 UCRT64" `
        -GetInstalledVersion { Get-InstalledMsys2Version } `
        -GetAvailableVersion { Get-SetupText "Latest repository versions" "仓库最新版本" } `
        -Install { param($Version) Install-Msys2 } `
        -Verify { Test-Msys2 } `
        -AlwaysRun

    Register-SetupComponent `
        -Name "msys2-packages" `
        -EnglishName "MSYS2 build packages" `
        -ChineseName "MSYS2 编译依赖包" `
        -GetInstalledVersion { Get-Msys2PackagesVersion } `
        -GetAvailableVersion { Get-SetupText "Latest repository versions" "仓库最新版本" } `
        -Install { param($Version) Install-Msys2Packages $Version } `
        -Verify { Test-Msys2Packages } `
        -AlwaysRun
}

function Register-StageThreeComponents {
    Register-SetupComponent `
        -Name "ffmpeg" `
        -EnglishName "FFmpeg and FFprobe" `
        -ChineseName "FFmpeg 和 FFprobe" `
        -GetInstalledVersion { Get-InstalledFfmpegVersion } `
        -GetAvailableVersion { (Get-FfmpegRelease).Version } `
        -Install { param($Version) Install-Ffmpeg $Version } `
        -Verify { Test-Ffmpeg } `
        -BuildToolchain "msys2"

    Register-SetupComponent `
        -Name "flac" `
        -EnglishName "FLAC" `
        -ChineseName "FLAC" `
        -GetInstalledVersion { Get-InstalledFlacVersion } `
        -GetAvailableVersion { (Get-FlacRelease).Version } `
        -Install { param($Version) Install-Flac $Version } `
        -Verify { Test-Flac }

    Register-SetupComponent `
        -Name "mkvtoolnix" `
        -EnglishName "MKVToolNix" `
        -ChineseName "MKVToolNix" `
        -GetInstalledVersion { Get-InstalledMkvToolNixVersion } `
        -GetAvailableVersion { (Get-MkvToolNixRelease).Version } `
        -Install { param($Version) Install-MkvToolNix $Version } `
        -Verify { Test-MkvToolNix }

    Register-SetupComponent `
        -Name "tsmuxer" `
        -EnglishName "tsMuxeR" `
        -ChineseName "tsMuxeR" `
        -GetInstalledVersion { Get-InstalledTsMuxerVersion } `
        -GetAvailableVersion { (Get-TsMuxerRelease).Version } `
        -Install { param($Version) Install-TsMuxer $Version } `
        -Verify { Test-TsMuxer }

    Register-SetupComponent `
        -Name "dovi-tool" `
        -EnglishName "dovi_tool" `
        -ChineseName "dovi_tool" `
        -GetInstalledVersion { Get-InstalledDoviToolVersion } `
        -GetAvailableVersion { (Get-DoviToolRelease).Version } `
        -Install { param($Version) Install-DoviTool $Version } `
        -Verify { Test-DoviTool }

    Register-SetupComponent `
        -Name "hdr10plus-tool" `
        -EnglishName "hdr10plus_tool" `
        -ChineseName "hdr10plus_tool" `
        -GetInstalledVersion { Get-InstalledHdr10PlusToolVersion } `
        -GetAvailableVersion { (Get-Hdr10PlusToolRelease).Version } `
        -Install { param($Version) Install-Hdr10PlusTool $Version } `
        -Verify { Test-Hdr10PlusTool }

}
function Register-StageFourComponents {
    Register-SetupComponent `
        -Name "x264" `
        -EnglishName "x264 8/10-bit encoder" `
        -ChineseName "x264 8/10-bit 编码器" `
        -GetInstalledVersion { Get-InstalledX264Version } `
        -GetAvailableVersion { (Get-X264Release).Version } `
        -Install { param($Version) Install-X264 $Version } `
        -Verify { Test-X264 } `
        -BuildToolchain "msys2"

    Register-SetupComponent `
        -Name "x265" `
        -EnglishName "x265 8/10/12-bit encoder" `
        -ChineseName "x265 8/10/12-bit 编码器" `
        -GetInstalledVersion { Get-InstalledX265Version } `
        -GetAvailableVersion { (Get-X265Release).Version } `
        -Install { param($Version) Invoke-VisualStudioBuild { Install-X265 $Version } } `
        -Verify { Test-X265 } `
        -BuildToolchain "msvc"

    Register-SetupComponent `
        -Name "svt-av1" `
        -EnglishName "SVT-AV1 encoder" `
        -ChineseName "SVT-AV1 编码器" `
        -GetInstalledVersion { Get-InstalledSvtAv1Version } `
        -GetAvailableVersion { (Get-SvtAv1Release).Version } `
        -Install { param($Version) Invoke-VisualStudioBuild { Install-SvtAv1 $Version } } `
        -Verify { Test-SvtAv1 } `
        -BuildToolchain "msvc"

    Register-SetupComponent `
        -Name "fdkaac" `
        -EnglishName "FDK-AAC and fdkaac" `
        -ChineseName "FDK-AAC 和 fdkaac" `
        -GetInstalledVersion { Get-InstalledFdkAacVersion } `
        -GetAvailableVersion { (Get-FdkAacRelease).Version } `
        -Install { param($Version) Install-FdkAac $Version } `
        -Verify { Test-FdkAac } `
        -BuildToolchain "msys2"

    Register-SetupComponent `
        -Name "libass" `
        -EnglishName "libass with static dependencies" `
        -ChineseName "静态依赖版 libass" `
        -GetInstalledVersion { Get-InstalledLibassVersion } `
        -GetAvailableVersion { (Get-LibassRelease).Version } `
        -Install { param($Version) Install-Libass $Version } `
        -Verify { Test-Libass } `
        -BuildToolchain "msys2"
}

function Register-StageFiveComponents {
    Register-SetupComponent `
        -Name "vapoursynth-classic" `
        -EnglishName "VapourSynth Classic and system Python module" `
        -ChineseName "VapourSynth Classic 和系统 Python 模块" `
        -GetInstalledVersion { Get-InstalledVapourSynthClassicVersion } `
        -GetAvailableVersion { (Get-VapourSynthClassicRelease).Version } `
        -Install { param($Version) Install-VapourSynthClassic $Version } `
        -Verify { Test-VapourSynthClassic } `
        -BuildToolchain "msvc"

}

function Invoke-WindowsSetup {
    $windows = Assert-SupportedWindows
    Write-SetupInfo `
        "Supported system detected: $($windows.Family) build $($windows.Build), $($windows.Architecture)." `
        "检测到受支持的系统：$($windows.Family) 内部版本 $($windows.Build)，$($windows.Architecture)。"

    Write-SetupInfo `
        "Parallel compilation workers: $script:BuildJobs" `
        "并行编译线程数：$script:BuildJobs"

    $temporaryDirectory = Initialize-SetupTempRoot
    Write-SetupInfo `
        "Using the system temporary directory: $temporaryDirectory" `
        "使用系统临时目录：$temporaryDirectory"

    $proxyDescription = Get-SystemProxyDescription
    $script:ProxyAddress = $proxyDescription
    Write-SetupInfo `
        "System proxy route: $proxyDescription" `
        "系统代理路由：$proxyDescription"

    Initialize-SetupManifest
    if ($Mode -eq "Build" -and $BuildCacheDirectory) {
        $script:BuildCacheRoot = Join-Path ([IO.Path]::GetFullPath($BuildCacheDirectory)) "artifacts"
        $script:NativeToolCacheRoot = $script:BuildCacheRoot
        $script:BuildRecipeHash = Get-BuildFingerprint @(
            $script:WindowsToolRecipeId
            (Get-FileHash -LiteralPath (Join-Path $script:SetupDirectory "tools\windows_build_cache.py")).Hash
            $script:WindowsToolPathRecipeId
        )
    }
    Initialize-PythonRuntimeSelection
    $script:Manifest.system = [ordered]@{
        family = $windows.Family
        caption = $windows.Caption
        build = $windows.Build
        version = $windows.Version
        installationType = $windows.InstallationType
        architecture = $windows.Architecture
        proxy = $proxyDescription
    }

    $probePath = Join-Path $script:TempRoot "setup-probe.tmp"
    [IO.File]::WriteAllText($probePath, "ok", (New-Object Text.UTF8Encoding($false)))
    if (-not (Test-Path -LiteralPath $probePath -PathType Leaf)) {
        throw (Get-SetupText `
            "Temporary directory write test failed." `
            "临时目录写入测试失败。")
    }

    Register-StageTwoComponents
    Register-StageThreeComponents
    Register-StageFourComponents
    Register-StageFiveComponents
    $buildTools = @($script:BuildToolchains.Values | ForEach-Object { $_ })
    foreach ($component in $script:RegisteredComponents.Values) {
        # Packaging needs cl.exe to generate the launchers even when all tool artifacts were restored.
        if ($script:BuildCacheRoot -and $component.Name -in $buildTools -and $component.Name -ne "visual-studio-build-tools") {
            continue
        }
        Invoke-SetupComponent $component
        if ($component.Name -eq "visual-studio-build-tools") {
            $script:PreparedBuildTools[$component.Name] = $true
        }
        if ($component.Name -eq "python") {
            Initialize-ConfiguredToolPaths
        }
    }
    Install-VapourSynthUpstreamComponents
    Install-VapourSynthScripts
    if ($Mode -eq "Build") {
        $script:Manifest.system.python_executable = $script:ToolPaths.Python
        $script:Manifest.system.seven_zip_executable = $script:ToolPaths.SevenZip
        $script:Manifest.system.download_cache_key = Get-BuildFingerprint @(
            (Get-PythonVersionFromExecutable $script:ToolPaths.Python)
            (Invoke-SetupCommand -FilePath $script:ToolPaths.Python -Arguments @(
                "-m", "pip", "list", "--format=freeze", "--disable-pip-version-check"
            ))
        )
        if ($script:BuildCacheRoot -and (Test-Path -LiteralPath $script:BuildCacheRoot -PathType Container)) {
            $archives = @(Get-ChildItem -LiteralPath $script:BuildCacheRoot -Filter "*.zip" -File | Sort-Object Name)
            if ($archives.Count) {
                $script:Manifest.system.build_cache_key = Get-BuildFingerprint @(
                    $archives | ForEach-Object { "$($_.Name)=$((Get-FileHash -LiteralPath $_.FullName).Hash)" }
                )
            }
        }
    }
    Save-SetupManifest

    if ($script:RestartRequired) {
        Write-SetupWarning `
            "Restart Windows before running the next setup stage." `
            "请重新启动 Windows 后再运行下一阶段。"
    }
}

$exitCode = 0
try {
    Invoke-WindowsSetup
}
catch {
    [Console]::Error.WriteLine("[BluraySubtitle][ERROR] " + $_.Exception.Message)
    $exitCode = 1
}
finally {
    Remove-SetupTempRoot
}

$global:LASTEXITCODE = $exitCode
