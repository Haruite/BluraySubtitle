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

    return Join-Path $PSHOME "powershell.exe"
}

function Start-ElevatedSetup {
    if (-not $PSCommandPath) {
        throw "The setup script path cannot be resolved."
    }

    $arguments = @("-NoProfile", "-NoExit", "-File", $PSCommandPath)

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
        [Console]::Error.WriteLine("Administrator permission is required. / 需要管理员权限。")
        return 1223
    }
}

# Elevation is the first operation performed by the setup script.
if (-not (Test-Administrator)) {
    Start-ElevatedSetup | Out-Null
    return
}

$script:Utf8Encoding = New-Object Text.UTF8Encoding($false)
[Console]::InputEncoding = $script:Utf8Encoding
[Console]::OutputEncoding = $script:Utf8Encoding
$OutputEncoding = $script:Utf8Encoding

$script:SelectedLanguage = "en"
$script:SystemTempRoot = ""
$script:TempRoot = ""
$commonApplicationData = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonApplicationData)
$script:ManifestPath = Join-Path $commonApplicationData "BluraySubtitle\environment-manifest.json"
$script:Manifest = $null
$script:RegisteredComponents = [ordered]@{}
$script:LatestPythonRelease = $null
$script:SelectedPythonRelease = $null

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

$script:SelectedLanguage = Select-SetupLanguage
$script:ProxyAddress = "DIRECT"
$script:RestartRequired = $false
$script:ReleaseCache = [ordered]@{}
$script:BuildJobs = [Math]::Max(1, [Environment]::ProcessorCount)
$script:ToolPaths = [ordered]@{
    SevenZip = "C:\Program Files\7-Zip\7z.exe"
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
    Msys2Version = "C:\msys64\bluraysubtitle-installer-version.txt"
    Ffmpeg = "C:\Software\ffmpeg.exe"
    Ffprobe = "C:\Software\ffprobe.exe"
    Flac = "C:\Software\flac.exe"
    FlacLibrary = "C:\Software\libFLAC.dll"
    Libass = "C:\Software\libass-9.dll"
    MkvToolNixRoot = "C:\Program Files\MKVToolNix"
    MkvMerge = "C:\Program Files\MKVToolNix\mkvmerge.exe"
    MkvInfo = "C:\Program Files\MKVToolNix\mkvinfo.exe"
    MkvExtract = "C:\Program Files\MKVToolNix\mkvextract.exe"
    MkvPropEdit = "C:\Program Files\MKVToolNix\mkvpropedit.exe"
    TsMuxer = "C:\Software\tsMuxeR.exe"
    DoviTool = "C:\Software\dovi_tool.exe"
    TrueHdd = "C:\Software\truehdd.exe"
    X264 = "C:\Software\x264.exe"
    X265 = "C:\Software\x265.exe"
    X265Version = "C:\Software\x265-version.txt"
    SvtAv1 = "C:\Software\SvtAv1EncApp.exe"
    FdkAac = "C:\Software\fdkaac.exe"
    LibassVersion = "C:\Software\libass-version.txt"
    VapourSynthRoot = "C:\Software\vapoursynth"
    VapourSynthPython = "C:\Software\vapoursynth\python.exe"
    VapourSynthSitePackages = "C:\Software\vapoursynth\Lib\site-packages"
    VapourSynthPlugins = "C:\Software\vapoursynth\vapoursynth64\plugins"
    VsPipe = "C:\Software\vapoursynth\vspipe.exe"
    VsEdit = "C:\Software\vapoursynth\vsedit.exe"
}
$script:RequiredVapourSynthPlugins = @(
    "addgrain.dll",
    "assrender.dll",
    "bilateral.dll",
    "descale.dll",
    "dfttest.dll",
    "eedi2.dll",
    "eedi3m.dll",
    "f3kdb.dll",
    "fmtconv.dll",
    "libsangnom.dll",
    "libvslsmashsource.dll",
    "mvtools.dll",
    "neo-f3kdb.dll",
    "vsnlm_ispc.dll",
    "zsmooth.dll"
)
$script:RequiredVapourSynthScripts = @(
    "havsfunc.py",
    "mvsfunc.py"
)
$script:PythonPackages = @(
    [pscustomobject]@{ Distribution = "pip"; Import = "import pip" },
    [pscustomobject]@{ Distribution = "pycountry"; Import = "import pycountry" },
    [pscustomobject]@{ Distribution = "PyQt6"; Import = "from PyQt6 import QtCore" },
    [pscustomobject]@{ Distribution = "librosa"; Import = "import librosa" },
    [pscustomobject]@{ Distribution = "pillow"; Import = "from PIL import Image" },
    [pscustomobject]@{ Distribution = "matplotlib"; Import = "import matplotlib" }
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
        [Parameter(Mandatory = $true)][string]$Chinese
    )

    Write-Host ("[BluraySubtitle][SETUP] " + (Get-SetupText $English $Chinese)) -ForegroundColor Cyan
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

    $isWindows10 = $caption -match '(?i)\bWindows 10\b' -and $build -ge 10240 -and $build -lt 22000
    $isWindows11 = $caption -match '(?i)\bWindows 11\b' -and $build -ge 22000
    $isWorkstation = $productType -eq 1
    $isAmd64 = [Environment]::Is64BitOperatingSystem -and $processorArchitecture -eq 9

    if (-not $isWorkstation -or (-not $isWindows10 -and -not $isWindows11)) {
        throw (Get-SetupText `
            "Only Windows 10 and Windows 11 workstation editions are supported. Detected: $caption (build $build)." `
            "仅支持 Windows 10 和 Windows 11 工作站版本。检测到：$caption（内部版本 $build）。")
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

    $family = if ($isWindows11) { "Windows 11" } else { "Windows 10" }
    return [pscustomobject]@{
        Family = $family
        Caption = $caption
        Build = $build
        Version = [string]$operatingSystem.Version
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
    $testUri = [Uri]"https://github.com/"
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
        [ValidateRange(1, 5)][int]$Attempts = 3
    )

    if (-not $script:TempRoot -or -not (Test-PathIsUnderRoot $Destination $script:TempRoot)) {
        throw (Get-SetupText `
            "Downloads may only be written inside the setup temporary directory." `
            "下载文件只能写入安装临时目录。")
    }

    $destinationDirectory = Split-Path -Parent $Destination
    [IO.Directory]::CreateDirectory($destinationDirectory) | Out-Null
    $fileName = [IO.Path]::GetFileName($Destination)
    $client = New-SetupHttpClient
    try {
        for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
            Write-SetupInfo `
                "Downloading $fileName (attempt $attempt/$Attempts): $Uri" `
                "正在下载 $fileName（第 $attempt/$Attempts 次）：$Uri"
            try {
                $response = $client.GetAsync(
                    $Uri,
                    [Net.Http.HttpCompletionOption]::ResponseHeadersRead
                ).GetAwaiter().GetResult()
                try {
                    $response.EnsureSuccessStatusCode() | Out-Null
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
        [int[]]$AcceptedExitCodes = @(0, 3010)
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw (Get-SetupText "Installer not found: $FilePath" "未找到安装程序：$FilePath")
    }

    $installerName = [IO.Path]::GetFileName($FilePath)
    Write-SetupInfo `
        "Running installer: $installerName" `
        "正在运行安装程序：$installerName"
    $argumentLine = ($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join " "
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
    $release = Get-SetupJsonFromUri `
        -Uri ([Uri]"https://api.github.com/repos/$Repository/releases/latest") `
        -CacheName "$safeName-latest.json"
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
        Uri = [Uri]$asset.browser_download_url
        Sha256 = $sha256
        Size = [long]$asset.size
        AssetUpdatedAtUtc = [string]$asset.updated_at
        ReleaseBody = [string]$release.body
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
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
    $tags = @(Get-SetupJsonFromUri `
        -Uri ([Uri]"https://api.github.com/repos/$Repository/tags?per_page=100") `
        -CacheName "$safeName-tags.json")
    $candidates = @(
        foreach ($tag in $tags) {
            $tagName = [string]$tag.name
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
        [string[]]$Arguments = @()
    )

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        throw (Get-SetupText "Build executable not found: $FilePath" "未找到编译程序：$FilePath")
    }
    Write-SetupInfo "Running build step: $DisplayName" "正在执行编译步骤：$DisplayName"
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host ([string]$_) }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw (Get-SetupText `
            "Build step failed with exit code ${exitCode}: $DisplayName" `
            "编译步骤执行失败，退出码 ${exitCode}：$DisplayName")
    }
    Write-SetupInfo "Build step completed: $DisplayName" "编译步骤完成：$DisplayName"
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

function Get-PythonReleaseByVersion {
    param([Parameter(Mandatory = $true)][string]$Version)

    return [pscustomobject]@{
        Version = $Version
        Name = "python-$Version-amd64.exe"
        Uri = [Uri]"https://www.python.org/ftp/python/$Version/python-$Version-amd64.exe"
        Sha256 = ""
    }
}

function Get-LatestPythonRelease {
    $version = Get-PythonStableVersions | Select-Object -First 1
    return Get-PythonReleaseByVersion $version
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
    $fallbackVersion = Get-PythonStableVersions |
        Where-Object {
            $candidate = ConvertTo-ComparableVersion $_
            $candidate.Major -eq $currentVersion.Major -and
            $candidate.Minor -eq $targetMinor
        } |
        Select-Object -First 1
    if (-not $fallbackVersion) {
        throw (Get-SetupText `
            "Unable to determine the previous stable Python minor release." `
            "无法确定上一个 Python 稳定次版本。")
    }
    return Get-PythonReleaseByVersion $fallbackVersion
}

function Set-PythonToolPathsForVersion {
    param([Parameter(Mandatory = $true)][string]$Version)

    $parsedVersion = ConvertTo-ComparableVersion $Version
    $directoryName = "Python{0}{1}" -f $parsedVersion.Major, $parsedVersion.Minor
    $root = Join-Path "C:\Program Files" $directoryName
    $script:ToolPaths.PythonRoot = $root
    $script:ToolPaths.Python = Join-Path $root "python.exe"
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
            $selectedRelease = Get-PythonReleaseByVersion ([string]$state.version)
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

function Get-LatestPyPiVersion {
    param([Parameter(Mandatory = $true)][string]$Distribution)

    $cacheKey = "pypi:$Distribution"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return [string]$script:ReleaseCache[$cacheKey]
    }
    $metadata = Get-SetupJsonFromUri `
        -Uri ([Uri]"https://pypi.org/pypi/$Distribution/json") `
        -CacheName "pypi-$($Distribution.ToLowerInvariant()).json"
    $version = [string]$metadata.info.version
    if (-not $version) {
        throw (Get-SetupText `
            "Unable to determine the latest PyPI version for $Distribution." `
            "无法确定 $Distribution 的最新 PyPI 版本。")
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
        [Parameter(Mandatory = $true)][scriptblock]$Verify
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

function Invoke-SetupComponent {
    param([Parameter(Mandatory = $true)]$Component)

    $displayName = Get-SetupText $Component.EnglishName $Component.ChineseName
    Write-SetupInfo "Checking $displayName" "正在检查 $displayName"

    $installedVersion = [string](& $Component.GetInstalledVersion)
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

    Write-SetupInfo `
        "Checking the target version/status for $displayName." `
        "正在查询 $displayName 的目标版本/状态。"
    $availableVersion = [string](& $Component.GetAvailableVersion)
    Write-SetupInfo `
        "$displayName target version/status: $availableVersion" `
        "$displayName 目标版本/状态：$availableVersion"

    $needsInstall = -not $installedVersion
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
        Write-SetupInfo `
            "$displayName verification succeeded." `
            "$displayName 验证成功。"
        $installedVersion = [string](& $Component.GetInstalledVersion)
        Update-ManifestComponent $Component.Name $installedVersion "installed"
        Write-SetupInfo `
            "$displayName installation/configuration completed: $installedVersion" `
            "$displayName 安装/配置完成：$installedVersion"
        return
    }

    Update-ManifestComponent $Component.Name $installedVersion "satisfied"
    Write-SetupInfo `
        "$displayName is already satisfied; skipping installation." `
        "$displayName 已满足要求，跳过安装。"
}
function Invoke-RegisteredSetupComponents {
    foreach ($component in $script:RegisteredComponents.Values) {
        Invoke-SetupComponent $component
    }
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
    Invoke-SetupDownload -Uri $release.Uri -Destination $installer -Sha256 $release.Sha256 | Out-Null
    Invoke-SetupInstaller -FilePath $installer -Arguments @("/S")
}

function Test-SevenZip {
    $version = Get-InstalledSevenZipVersion
    if (-not $version) {
        return $false
    }
    return (Compare-SetupVersion $version "23.00") -ge 0
}

function Get-PythonVersionFromExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $Path -Arguments @("--version")
    $match = [regex]::Match($output, 'Python\s+([0-9]+\.[0-9]+\.[0-9]+)', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Get-DetectedPythonInstallation {
    $candidatePaths = @(
        $script:ToolPaths.Python,
        "C:\Software\Python\python.exe"
    )
    foreach ($registryRoot in @(
        [Microsoft.Win32.Registry]::LocalMachine,
        [Microsoft.Win32.Registry]::CurrentUser
    )) {
        $pythonCore = $registryRoot.OpenSubKey("Software\Python\PythonCore", $false)
        if ($null -eq $pythonCore) {
            continue
        }
        try {
            foreach ($versionKeyName in $pythonCore.GetSubKeyNames()) {
                $installKey = $pythonCore.OpenSubKey("$versionKeyName\InstallPath", $false)
                if ($null -eq $installKey) {
                    continue
                }
                try {
                    $executablePath = [string]$installKey.GetValue(
                        "ExecutablePath",
                        "",
                        [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                    )
                    if (-not $executablePath) {
                        $installRoot = [string]$installKey.GetValue(
                            "",
                            "",
                            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
                        )
                        if ($installRoot) {
                            $executablePath = Join-Path $installRoot "python.exe"
                        }
                    }
                    if ($executablePath) {
                        $candidatePaths += $executablePath
                    }
                }
                finally {
                    $installKey.Dispose()
                }
            }
        }
        finally {
            $pythonCore.Dispose()
        }
    }

    $installations = @(
        $candidatePaths |
            Where-Object { $_ } |
            Select-Object -Unique |
            ForEach-Object {
                $detectedVersion = Get-PythonVersionFromExecutable $_
                if ($detectedVersion) {
                    $root = Split-Path -Parent $_
                    [pscustomobject]@{
                        Version = $detectedVersion
                        Executable = $_
                        Root = $root
                        Scripts = Join-Path $root "Scripts"
                    }
                }
            }
    )
    $targetExecutable = [IO.Path]::GetFullPath($script:ToolPaths.Python)
    return $installations |
        Where-Object {
            [IO.Path]::GetFullPath($_.Executable) -eq $targetExecutable
        } |
        Select-Object -First 1
}

function Get-InstalledPythonVersion {
    $installation = Get-DetectedPythonInstallation
    if ($null -eq $installation) {
        return ""
    }
    return $installation.Version
}

function Get-ActivePythonExecutable {
    $installation = Get-DetectedPythonInstallation
    if ($null -eq $installation) {
        return ""
    }
    return $installation.Executable
}

function Install-PythonRuntime {
    param([string]$Version)

    Set-PythonToolPathsForVersion $Version
    $release = Get-PythonReleaseByVersion $Version
    $installer = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload -Uri $release.Uri -Destination $installer | Out-Null
    Assert-ValidAuthenticodeSignature $installer
    [IO.Directory]::CreateDirectory($script:ToolPaths.PythonRoot) | Out-Null
    $installLog = Join-Path $script:TempRoot "python-install.log"
    Invoke-SetupInstaller -FilePath $installer -Arguments @(
        "/quiet",
        "/log", $installLog,
        "InstallAllUsers=1",
        "TargetDir=$($script:ToolPaths.PythonRoot)",
        "PrependPath=0",
        "Include_launcher=1",
        "InstallLauncherAllUsers=1",
        "Include_pip=1",
        "Include_test=0",
        "Include_doc=0",
        "Shortcuts=0"
    )
}

function Test-PythonRuntime {
    $python = Get-ActivePythonExecutable
    if (-not $python) {
        return $false
    }
    try {
        Invoke-SetupCommand -FilePath $python -Arguments @(
            "-c",
            "import ssl, sqlite3, ctypes, ensurepip; print('ok')"
        ) | Out-Null
        return $true
    }
    catch {
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
    param([Parameter(Mandatory = $true)][string]$Distribution)

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
    if (-not (Test-PythonDependencies)) {
        return ""
    }
    foreach ($package in $script:PythonPackages) {
        $distribution = [string]$package.Distribution
        $installedVersion = Get-PythonPackageVersion $distribution
        $availableVersion = Get-LatestPyPiVersion $distribution
        if (
            -not $installedVersion -or
            (Compare-SetupVersion $installedVersion $availableVersion) -lt 0
        ) {
            return ""
        }
    }
    return "1.0"
}

function Install-AllPythonDependencies {
    foreach ($package in $script:PythonPackages) {
        $distribution = [string]$package.Distribution
        $importStatement = [string]$package.Import
        Write-SetupInfo `
            "Installing Python package $distribution" `
            "正在安装 Python 包 $distribution"
        Install-PythonPackage $distribution
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
        Install-PythonRuntime $fallbackRelease.Version
        if (-not (Test-PythonRuntime)) {
            throw (Get-SetupText `
                "The fallback Python runtime failed verification." `
                "回退后的 Python 运行环境验证失败。")
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

function Get-VisualStudioWherePath {
    return Join-Path $script:ToolPaths.VisualStudioInstaller "vswhere.exe"
}

function Get-VisualStudioInstallationPath {
    $vswhere = Get-VisualStudioWherePath
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        return ""
    }
    try {
        return Invoke-SetupCommand -FilePath $vswhere -Arguments @(
            "-latest",
            "-version", "[18.0,19.0)",
            "-products", "Microsoft.VisualStudio.Product.BuildTools",
            "-requires", "Microsoft.VisualStudio.Workload.VCTools",
            "-property", "installationPath"
        )
    }
    catch {
        return ""
    }
}

function Get-InstalledVisualStudioVersion {
    $vswhere = Get-VisualStudioWherePath
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        return ""
    }
    try {
        return Invoke-SetupCommand -FilePath $vswhere -Arguments @(
            "-latest",
            "-version", "[18.0,19.0)",
            "-products", "Microsoft.VisualStudio.Product.BuildTools",
            "-requires", "Microsoft.VisualStudio.Workload.VCTools",
            "-property", "installationVersion"
        )
    }
    catch {
        return ""
    }
}

function Install-VisualStudioBuildTools {
    param([string]$Version)

    $installationPath = Get-VisualStudioInstallationPath
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
    $installationPath = Get-VisualStudioInstallationPath
    if (-not $installationPath) {
        return $false
    }
    $compiler = Get-ChildItem -LiteralPath (Join-Path $installationPath "VC\Tools\MSVC") `
        -Filter "cl.exe" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\bin\\Hostx64\\x64\\cl\.exe$' } |
        Select-Object -First 1
    $msbuild = Join-Path $installationPath "MSBuild\Current\Bin\MSBuild.exe"
    $windowsSdkHeaders = Get-ChildItem -LiteralPath "C:\Program Files (x86)\Windows Kits\10\Include" `
        -Filter "Windows.h" -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\um\\Windows\.h$' } |
        Select-Object -First 1
    return $null -ne $compiler -and
        (Test-Path -LiteralPath $msbuild -PathType Leaf) -and
        $null -ne $windowsSdkHeaders
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
    Invoke-SetupDownload -Uri $release.Uri -Destination $installer -Sha256 $release.Sha256 | Out-Null
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
    return [bool](Get-InstalledCMakeVersion)
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
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive -Sha256 $release.Sha256 | Out-Null
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

function Get-Msys2Release {
    $release = Get-GitHubLatestReleaseAsset `
        -Repository "msys2/msys2-installer" `
        -AssetPattern '^msys2-base-x86_64-latest\.sfx\.exe$'
    try {
        $assetUpdatedAt = [DateTimeOffset]::Parse(
            $release.AssetUpdatedAtUtc,
            [Globalization.CultureInfo]::InvariantCulture
        )
    }
    catch {
        throw (Get-SetupText `
            "Unable to parse the MSYS2 asset update time." `
            "无法解析 MSYS2 发布文件的更新时间。")
    }
    return [pscustomobject]@{
        Version = $assetUpdatedAt.UtcDateTime.ToString(
            "yyyy.MM.dd.HHmmss",
            [Globalization.CultureInfo]::InvariantCulture
        )
        Name = $release.Name
        Uri = $release.Uri
        Sha256 = $release.Sha256
    }
}

function Get-InstalledMsys2Version {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Msys2Bash -PathType Leaf)) {
        return ""
    }
    if (Test-Path -LiteralPath $script:ToolPaths.Msys2Version -PathType Leaf) {
        return ([IO.File]::ReadAllText($script:ToolPaths.Msys2Version)).Trim()
    }
    return ""
}

function Install-Msys2 {
    param([string]$Version)

    $release = Get-Msys2Release
    $pacman = Join-Path $script:ToolPaths.Msys2Root "usr\bin\pacman.exe"
    $reuseExistingCore =
        (Test-Path -LiteralPath $script:ToolPaths.Msys2Bash -PathType Leaf) -and
        (Test-Path -LiteralPath $pacman -PathType Leaf)
    if ($reuseExistingCore) {
        Write-SetupInfo `
            "Existing MSYS2 core files detected; skipping the base archive download and resuming initialization." `
            "检测到现有 MSYS2 核心文件；跳过基础包下载并继续初始化。"
    }
    else {
        $installer = Join-Path $script:TempRoot $release.Name
        Invoke-SetupDownload -Uri $release.Uri -Destination $installer -Sha256 $release.Sha256 | Out-Null
        if (-not $release.Sha256) {
            $checksumPath = "$installer.sha256"
            try {
                Invoke-SetupDownload `
                    -Uri ([Uri]($release.Uri.AbsoluteUri + ".sha256")) `
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
    [IO.File]::WriteAllText(
        $script:ToolPaths.Msys2Version,
        $release.Version,
        (New-Object Text.UTF8Encoding($false))
    )
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
        Invoke-SetupCommand -FilePath $script:ToolPaths.Msys2Bash -Arguments @("-lc", "true") | Out-Null
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
    return Invoke-SetupCommand `
        -FilePath $pacman `
        -Arguments $effectiveArguments `
        -AcceptedExitCodes $AcceptedExitCodes
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

    Write-SetupInfo "Installing missing MSYS2 build packages without a full system upgrade." "正在安装缺少的 MSYS2 编译包，不执行完整系统升级。"
    Invoke-Msys2Pacman -Arguments (@("--noconfirm", "--needed", "-S") + $script:Msys2Packages) | Out-Null
}

function Test-Msys2Packages {
    return (Get-Msys2PackagesVersion) -eq "1.0"
}

function Get-FfmpegRelease {
    $cacheKey = "ffmpeg-gyan-release-essentials"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $version = (Get-SetupTextFromUri `
        -Uri ([Uri]"https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.7z.ver") `
        -CacheName "ffmpeg-release-essentials.7z.ver").Trim()
    if ($version -notmatch '^[0-9]+(?:\.[0-9]+){1,3}$') {
        throw (Get-SetupText "Unable to parse the latest FFmpeg release version." "无法解析 FFmpeg 最新发布版本。")
    }
    $checksumText = Get-SetupTextFromUri `
        -Uri ([Uri]"https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.7z.sha256") `
        -CacheName "ffmpeg-release-essentials.7z.sha256"
    $checksumMatch = [regex]::Match($checksumText, '\b([0-9a-fA-F]{64})\b')
    if (-not $checksumMatch.Success) {
        throw (Get-SetupText "Unable to parse the official FFmpeg SHA-256 checksum." "无法解析 FFmpeg 官方 SHA-256。")
    }
    $result = [pscustomobject]@{
        Version = $version
        Name = "ffmpeg-release-essentials.7z"
        Uri = [Uri]"https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.7z"
        Sha256 = $checksumMatch.Groups[1].Value
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-InstalledFfmpegVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.Ffmpeg -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:ToolPaths.Ffprobe -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.Ffmpeg -Arguments @("-version")
    $match = [regex]::Match($output, 'ffmpeg version\s+([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-Ffmpeg {
    param([string]$Version)

    $release = Get-FfmpegRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "ffmpeg-extracted"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupArchiveWithSevenZip -Archive $archive -Destination $extracted
    $ffmpegExecutable = Get-ChildItem -LiteralPath $extracted -Filter "ffmpeg.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $ffmpegExecutable) {
        throw (Get-SetupText "ffmpeg.exe is missing from the release archive." "发布压缩包中缺少 ffmpeg.exe。")
    }
    $ffprobeExecutable = Join-Path $ffmpegExecutable.DirectoryName "ffprobe.exe"
    if (-not (Test-Path -LiteralPath $ffprobeExecutable -PathType Leaf)) {
        throw (Get-SetupText "ffprobe.exe is missing from the release archive." "发布压缩包中缺少 ffprobe.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.Ffmpeg)) | Out-Null
    Copy-Item -LiteralPath $ffmpegExecutable.FullName -Destination $script:ToolPaths.Ffmpeg -Force
    Copy-Item -LiteralPath $ffprobeExecutable -Destination $script:ToolPaths.Ffprobe -Force
}

function Test-Ffmpeg {
    $version = Get-InstalledFfmpegVersion
    if (-not $version) {
        return $false
    }
    try {
        $output = Invoke-SetupCommand -FilePath $script:ToolPaths.Ffprobe -Arguments @("-version")
        return $output -match 'ffprobe version\s+[0-9]'
    }
    catch {
        return $false
    }
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
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive -Sha256 $release.Sha256 | Out-Null
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
    $name = "mkvtoolnix-64-bit-$version-setup.exe"
    $checksumText = Get-SetupTextFromUri `
        -Uri ([Uri]"https://mkvtoolnix.download/windows/releases/$version/sha256sums.txt") `
        -CacheName "mkvtoolnix-$version-sha256sums.txt"
    $checksumPattern = '(?im)^([0-9a-fA-F]{64})\s+' + [regex]::Escape($name) + '\s*$'
    $checksumMatch = [regex]::Match($checksumText, $checksumPattern)
    if (-not $checksumMatch.Success) {
        throw (Get-SetupText "Unable to find the MKVToolNix installer SHA-256 checksum." "无法找到 MKVToolNix 安装程序的 SHA-256。")
    }
    $result = [pscustomobject]@{
        Version = $version
        Name = $name
        Uri = [Uri]"https://mkvtoolnix.download/windows/releases/$version/$name"
        Sha256 = $checksumMatch.Groups[1].Value
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-InstalledMkvToolNixVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.MkvMerge -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.MkvMerge -Arguments @("--version")
    $match = [regex]::Match($output, 'mkvmerge\s+v([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-MkvToolNix {
    param([string]$Version)

    $release = Get-MkvToolNixRelease
    $installer = Join-Path $script:TempRoot $release.Name
    Invoke-SetupDownload -Uri $release.Uri -Destination $installer -Sha256 $release.Sha256 | Out-Null
    Assert-ValidAuthenticodeSignature $installer
    Invoke-SetupInstaller -FilePath $installer -Arguments @("/S")
}

function Test-MkvToolNix {
    if (-not (Get-InstalledMkvToolNixVersion)) {
        return $false
    }
    foreach ($path in @(
        $script:ToolPaths.MkvInfo,
        $script:ToolPaths.MkvMerge,
        $script:ToolPaths.MkvPropEdit,
        $script:ToolPaths.MkvExtract
    )) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            return $false
        }
    }
    return $true
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
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive -Sha256 $release.Sha256 | Out-Null
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
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive -Sha256 $release.Sha256 | Out-Null
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

function Get-TrueHddRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "truehdd/truehdd" `
        -AssetPattern '^truehdd-[0-9]+(?:\.[0-9]+){1,3}-x86_64-pc-windows-msvc\.zip$'
}

function Get-InstalledTrueHddVersion {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.TrueHdd -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.TrueHdd -Arguments @("--version")
    $match = [regex]::Match($output, 'truehdd\s+([0-9]+(?:\.[0-9]+){1,3})', 'IgnoreCase')
    return $(if ($match.Success) { $match.Groups[1].Value } else { "" })
}

function Install-TrueHdd {
    param([string]$Version)

    $release = Get-TrueHddRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "truehdd-extracted"
    Invoke-SetupDownload -Uri $release.Uri -Destination $archive -Sha256 $release.Sha256 | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $executable = Get-ChildItem -LiteralPath $extracted -Filter "truehdd.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $executable) {
        throw (Get-SetupText "truehdd.exe is missing from the release archive." "发布压缩包中缺少 truehdd.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.TrueHdd)) | Out-Null
    Copy-Item -LiteralPath $executable.FullName -Destination $script:ToolPaths.TrueHdd -Force
}

function Test-TrueHdd {
    return [bool](Get-InstalledTrueHddVersion)
}
function Get-X264Release {
    $release = Get-GitHubLatestReleaseAsset `
        -Repository "jpsdr/x264" `
        -AssetPattern '^x264_tmod_r[0-9]+\.7z$'
    if ($release.ReleaseBody -notmatch '(?i)x86/x64\s+8bits/10bits') {
        throw (Get-SetupText `
            "The x264 release does not confirm x64 8/10-bit support." `
            "x264 发布信息未确认支持 x64 8/10-bit。")
    }
    if ($release.Size -le 0) {
        throw (Get-SetupText `
            "The x264 release does not provide an asset size." `
            "x264 发布信息未提供文件大小。")
    }
    return $release
}

function Get-InstalledX264Version {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.X264 -PathType Leaf)) {
        return ""
    }
    $output = Invoke-SetupCommand -FilePath $script:ToolPaths.X264 -Arguments @("--version")
    $match = [regex]::Match($output, '\bx264\s+[0-9]+\.[0-9]+\.(?<revision>[0-9]+)\b', 'IgnoreCase')
    if (-not $match.Success) {
        $match = [regex]::Match($output, '\br(?<revision>[0-9]+)\b', 'IgnoreCase')
    }
    return $(if ($match.Success) { "r$($match.Groups['revision'].Value)" } else { "" })
}

function Install-X264 {
    param([string]$Version)

    $release = Get-X264Release
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "x264-extracted"
    Invoke-SetupDownload `
        -Uri $release.Uri `
        -Destination $archive `
        -Sha256 $release.Sha256 `
        -ExpectedSize $release.Size | Out-Null
    Expand-SetupArchiveWithSevenZip -Archive $archive -Destination $extracted
    $executable = Join-Path $extracted "winthread\x264_x64.exe"
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw (Get-SetupText `
            "The x264 Release archive is missing winthread\x264_x64.exe." `
            "x264 Release 压缩包中缺少 winthread\x264_x64.exe。")
    }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($script:ToolPaths.X264)) | Out-Null
    Copy-Item -LiteralPath $executable -Destination $script:ToolPaths.X264 -Force
}

function Test-X264 {
    return [bool](Get-InstalledX264Version)
}

function Get-X265Release {
    $repository = "msg7086/x265-Yuuki-Asuna"
    $branchName = "stable"
    $cacheKey = "github-branch-source:${repository}:$branchName"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $branch = Get-SetupJsonFromUri `
        -Uri ([Uri]"https://api.github.com/repos/$repository/branches/$branchName") `
        -CacheName "x265-yuuki-asuna-stable-branch.json"
    $commit = [string]$branch.commit.sha
    if (-not $commit) {
        throw (Get-SetupText "The x265 stable branch has no commit." "x265 stable 分支没有可用提交。")
    }

    $versionText = Get-SetupTextFromUri `
        -Uri ([Uri]"https://raw.githubusercontent.com/$repository/$commit/x265Version.txt") `
        -CacheName "x265-yuuki-asuna-version.txt"
    $releaseTagLine = $versionText.Replace("`r", "").Split([char]"`n") |
        Where-Object { $_.TrimStart().StartsWith("releasetag:", [StringComparison]::OrdinalIgnoreCase) } |
        Select-Object -First 1
    if (-not $releaseTagLine) {
        throw (Get-SetupText "The x265 stable branch does not declare its release version." "x265 stable 分支未声明发布版本。")
    }
    $version = $releaseTagLine.Substring($releaseTagLine.IndexOf(':') + 1).Trim()
    if (-not $version) {
        throw (Get-SetupText "The x265 stable branch release version is empty." "x265 stable 分支的发布版本为空。")
    }

    $result = [pscustomobject]@{
        Version = $version
        Name = "x265-Yuuki-Asuna-$version.zip"
        Uri = [Uri]"https://codeload.github.com/$repository/zip/$commit"
        Sha256 = ""
        Size = 0L
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-InstalledX265Version {
    if (-not (Test-Path -LiteralPath $script:ToolPaths.X265 -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:ToolPaths.X265Version -PathType Leaf)) {
        return ""
    }
    return ([IO.File]::ReadAllText($script:ToolPaths.X265Version)).Trim()
}

function Update-X265SourceForCMake4 {
    param([Parameter(Mandatory = $true)][string]$SourceRoot)

    $mainCmake = Join-Path $SourceRoot "CMakeLists.txt"
    Set-SourceTextReplacement `
        -Path $mainCmake `
        -OldText "cmake_policy(SET CMP0025 OLD) # report Apple's Clang as just Clang" `
        -NewText "cmake_policy(SET CMP0025 NEW) # report Apple's Clang as just Clang" `
        -Description "x265 CMP0025 policy"
    Set-SourceTextReplacement `
        -Path $mainCmake `
        -OldText "cmake_policy(SET CMP0054 OLD) # Only interpret if() arguments as variables or keywords when unquoted" `
        -NewText "cmake_policy(SET CMP0054 NEW) # Only interpret if() arguments as variables or keywords when unquoted" `
        -Description "x265 CMP0054 policy"
    Set-SourceTextReplacement `
        -Path $mainCmake `
        -OldText @"
project (x265)
cmake_minimum_required (VERSION 2.8.8) # OBJECT libraries require 2.8.8
"@ `
        -NewText @"
cmake_minimum_required(VERSION 3.10)
project(x265 LANGUAGES C CXX)
"@ `
        -Description "x265 minimum CMake version"

    $dynamicHdrCmake = Join-Path $SourceRoot "dynamicHDR10\CMakeLists.txt"
    if (Test-Path -LiteralPath $dynamicHdrCmake -PathType Leaf) {
        Set-SourceTextReplacement `
            -Path $dynamicHdrCmake `
            -OldText "cmake_minimum_required (VERSION 2.8.11)" `
            -NewText "cmake_minimum_required(VERSION 3.10)" `
            -Description "x265 dynamicHDR10 minimum CMake version"
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
    Update-X265SourceForCMake4 -SourceRoot $sourceRoot

    $buildRoot = Join-Path $script:TempRoot "x265-build"
    $build12 = Join-Path $buildRoot "12bit"
    $build10 = Join-Path $buildRoot "10bit"
    $build8 = Join-Path $buildRoot "8bit"
    $nasmPath = $script:ToolPaths.Nasm.Replace('\', '/')
    $commonArguments = @(
        "-G", "Visual Studio 18 2026",
        "-A", "x64",
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
    [IO.File]::WriteAllText(
        $script:ToolPaths.X265Version,
        $release.Version,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-X265 {
    try {
        $output = Invoke-SetupCommand -FilePath $script:ToolPaths.X265 -Arguments @("--version")
        return $output.IndexOf("8bit+10bit+12bit", [StringComparison]::OrdinalIgnoreCase) -ge 0
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

function Try-Update-SvtAv1SourceFor12Bit {
    param([Parameter(Mandatory = $true)][string]$SourceRoot)

    $sourceFiles = @(
        (Join-Path $SourceRoot "Source\Lib\Globals\enc_settings.c"),
        (Join-Path $SourceRoot "Source\App\app_config.c"),
        (Join-Path $SourceRoot "Source\App\app_main.c"),
        (Join-Path $SourceRoot "Source\App\app_process_cmd.c"),
        (Join-Path $SourceRoot "Source\Lib\Codec\entropy_coding.c")
    )
    $originalFiles = [ordered]@{}
    foreach ($sourceFile in $sourceFiles) {
        if (Test-Path -LiteralPath $sourceFile -PathType Leaf) {
            $originalFiles[$sourceFile] = [IO.File]::ReadAllBytes($sourceFile)
        }
    }

    try {
        Set-SourceTextReplacement `
        -Path (Join-Path $SourceRoot "Source\Lib\Globals\enc_settings.c") `
        -OldText @"
    if ((config->encoder_bit_depth != 8) && (config->encoder_bit_depth != 10)) {
        SVT_ERROR("Encoder Bit Depth shall be only 8 or 10 \n");
        return_error = EB_ErrorBadParameter;
    }
    // Check if the EncoderBitDepth is conformant with the Profile constraint
"@ `
        -NewText @"
#if CONFIG_ENABLE_HIGH_BIT_DEPTH
    if (config->encoder_bit_depth != 8 && config->encoder_bit_depth != 10 &&
        config->encoder_bit_depth != EB_TWELVE_BIT) {
        SVT_ERROR("Encoder Bit Depth shall be only 8, 10, or 12\n");
        return_error = EB_ErrorBadParameter;
    }
    if (config->encoder_bit_depth == EB_TWELVE_BIT && config->profile != PROFESSIONAL_PROFILE) {
        SVT_ERROR("12-bit encoding requires Professional profile (seq_profile / --profile 2)\n");
        return_error = EB_ErrorBadParameter;
    }
#else
    if ((config->encoder_bit_depth != 8) && (config->encoder_bit_depth != 10)) {
        SVT_ERROR("Encoder Bit Depth shall be only 8 or 10 \n");
        return_error = EB_ErrorBadParameter;
    }
#endif
    // Check if the EncoderBitDepth is conformant with the Profile constraint
"@ `
        -Description "SVT-AV1 12-bit validation"

    $appConfig = Join-Path $SourceRoot "Source\App\app_config.c"
    Set-SourceTextReplacement `
        -Path $appConfig `
        -OldText @"
#define INPUT_DEPTH_TOKEN "--input-depth"
#define KEYINT_TOKEN "--keyint"
"@ `
        -NewText @"
#define INPUT_DEPTH_TOKEN "--input-depth"
#if CONFIG_ENABLE_HIGH_BIT_DEPTH
#define INPUT_DEPTH_HELP \
    "Input video file and output bitstream bit-depth, default is 8 [8, 10, 12]. 12-bit requires " \
    "--profile 2 (Professional)"
#else
#define INPUT_DEPTH_HELP "Input video file and output bitstream bit-depth, default is 8 [8, 10]"
#endif
#define KEYINT_TOKEN "--keyint"
"@ `
        -Description "SVT-AV1 12-bit help text"
    Set-SourceTextReplacement `
        -Path $appConfig `
        -OldText '    {INPUT_DEPTH_TOKEN, "Input video file and output bitstream bit-depth, default is 8 [8, 10]"},' `
        -NewText '    {INPUT_DEPTH_TOKEN, INPUT_DEPTH_HELP},' `
        -Description "SVT-AV1 input-depth help entry"
    Set-SourceTextReplacement `
        -Path $appConfig `
        -OldText '    frame_size = frame_size << ((app_cfg->config.encoder_bit_depth == 10) ? 1 : 0);' `
        -NewText '    frame_size = frame_size << ((app_cfg->config.encoder_bit_depth > 8) ? 1 : 0);' `
        -Description "SVT-AV1 12-bit input frame size"
    Set-SourceTextReplacement `
        -Path (Join-Path $SourceRoot "Source\App\app_main.c") `
        -OldText '        double max_pix_value  = (cfg->encoder_bit_depth == 8) ? 255 : 1023;' `
        -NewText '        double max_pix_value = (double)((1u << cfg->encoder_bit_depth) - 1);' `
        -Description "SVT-AV1 application 12-bit pixel range"
    Set-SourceTextReplacement `
        -Path (Join-Path $SourceRoot "Source\App\app_process_cmd.c") `
        -OldText '    double   max_pix_value = (app_cfg->config.encoder_bit_depth == 8) ? 255 : 1023;' `
        -NewText '    double max_pix_value = (double)((1u << app_cfg->config.encoder_bit_depth) - 1);' `
        -Description "SVT-AV1 command 12-bit pixel range"
    Set-SourceTextReplacement `
        -Path (Join-Path $SourceRoot "Source\Lib\Codec\entropy_coding.c") `
        -OldText @"
    if (scs->static_config.profile == PROFESSIONAL_PROFILE && scs->static_config.encoder_bit_depth != EB_EIGHT_BIT) {
        SVT_ERROR("Profile 2 Not supported\n");
        svt_aom_wb_write_bit(wb, scs->static_config.encoder_bit_depth == EB_TEN_BIT ? 0 : 1);
    }
"@ `
        -NewText @"
    if (scs->static_config.profile == PROFESSIONAL_PROFILE && scs->static_config.encoder_bit_depth != EB_EIGHT_BIT) {
        svt_aom_wb_write_bit(wb, scs->static_config.encoder_bit_depth == EB_TEN_BIT ? 0 : 1);
    }
"@ `
        -Description "SVT-AV1 Professional profile 12-bit signaling"
        Write-SetupWarning `
            "The experimental SVT-AV1 12-bit patch was applied. Upstream 12-bit support is incomplete or may be buggy; use it only for experiments." `
            "已应用 SVT-AV1 实验性 12-bit 补丁。上游底层的 12-bit 支持并不完整或可能存在错误，仅供实验使用。"
        return $true
    }
    catch {
        $patchError = $_.Exception.Message
        foreach ($sourceFile in $originalFiles.Keys) {
            [IO.File]::WriteAllBytes($sourceFile, $originalFiles[$sourceFile])
        }
        Write-SetupWarning `
            "The experimental SVT-AV1 12-bit patch could not be applied: $patchError. The unmodified upstream source will be compiled with normal 8/10-bit support." `
            "无法应用 SVT-AV1 实验性 12-bit 补丁：$patchError。将按上游原始源码编译，正常支持 8/10-bit。"
        return $false
    }
}

function Build-SvtAv1Executable {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$BuildRoot,
        [Parameter(Mandatory = $true)][string]$BuildDescription
    )

    $nasmPath = $script:ToolPaths.Nasm.Replace('\', '/')
    Invoke-SetupBuildCommand `
        -DisplayName "SVT-AV1 $BuildDescription configuration" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments @(
            "-S", $SourceRoot,
            "-B", $BuildRoot,
            "-G", "Visual Studio 18 2026",
            "-A", "x64",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DBUILD_TESTING=OFF",
            "-DBUILD_APPS=ON",
            "-DSVT_AV1_LTO=ON",
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
            "-DCMAKE_ASM_NASM_COMPILER=$nasmPath"
        )
    Invoke-SetupBuildCommand `
        -DisplayName "SVT-AV1 $BuildDescription compilation" `
        -FilePath $script:ToolPaths.CMake `
        -Arguments @("--build", $BuildRoot, "--config", "Release", "--target", "SvtAv1EncApp", "--parallel", $script:BuildJobs)
    $executable = Get-ChildItem -LiteralPath $SourceRoot -Filter "SvtAv1EncApp.exe" -File -Recurse |
        Where-Object { $_.FullName -match '[\\/]Bin[\\/]Release[\\/]' } |
        Select-Object -First 1
    if ($null -eq $executable) {
        $executable = Get-ChildItem -LiteralPath $BuildRoot -Filter "SvtAv1EncApp.exe" -File -Recurse |
            Select-Object -First 1
    }
    if ($null -eq $executable) {
        throw (Get-SetupText "The SVT-AV1 executable is missing after compilation." "编译后未找到 SVT-AV1 可执行文件。")
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
    $patchApplied = Try-Update-SvtAv1SourceFor12Bit -SourceRoot $sourceRoot
    $buildDescription = $(if ($patchApplied) { "experimental 12-bit" } else { "upstream 8/10-bit" })
    try {
        $executable = Build-SvtAv1Executable `
            -SourceRoot $sourceRoot `
            -BuildRoot (Join-Path $script:TempRoot "svt-av1-build") `
            -BuildDescription $buildDescription
    }
    catch {
        if (-not $patchApplied) {
            throw
        }
        $experimentalBuildError = $_.Exception.Message
        Write-SetupWarning `
            "The experimental SVT-AV1 12-bit build failed: $experimentalBuildError. Retrying with a fresh copy of the unmodified upstream source." `
            "SVT-AV1 实验性 12-bit 版本编译失败：$experimentalBuildError。正在使用重新解压的上游原始源码重试。"
        $fallbackExtracted = Join-Path $script:TempRoot "svt-av1-fallback-extracted"
        Expand-SetupZip -Archive $archive -Destination $fallbackExtracted
        $fallbackMarker = Get-ChildItem -LiteralPath $fallbackExtracted -Filter "enc_settings.c" -File -Recurse |
            Where-Object { $_.FullName -match '[\\/]Source[\\/]Lib[\\/]Globals[\\/]enc_settings\.c$' } |
            Select-Object -First 1
        if ($null -eq $fallbackMarker) {
            throw (Get-SetupText `
                "The unmodified SVT-AV1 fallback source directory is missing." `
                "未找到未修改的 SVT-AV1 回退源码目录。")
        }
        $fallbackSourceRoot = $fallbackMarker.Directory.Parent.Parent.Parent.FullName
        $executable = Build-SvtAv1Executable `
            -SourceRoot $fallbackSourceRoot `
            -BuildRoot (Join-Path $script:TempRoot "svt-av1-fallback-build") `
            -BuildDescription "upstream 8/10-bit fallback"
    }

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
    $cliRelease = Get-FdkAacRelease
    $libraryArchive = Join-Path $script:TempRoot $libraryRelease.Name
    $cliArchive = Join-Path $script:TempRoot $cliRelease.Name
    $libraryExtracted = Join-Path $script:TempRoot "fdk-aac-extracted"
    $cliExtracted = Join-Path $script:TempRoot "fdkaac-extracted"
    Invoke-SetupDownload -Uri $libraryRelease.Uri -Destination $libraryArchive | Out-Null
    Invoke-SetupDownload -Uri $cliRelease.Uri -Destination $cliArchive | Out-Null
    Expand-SetupZip -Archive $libraryArchive -Destination $libraryExtracted
    Expand-SetupZip -Archive $cliArchive -Destination $cliExtracted
    $libraryConfigure = Get-ChildItem -LiteralPath $libraryExtracted -Filter "configure.ac" -File -Recurse |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "libFDK") -PathType Container } |
        Select-Object -First 1
    $cliConfigure = Get-ChildItem -LiteralPath $cliExtracted -Filter "configure.ac" -File -Recurse |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.DirectoryName "src") -PathType Container } |
        Select-Object -First 1
    if ($null -eq $libraryConfigure -or $null -eq $cliConfigure) {
        throw (Get-SetupText "FDK-AAC source directories are missing." "未找到 FDK-AAC 源码目录。")
    }

    $prefix = Join-Path $script:TempRoot "fdkaac-prefix"
    $buildScriptContent = @(
        'set -euo pipefail',
        'export PATH=/ucrt64/bin:/usr/bin',
        'library_source=$1',
        'cli_source=$2',
        'prefix=$3',
        'jobs=$4',
        'cd "$library_source"',
        './autogen.sh',
        './configure --prefix="$prefix" --disable-shared --enable-static',
        'make -j"$jobs"',
        'make install',
        'cd "$cli_source"',
        'autoreconf -fi',
        'PKG_CONFIG_PATH="$prefix/lib/pkgconfig" LDFLAGS="-static -static-libgcc" ./configure --host=x86_64-w64-mingw32 --prefix="$prefix" --disable-shared --enable-static',
        'make -j"$jobs"'
    ) -join "`n"
    $buildScript = Write-SetupTempScript -Name "build-fdkaac.sh" -Content $buildScriptContent
    Invoke-SetupBuildCommand `
        -DisplayName "FDK-AAC and fdkaac static compilation" `
        -FilePath $script:ToolPaths.Msys2Bash `
        -Arguments @(
            (ConvertTo-Msys2Path $buildScript),
            (ConvertTo-Msys2Path $libraryConfigure.Directory.FullName),
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
    $cacheKey = "github:vapoursynth-classic:latest-x64"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }

    $releases = @(Get-SetupJsonFromUri `
        -Uri ([Uri]"https://api.github.com/repos/AmusementClub/vapoursynth-classic/releases?per_page=100") `
        -CacheName "vapoursynth-classic-releases.json")
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
            $assets = @($release.assets | Where-Object { [string]$_.name -ieq "release-x64.zip" })
            if ($assets.Count -ne 1) {
                continue
            }
            $asset = $assets[0]
            $sha256 = ""
            $digest = [string]$asset.digest
            if ($digest.StartsWith("sha256:", [StringComparison]::OrdinalIgnoreCase)) {
                $sha256 = $digest.Substring(7)
            }
            [pscustomobject]@{
                Version = "$releaseNumber.$apiNumber"
                Tag = $tag
                SortVersion = New-Object Version($releaseNumber, $apiNumber)
                Name = "vapoursynth-classic-$tag-x64.zip"
                Uri = [Uri]$asset.browser_download_url
                Sha256 = $sha256
                Size = [long]$asset.size
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

function Get-InstalledVapourSynthClassicVersion {
    $marker = Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-classic-version.txt"
    $requiredFiles = @(
        $script:ToolPaths.VsPipe,
        (Join-Path $script:ToolPaths.VapourSynthRoot "VapourSynth.dll"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "VSScript.dll"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth.cp313-win_amd64.pyd"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth64\coreplugins\RemoveGrainVS.dll")
    )
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        return ""
    }
    foreach ($file in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            return ""
        }
    }
    return ([IO.File]::ReadAllText($marker)).Trim()
}

function Install-VapourSynthClassic {
    param([string]$Version)

    $release = Get-VapourSynthClassicRelease
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "vapoursynth-classic"
    Invoke-SetupDownload `
        -Uri $release.Uri `
        -Destination $archive `
        -Sha256 $release.Sha256 `
        -ExpectedSize $release.Size | Out-Null
    Expand-SetupZip -Archive $archive -Destination $extracted
    $vspipe = Get-ChildItem -LiteralPath $extracted -Filter "VSPipe.exe" -File -Recurse |
        Select-Object -First 1
    if ($null -eq $vspipe) {
        throw (Get-SetupText `
            "VSPipe.exe is missing from the vapoursynth-classic archive." `
            "vapoursynth-classic 压缩包中缺少 VSPipe.exe。")
    }

    [IO.Directory]::CreateDirectory($script:ToolPaths.VapourSynthRoot) | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $vspipe.Directory.FullName -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $script:ToolPaths.VapourSynthRoot -Recurse -Force
    }
    $portableMarker = Join-Path $script:ToolPaths.VapourSynthRoot "portable.vs"
    if (-not (Test-Path -LiteralPath $portableMarker -PathType Leaf)) {
        [IO.File]::WriteAllText($portableMarker, "", (New-Object Text.UTF8Encoding($false)))
    }
    [IO.File]::WriteAllText(
        (Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-classic-version.txt"),
        $release.Version,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-VapourSynthClassic {
    $installedVersion = Get-InstalledVapourSynthClassicVersion
    return [bool]$installedVersion -and
        $installedVersion -eq (Get-VapourSynthClassicRelease).Version
}
function Get-VapourSynthPythonRelease {
    $cacheKey = "python-embed:3.13:latest"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }
    $version = Get-PythonStableVersions |
        Where-Object {
            $candidate = ConvertTo-ComparableVersion $_
            $candidate.Major -eq 3 -and $candidate.Minor -eq 13
        } |
        Select-Object -First 1
    if (-not $version) {
        throw (Get-SetupText `
            "Unable to determine the latest Python 3.13 embeddable release." `
            "无法确定最新的 Python 3.13 嵌入版。")
    }
    $result = [pscustomobject]@{
        Version = $version
        Name = "python-$version-embed-amd64.zip"
        Uri = [Uri]"https://www.python.org/ftp/python/$version/python-$version-embed-amd64.zip"
    }
    $script:ReleaseCache[$cacheKey] = $result
    return $result
}

function Get-VapourSynthNumpyRelease {
    $cacheKey = "pypi:numpy:cp313-win-amd64"
    if ($script:ReleaseCache.Contains($cacheKey)) {
        return $script:ReleaseCache[$cacheKey]
    }
    $package = Get-SetupJsonFromUri `
        -Uri ([Uri]"https://pypi.org/pypi/numpy/json") `
        -CacheName "numpy-pypi.json"
    $preferredVersion = [string]$package.info.version
    $preferredRelease = $package.releases.PSObject.Properties |
        Where-Object { $_.Name -eq $preferredVersion } |
        Select-Object -First 1
    $releaseProperties = @()
    if ($null -ne $preferredRelease) {
        $releaseProperties += $preferredRelease
    }
    $releaseProperties += @(
        $package.releases.PSObject.Properties |
            Where-Object {
                $_.Name -ne $preferredVersion -and
                $_.Name -match '^[0-9]+(?:\.[0-9]+){1,3}$'
            } |
            Sort-Object { ConvertTo-ComparableVersion $_.Name } -Descending
    )
    foreach ($property in $releaseProperties) {
        $files = @(
            $property.Value |
                Where-Object {
                    [string]$_.packagetype -eq "bdist_wheel" -and
                    ([string]$_.filename).EndsWith(
                        "cp313-cp313-win_amd64.whl",
                        [StringComparison]::OrdinalIgnoreCase
                    )
                }
        )
        if ($files.Count -eq 1) {
            $file = $files[0]
            $result = [pscustomobject]@{
                Version = $property.Name
                Name = [string]$file.filename
                Uri = [Uri]$file.url
                Sha256 = [string]$file.digests.sha256
                Size = [long]$file.size
            }
            $script:ReleaseCache[$cacheKey] = $result
            return $result
        }
    }
    throw (Get-SetupText `
        "No NumPy wheel compatible with CPython 3.13 x64 was found." `
        "未找到兼容 CPython 3.13 x64 的 NumPy wheel。")
}

function Get-VapourSynthPythonState {
    $marker = Join-Path $script:ToolPaths.VapourSynthRoot "python-embed-version.json"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -Raw -Encoding UTF8 -LiteralPath $marker | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Get-InstalledVapourSynthPythonVersion {
    $state = Get-VapourSynthPythonState
    $requiredFiles = @(
        $script:ToolPaths.VapourSynthPython,
        (Join-Path $script:ToolPaths.VapourSynthRoot "python313.dll"),
        (Join-Path $script:ToolPaths.VapourSynthRoot "python313._pth"),
        (Join-Path $script:ToolPaths.VapourSynthSitePackages "numpy\__init__.py")
    )
    if ($null -eq $state) {
        return ""
    }
    foreach ($file in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            return ""
        }
    }
    return [string]$state.python_version
}

function Install-VapourSynthEmbeddedPython {
    param([string]$Version)

    $pythonRelease = Get-VapourSynthPythonRelease
    $numpyRelease = Get-VapourSynthNumpyRelease
    $pythonArchive = Join-Path $script:TempRoot $pythonRelease.Name
    $pythonExtracted = Join-Path $script:TempRoot "python-embed"
    Invoke-SetupDownload -Uri $pythonRelease.Uri -Destination $pythonArchive | Out-Null
    Expand-SetupZip -Archive $pythonArchive -Destination $pythonExtracted

    [IO.Directory]::CreateDirectory($script:ToolPaths.VapourSynthRoot) | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $pythonExtracted -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $script:ToolPaths.VapourSynthRoot -Recurse -Force
    }
    [IO.Directory]::CreateDirectory($script:ToolPaths.VapourSynthSitePackages) | Out-Null
    $pthContent = ".`r`npython313.zip`r`nimport site`r`n"
    [IO.File]::WriteAllText(
        (Join-Path $script:ToolPaths.VapourSynthRoot "python313._pth"),
        $pthContent,
        (New-Object Text.UTF8Encoding($false))
    )

    $numpyWheel = Join-Path $script:TempRoot $numpyRelease.Name
    $numpyExtracted = Join-Path $script:TempRoot "numpy-wheel"
    Invoke-SetupDownload `
        -Uri $numpyRelease.Uri `
        -Destination $numpyWheel `
        -Sha256 $numpyRelease.Sha256 `
        -ExpectedSize $numpyRelease.Size | Out-Null
    Expand-SetupZip -Archive $numpyWheel -Destination $numpyExtracted

    foreach ($directoryName in @("numpy", "numpy.libs")) {
        $existingDirectory = Join-Path $script:ToolPaths.VapourSynthSitePackages $directoryName
        if (Test-Path -LiteralPath $existingDirectory) {
            Remove-Item -LiteralPath $existingDirectory -Recurse -Force
        }
    }
    Get-ChildItem -LiteralPath $script:ToolPaths.VapourSynthSitePackages -Directory |
        Where-Object {
            $_.Name.StartsWith("numpy-", [StringComparison]::OrdinalIgnoreCase) -and
            $_.Name.EndsWith(".dist-info", [StringComparison]::OrdinalIgnoreCase)
        } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    foreach ($item in Get-ChildItem -LiteralPath $numpyExtracted -Force) {
        if (-not $item.Name.EndsWith(".data", [StringComparison]::OrdinalIgnoreCase)) {
            Copy-Item -LiteralPath $item.FullName -Destination $script:ToolPaths.VapourSynthSitePackages -Recurse -Force
        }
    }

    $state = [ordered]@{
        python_version = $pythonRelease.Version
        numpy_version = $numpyRelease.Version
    } | ConvertTo-Json
    [IO.File]::WriteAllText(
        (Join-Path $script:ToolPaths.VapourSynthRoot "python-embed-version.json"),
        $state,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-VapourSynthEmbeddedPython {
    $state = Get-VapourSynthPythonState
    if ($null -eq $state -or
        [string]$state.python_version -ne (Get-VapourSynthPythonRelease).Version -or
        [string]$state.numpy_version -ne (Get-VapourSynthNumpyRelease).Version) {
        return $false
    }
    if (-not (Get-InstalledVapourSynthPythonVersion) -or
        -not (Test-Path -LiteralPath (Join-Path $script:ToolPaths.VapourSynthSitePackages "numpy.libs") -PathType Container)) {
        return $false
    }
    try {
        Invoke-SetupCommand -FilePath $script:ToolPaths.VsPipe -Arguments @("--version") | Out-Null
        $output = Invoke-SetupCommand `
            -FilePath $script:ToolPaths.VapourSynthPython `
            -Arguments @("-c", "import numpy, vapoursynth; print(numpy.__version__)")
        return $output.Trim() -eq [string]$state.numpy_version
    }
    catch {
        return $false
    }
}
function Get-VapourSynthToolsRelease {
    return Get-GitHubLatestReleaseAsset `
        -Repository "AmusementClub/tools" `
        -AssetPattern '^vapoursynth_portable_.+_cpu\.7z$'
}

function Get-InstalledVapourSynthToolsVersion {
    $marker = Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-tools-version.txt"
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf) -or
        -not (Test-Path -LiteralPath $script:ToolPaths.VsEdit -PathType Leaf)) {
        return ""
    }
    foreach ($plugin in $script:RequiredVapourSynthPlugins) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:ToolPaths.VapourSynthPlugins $plugin) -PathType Leaf)) {
            return ""
        }
    }
    foreach ($scriptFile in $script:RequiredVapourSynthScripts) {
        if (-not (Test-Path -LiteralPath (Join-Path $script:ToolPaths.VapourSynthSitePackages $scriptFile) -PathType Leaf)) {
            return ""
        }
    }
    return ([IO.File]::ReadAllText($marker)).Trim()
}

function Install-VapourSynthTools {
    param([string]$Version)

    $release = Get-VapourSynthToolsRelease
    if (-not $release.Sha256) {
        throw (Get-SetupText `
            "The AmusementClub tools release does not provide a SHA-256 digest." `
            "AmusementClub tools 发布信息未提供 SHA-256 摘要。")
    }
    $archive = Join-Path $script:TempRoot $release.Name
    $extracted = Join-Path $script:TempRoot "vapoursynth-tools"
    Invoke-SetupDownload `
        -Uri $release.Uri `
        -Destination $archive `
        -Sha256 $release.Sha256 `
        -ExpectedSize $release.Size | Out-Null

    Write-SetupInfo `
        "Reading the AmusementClub tools archive layout." `
        "正在读取 AmusementClub tools 压缩包结构。"
    $listing = Invoke-SetupCommand `
        -FilePath $script:ToolPaths.SevenZip `
        -Arguments @("l", "-slt", $archive)
    $entries = @(
        foreach ($line in ($listing -split "`n")) {
            $trimmed = $line.Trim()
            if ($trimmed.StartsWith("Path = ", [StringComparison]::Ordinal)) {
                $entryPath = $trimmed.Substring(7)
                [pscustomobject]@{
                    Path = $entryPath
                    Normalized = $entryPath.Replace('/', '\')
                }
            }
        }
    )
    $vsEditEntry = $entries |
        Where-Object {
            $_.Normalized -ieq "vsedit.exe" -or
            $_.Normalized.EndsWith("\vsedit.exe", [StringComparison]::OrdinalIgnoreCase)
        } |
        Select-Object -First 1
    if ($null -eq $vsEditEntry) {
        throw (Get-SetupText `
            "vsedit.exe is missing from the AmusementClub tools archive." `
            "AmusementClub tools 压缩包中缺少 vsedit.exe。")
    }

    $scriptEntries = @(
        $entries |
            Where-Object {
                $_.Normalized.StartsWith("VapourSynthScripts\", [StringComparison]::OrdinalIgnoreCase) -or
                $_.Normalized.IndexOf("\VapourSynthScripts\", [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
    )
    if ($scriptEntries.Count -eq 0) {
        throw (Get-SetupText `
            "The VapourSynthScripts directory is missing from the AmusementClub tools archive." `
            "AmusementClub tools 压缩包中缺少 VapourSynthScripts 目录。")
    }

    $selectedEntries = @($vsEditEntry.Path)
    $selectedEntries += @($scriptEntries | ForEach-Object { $_.Path })
    foreach ($plugin in $script:RequiredVapourSynthPlugins) {
        $suffix = "\vapoursynth64\plugins\$plugin"
        $pluginEntry = $entries |
            Where-Object {
                $_.Normalized -ieq $suffix.TrimStart('\') -or
                $_.Normalized.EndsWith($suffix, [StringComparison]::OrdinalIgnoreCase)
            } |
            Select-Object -First 1
        if ($null -eq $pluginEntry) {
            throw (Get-SetupText `
                "Required VapourSynth plugin is missing from the tools archive: $plugin" `
                "tools 压缩包中缺少必需的 VapourSynth 插件：$plugin")
        }
        $selectedEntries += $pluginEntry.Path
    }

    [IO.Directory]::CreateDirectory($extracted) | Out-Null
    $extractArguments = @("x", $archive, "-o$extracted", "-y", "-bso0", "-bsp0")
    $extractArguments += @($selectedEntries | Sort-Object -Unique)
    Write-SetupInfo `
        "Extracting VSEdit, VapourSynthScripts, and $($script:RequiredVapourSynthPlugins.Count) required plugins." `
        "正在解压 VSEdit、VapourSynthScripts 和 $($script:RequiredVapourSynthPlugins.Count) 个必需插件。"
    Invoke-SetupCommand `
        -FilePath $script:ToolPaths.SevenZip `
        -Arguments $extractArguments | Out-Null

    $vsEdit = Get-ChildItem -LiteralPath $extracted -Filter "vsedit.exe" -File -Recurse |
        Select-Object -First 1
    $scriptsDirectory = Get-ChildItem -LiteralPath $extracted -Filter "VapourSynthScripts" -Directory -Recurse |
        Select-Object -First 1
    if ($null -eq $vsEdit -or $null -eq $scriptsDirectory) {
        throw (Get-SetupText `
            "VSEdit or VapourSynthScripts could not be located after extraction." `
            "解压后无法定位 VSEdit 或 VapourSynthScripts。")
    }

    [IO.Directory]::CreateDirectory($script:ToolPaths.VapourSynthRoot) | Out-Null
    [IO.Directory]::CreateDirectory($script:ToolPaths.VapourSynthSitePackages) | Out-Null
    [IO.Directory]::CreateDirectory($script:ToolPaths.VapourSynthPlugins) | Out-Null
    Copy-Item -LiteralPath $vsEdit.FullName -Destination $script:ToolPaths.VsEdit -Force
    foreach ($item in Get-ChildItem -LiteralPath $scriptsDirectory.FullName -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $script:ToolPaths.VapourSynthSitePackages -Recurse -Force
    }
    foreach ($plugin in $script:RequiredVapourSynthPlugins) {
        $pluginFile = Get-ChildItem -LiteralPath $extracted -Filter $plugin -File -Recurse |
            Where-Object {
                $_.DirectoryName.Replace('/', '\').EndsWith(
                    "\vapoursynth64\plugins",
                    [StringComparison]::OrdinalIgnoreCase
                )
            } |
            Select-Object -First 1
        if ($null -eq $pluginFile) {
            throw (Get-SetupText `
                "Required plugin could not be located after extraction: $plugin" `
                "解压后无法定位必需插件：$plugin")
        }
        Copy-Item -LiteralPath $pluginFile.FullName -Destination (Join-Path $script:ToolPaths.VapourSynthPlugins $plugin) -Force
    }

    $config = "[common]`r`nvapoursynth_library_paths=./`r`nvapoursynth_plugins_paths=./vapoursynth64/coreplugins, ./vapoursynth64/plugins`r`n"
    [IO.File]::WriteAllText(
        (Join-Path $script:ToolPaths.VapourSynthRoot "vsedit.config"),
        $config,
        (New-Object Text.UTF8Encoding($false))
    )
    [IO.File]::WriteAllText(
        (Join-Path $script:ToolPaths.VapourSynthRoot "vapoursynth-tools-version.txt"),
        $release.Version,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Test-VapourSynthTools {
    $installedVersion = Get-InstalledVapourSynthToolsVersion
    if (-not $installedVersion -or $installedVersion -ne (Get-VapourSynthToolsRelease).Version) {
        return $false
    }
    try {
        $pythonCode = "import numpy, vapoursynth as vs; required=('grain','assrender','bilateral','descale','dfttest','eedi2','eedi3m','f3kdb','fmtc','sangnom','lsmas','mv','neo_f3kdb','nlm_ispc','zsmooth','rgvs'); missing=[name for name in required if not hasattr(vs.core,name)]; assert not missing, 'missing plugins: ' + ', '.join(missing)"
        Invoke-SetupCommand `
            -FilePath $script:ToolPaths.VapourSynthPython `
            -Arguments @("-c", $pythonCode) | Out-Null
        return $true
    }
    catch {
        return $false
    }
}
function Test-CompiledToolsReady {
    Write-SetupInfo `
        "Checking compiled tools before deciding whether MSYS2 is needed." `
        "正在检查编译工具，以确定是否需要 MSYS2。"
    $checks = @(
        [pscustomobject]@{
            Name = "x265 8/10/12-bit encoder"
            GetInstalled = { Get-InstalledX265Version }
            GetAvailable = { (Get-X265Release).Version }
            Verify = { Test-X265 }
        },
        [pscustomobject]@{
            Name = "SVT-AV1 encoder"
            GetInstalled = { Get-InstalledSvtAv1Version }
            GetAvailable = { (Get-SvtAv1Release).Version }
            Verify = { Test-SvtAv1 }
        },
        [pscustomobject]@{
            Name = "FDK-AAC and fdkaac"
            GetInstalled = { Get-InstalledFdkAacVersion }
            GetAvailable = { (Get-FdkAacRelease).Version }
            Verify = { Test-FdkAac }
        },
        [pscustomobject]@{
            Name = "libass"
            GetInstalled = { Get-InstalledLibassVersion }
            GetAvailable = { (Get-LibassRelease).Version }
            Verify = {
                if (-not (Test-Path -LiteralPath $script:ToolPaths.Python -PathType Leaf)) {
                    return [bool](Get-InstalledLibassVersion)
                }
                return Test-Libass
            }
        }
    )
    $toolsRequiringCompilation = @(
        foreach ($check in $checks) {
            $installedVersion = [string](& $check.GetInstalled)
            $availableVersion = [string](& $check.GetAvailable)
            $isReady = [bool]$installedVersion
            if ($isReady) {
                try {
                    $isReady = (Compare-SetupVersion $installedVersion $availableVersion) -ge 0
                }
                catch {
                    $isReady = $false
                }
            }
            if ($isReady) {
                $isReady = [bool](& $check.Verify)
            }
            if ($isReady) {
                Write-SetupInfo `
                    "$($check.Name) is ready: $installedVersion (target: $availableVersion)." `
                    "$($check.Name) 已就绪：$installedVersion（目标：$availableVersion）。"
            }
            else {
                $installedDescription = if ($installedVersion) { $installedVersion } else { "not installed" }
                Write-SetupInfo `
                    "$($check.Name) requires compilation; installed: $installedDescription, target: $availableVersion." `
                    "$($check.Name) 需要编译；当前：$installedDescription，目标：$availableVersion。"
                $check.Name
            }
        }
    )
    if ($toolsRequiringCompilation.Count -eq 0) {
        Write-SetupInfo `
            "All compiled tools are ready; skipping MSYS2 and its build packages." `
            "所有编译工具均已就绪，跳过 MSYS2 及其编译依赖包。"
        return $true
    }
    $missingDescription = $toolsRequiringCompilation -join ", "
    Write-SetupInfo `
        "MSYS2 is required for: $missingDescription" `
        "以下工具需要使用 MSYS2 编译：$missingDescription"
    return $false
}
function Register-StageTwoComponents {
    Register-SetupComponent `
        -Name "7zip" `
        -EnglishName "7-Zip" `
        -ChineseName "7-Zip" `
        -GetInstalledVersion { Get-InstalledSevenZipVersion } `
        -GetAvailableVersion { (Get-SevenZipRelease).Version } `
        -Install { param($Version) Install-SevenZip $Version } `
        -Verify { Test-SevenZip }

    Register-SetupComponent `
        -Name "python" `
        -EnglishName "Python runtime" `
        -ChineseName "Python 运行环境" `
        -GetInstalledVersion { Get-InstalledPythonVersion } `
        -GetAvailableVersion { $script:SelectedPythonRelease.Version } `
        -Install { param($Version) Install-PythonRuntime $Version } `
        -Verify { Test-PythonRuntime }

    Register-SetupComponent `
        -Name "python-dependencies" `
        -EnglishName "Python dependencies" `
        -ChineseName "Python 依赖" `
        -GetInstalledVersion { Get-PythonDependenciesVersion } `
        -GetAvailableVersion { "1.0" } `
        -Install { param($Version) Install-PythonDependenciesWithFallback } `
        -Verify { Test-PythonDependencies }

    Register-SetupComponent `
        -Name "python-system-path" `
        -EnglishName "Python and pip system PATH" `
        -ChineseName "Python 和 pip 系统 PATH" `
        -GetInstalledVersion { if (Test-PythonMachinePath) { "1.0" } else { "" } } `
        -GetAvailableVersion { "1.0" } `
        -Install { param($Version) Add-PythonToMachinePath } `
        -Verify { Test-PythonMachinePath }
    Register-SetupComponent `
        -Name "git" `
        -EnglishName "Git for Windows" `
        -ChineseName "Git for Windows" `
        -GetInstalledVersion { Get-InstalledGitVersion } `
        -GetAvailableVersion { (Get-GitRelease).Version } `
        -Install { param($Version) Install-Git $Version } `
        -Verify { Test-Git }

    Register-SetupComponent `
        -Name "git-system-path" `
        -EnglishName "Git system PATH" `
        -ChineseName "Git 系统 PATH" `
        -GetInstalledVersion { if (Test-GitMachinePath) { "1.0" } else { "" } } `
        -GetAvailableVersion { "1.0" } `
        -Install { param($Version) Add-GitToMachinePath } `
        -Verify { Test-GitMachinePath }

    Register-SetupComponent `
        -Name "visual-studio-build-tools" `
        -EnglishName "Visual Studio 2026 C++ Build Tools" `
        -ChineseName "Visual Studio 2026 C++ 编译工具" `
        -GetInstalledVersion { Get-InstalledVisualStudioVersion } `
        -GetAvailableVersion { (Get-LatestVisualStudioRelease).Version } `
        -Install { param($Version) Install-VisualStudioBuildTools $Version } `
        -Verify { Test-VisualStudioBuildTools }

    Register-SetupComponent `
        -Name "cmake" `
        -EnglishName "CMake" `
        -ChineseName "CMake" `
        -GetInstalledVersion { Get-InstalledCMakeVersion } `
        -GetAvailableVersion { (Get-CMakeRelease).Version } `
        -Install { param($Version) Install-CMake $Version } `
        -Verify { Test-CMake }

    Register-SetupComponent `
        -Name "ninja" `
        -EnglishName "Ninja" `
        -ChineseName "Ninja" `
        -GetInstalledVersion { Get-InstalledNinjaVersion } `
        -GetAvailableVersion { (Get-NinjaRelease).Version } `
        -Install { param($Version) Install-Ninja $Version } `
        -Verify { Test-Ninja }

    Register-SetupComponent `
        -Name "nasm" `
        -EnglishName "NASM" `
        -ChineseName "NASM" `
        -GetInstalledVersion { Get-InstalledNasmVersion } `
        -GetAvailableVersion { (Get-LatestNasmRelease).Version } `
        -Install { param($Version) Install-Nasm $Version } `
        -Verify { Test-Nasm }

    if (Test-CompiledToolsReady) {
        return
    }

    Register-SetupComponent `
        -Name "msys2" `
        -EnglishName "MSYS2 UCRT64" `
        -ChineseName "MSYS2 UCRT64" `
        -GetInstalledVersion { Get-InstalledMsys2Version } `
        -GetAvailableVersion { (Get-Msys2Release).Version } `
        -Install { param($Version) Install-Msys2 $Version } `
        -Verify { Test-Msys2 }

    Register-SetupComponent `
        -Name "msys2-packages" `
        -EnglishName "MSYS2 build packages" `
        -ChineseName "MSYS2 编译依赖包" `
        -GetInstalledVersion { Get-Msys2PackagesVersion } `
        -GetAvailableVersion { "1.0" } `
        -Install { param($Version) Install-Msys2Packages $Version } `
        -Verify { Test-Msys2Packages }
}

function Register-StageThreeComponents {
    Register-SetupComponent `
        -Name "ffmpeg" `
        -EnglishName "FFmpeg and FFprobe" `
        -ChineseName "FFmpeg 和 FFprobe" `
        -GetInstalledVersion { Get-InstalledFfmpegVersion } `
        -GetAvailableVersion { (Get-FfmpegRelease).Version } `
        -Install { param($Version) Install-Ffmpeg $Version } `
        -Verify { Test-Ffmpeg }

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
        -Name "truehdd" `
        -EnglishName "truehdd" `
        -ChineseName "truehdd" `
        -GetInstalledVersion { Get-InstalledTrueHddVersion } `
        -GetAvailableVersion { (Get-TrueHddRelease).Version } `
        -Install { param($Version) Install-TrueHdd $Version } `
        -Verify { Test-TrueHdd }
}
function Register-StageFourComponents {
    Register-SetupComponent `
        -Name "x264" `
        -EnglishName "x264 8/10-bit encoder" `
        -ChineseName "x264 8/10-bit 编码器" `
        -GetInstalledVersion { Get-InstalledX264Version } `
        -GetAvailableVersion { (Get-X264Release).Version } `
        -Install { param($Version) Install-X264 $Version } `
        -Verify { Test-X264 }

    Register-SetupComponent `
        -Name "x265" `
        -EnglishName "x265 8/10/12-bit encoder" `
        -ChineseName "x265 8/10/12-bit 编码器" `
        -GetInstalledVersion { Get-InstalledX265Version } `
        -GetAvailableVersion { (Get-X265Release).Version } `
        -Install { param($Version) Install-X265 $Version } `
        -Verify { Test-X265 }

    Register-SetupComponent `
        -Name "svt-av1" `
        -EnglishName "SVT-AV1 encoder (experimental 12-bit patch)" `
        -ChineseName "SVT-AV1 编码器（实验性 12-bit 补丁）" `
        -GetInstalledVersion { Get-InstalledSvtAv1Version } `
        -GetAvailableVersion { (Get-SvtAv1Release).Version } `
        -Install { param($Version) Install-SvtAv1 $Version } `
        -Verify { Test-SvtAv1 }

    Register-SetupComponent `
        -Name "fdkaac" `
        -EnglishName "FDK-AAC and fdkaac" `
        -ChineseName "FDK-AAC 和 fdkaac" `
        -GetInstalledVersion { Get-InstalledFdkAacVersion } `
        -GetAvailableVersion { (Get-FdkAacRelease).Version } `
        -Install { param($Version) Install-FdkAac $Version } `
        -Verify { Test-FdkAac }

    Register-SetupComponent `
        -Name "libass" `
        -EnglishName "libass with static dependencies" `
        -ChineseName "静态依赖版 libass" `
        -GetInstalledVersion { Get-InstalledLibassVersion } `
        -GetAvailableVersion { (Get-LibassRelease).Version } `
        -Install { param($Version) Install-Libass $Version } `
        -Verify { Test-Libass }
}

function Register-StageFiveComponents {
    Register-SetupComponent `
        -Name "vapoursynth-classic" `
        -EnglishName "VapourSynth Classic portable runtime" `
        -ChineseName "VapourSynth Classic 便携运行环境" `
        -GetInstalledVersion { Get-InstalledVapourSynthClassicVersion } `
        -GetAvailableVersion { (Get-VapourSynthClassicRelease).Version } `
        -Install { param($Version) Install-VapourSynthClassic $Version } `
        -Verify { Test-VapourSynthClassic }

    Register-SetupComponent `
        -Name "vapoursynth-python" `
        -EnglishName "VapourSynth embedded Python 3.13 and NumPy" `
        -ChineseName "VapourSynth 嵌入式 Python 3.13 和 NumPy" `
        -GetInstalledVersion { Get-InstalledVapourSynthPythonVersion } `
        -GetAvailableVersion { (Get-VapourSynthPythonRelease).Version } `
        -Install { param($Version) Install-VapourSynthEmbeddedPython $Version } `
        -Verify { Test-VapourSynthEmbeddedPython }

    Register-SetupComponent `
        -Name "vapoursynth-tools" `
        -EnglishName "VSEdit, VapourSynth scripts, and required plugins" `
        -ChineseName "VSEdit、VapourSynth 脚本和必需插件" `
        -GetInstalledVersion { Get-InstalledVapourSynthToolsVersion } `
        -GetAvailableVersion { (Get-VapourSynthToolsRelease).Version } `
        -Install { param($Version) Install-VapourSynthTools $Version } `
        -Verify { Test-VapourSynthTools }
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
    Initialize-PythonRuntimeSelection
    $script:Manifest.system = [ordered]@{
        family = $windows.Family
        caption = $windows.Caption
        build = $windows.Build
        version = $windows.Version
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
    Invoke-RegisteredSetupComponents
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
