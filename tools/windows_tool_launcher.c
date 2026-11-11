#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <strsafe.h>

#define PATH_LENGTH 32768

static WCHAR launcher_path[PATH_LENGTH];
static WCHAR bundle_root[PATH_LENGTH];
static WCHAR executable_path[PATH_LENGTH];
static WCHAR search_path[PATH_LENGTH];
static WCHAR original_path[PATH_LENGTH];
static WCHAR command_line[PATH_LENGTH];

static STARTUPINFOW inherited;
static STARTUPINFOW startup;
static PROCESS_INFORMATION child;

static __declspec(noreturn) void fail(PCWSTR action, DWORD error)
{
    static WCHAR message[1024];
    const DWORD detail = FormatMessageW(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
                                       NULL, error, 0, message, ARRAYSIZE(message), NULL);
#ifdef GUI_ENTRY
    MessageBoxW(NULL, detail ? message : action, action, MB_OK | MB_ICONERROR);
#else
    static char utf8[4096];
    DWORD written;
    const HANDLE output = GetStdHandle(STD_ERROR_HANDLE);
    const int length = WideCharToMultiByte(CP_UTF8, 0, action, -1, utf8, ARRAYSIZE(utf8), NULL, NULL);
    if (length > 1)
        WriteFile(output, utf8, (DWORD)length - 1, &written, NULL);
    WriteFile(output, "\r\n", 2, &written, NULL);
    if (detail) {
        const int bytes = WideCharToMultiByte(CP_UTF8, 0, message, (int)detail, utf8, ARRAYSIZE(utf8), NULL, NULL);
        if (bytes > 0)
            WriteFile(output, utf8, (DWORD)bytes, &written, NULL);
    }
#endif
    ExitProcess(1);
}

static PWSTR file_name(PWSTR start, PWSTR end)
{
    while (end > start && end[-1] != L'\\')
        --end;
    return end;
}

void WINAPI launch_entry(void)
{
    const DWORD length = GetModuleFileNameW(NULL, launcher_path, ARRAYSIZE(launcher_path));
    if (length == 0 || length >= ARRAYSIZE(launcher_path))
        fail(L"Locating the launcher", GetLastError());

    PWSTR const name = file_name(launcher_path, launcher_path + length);
    if (name == launcher_path || launcher_path + length - name <= 4)
        fail(L"Reading the launcher path", ERROR_BAD_PATHNAME);

    PWSTR const folder = file_name(launcher_path, name - 1);
    const int folder_length = (int)(name - folder - 1);
    const BOOL editor = CompareStringOrdinal(folder, folder_length, L"vsedit", -1, TRUE) == CSTR_EQUAL;
    const BOOL private_mkv = CompareStringOrdinal(folder, folder_length, L"mkvtoolnix", -1, TRUE) == CSTR_EQUAL;
    if ((editor || private_mkv) && folder == launcher_path)
        fail(L"Locating the package", ERROR_BAD_PATHNAME);
    const size_t directory_length = (size_t)(name - launcher_path - 1);
    const size_t root_length = editor || private_mkv ? (size_t)(folder - launcher_path - 1) : directory_length;
    if (FAILED(StringCchCopyNW(bundle_root, ARRAYSIZE(bundle_root), launcher_path, root_length)))
        fail(L"Locating the package", ERROR_FILENAME_EXCED_RANGE);

    if (FAILED(StringCchCopyNW(executable_path, ARRAYSIZE(executable_path), launcher_path,
                               editor ? directory_length : root_length))
        || (!editor && FAILED(StringCchCatW(executable_path, ARRAYSIZE(executable_path), L"\\mkvtoolnix")))
        || FAILED(StringCchCatW(executable_path, ARRAYSIZE(executable_path), L"\\"))
        || FAILED(StringCchCatNW(executable_path, ARRAYSIZE(executable_path), name,
                                (size_t)(launcher_path + length - name - 4)))
        || FAILED(StringCchCatW(executable_path, ARRAYSIZE(executable_path), L"-native.exe"))) {
        fail(L"Locating the bundled executable", ERROR_FILENAME_EXCED_RANGE);
    }

    const DWORD path_length = GetEnvironmentVariableW(L"PATH", original_path, ARRAYSIZE(original_path));
    if (path_length >= ARRAYSIZE(original_path)
        || FAILED(StringCchCopyW(search_path, ARRAYSIZE(search_path), bundle_root))
        || (editor && (FAILED(StringCchCatW(search_path, ARRAYSIZE(search_path), L"\\PyQt6\\Qt6\\bin;"))
                       || FAILED(StringCchCatW(search_path, ARRAYSIZE(search_path), bundle_root))))
        || (path_length && (FAILED(StringCchCatW(search_path, ARRAYSIZE(search_path), L";"))
                            || FAILED(StringCchCatW(search_path, ARRAYSIZE(search_path), original_path))))) {
        fail(L"Preparing the child DLL search path", ERROR_INSUFFICIENT_BUFFER);
    }
    if (!SetEnvironmentVariableW(L"PATH", search_path))
        fail(L"Setting the child DLL search path", GetLastError());

    if (editor) {
        SetEnvironmentVariableW(L"QT_PLUGIN_PATH", NULL);
        SetEnvironmentVariableW(L"QT_QPA_PLATFORM_PLUGIN_PATH", NULL);
        SetEnvironmentVariableW(L"QML_IMPORT_PATH", NULL);
        SetEnvironmentVariableW(L"QML2_IMPORT_PATH", NULL);
        if (FAILED(StringCchCatW(bundle_root, ARRAYSIZE(bundle_root), L"\\VSScript.dll")))
            fail(L"Locating the bundled VSScript", ERROR_FILENAME_EXCED_RANGE);
        if (!SetEnvironmentVariableW(L"VSSCRIPT_PATH", bundle_root))
            fail(L"Setting the bundled VSScript path", GetLastError());
    }

    if (FAILED(StringCchCopyW(command_line, ARRAYSIZE(command_line), GetCommandLineW())))
        fail(L"Reading the command line", ERROR_INSUFFICIENT_BUFFER);

    GetStartupInfoW(&inherited);
    startup.cb = sizeof(startup);
    startup.dwFlags = inherited.dwFlags & (STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES);
    startup.wShowWindow = inherited.wShowWindow;
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);

    const DWORD flags = GetConsoleWindow() ? 0 : CREATE_NO_WINDOW;
    if (!CreateProcessW(executable_path, command_line, NULL, NULL, TRUE,
                        flags, NULL, NULL, &startup, &child))
        fail(L"Starting the bundled executable", GetLastError());

    CloseHandle(child.hThread);
    if (WaitForSingleObject(child.hProcess, INFINITE) != WAIT_OBJECT_0)
        fail(L"Waiting for the bundled executable", GetLastError());
    DWORD code;
    if (!GetExitCodeProcess(child.hProcess, &code))
        fail(L"Reading the bundled executable exit code", GetLastError());

    CloseHandle(child.hProcess);
    ExitProcess(code);
}
