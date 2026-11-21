#define WIN32_LEAN_AND_MEAN
#include <windows.h>

typedef struct {
    DWORD size;
    DWORD attributes;
    DWORD flags;
    DWORD security_qos;
    LPSECURITY_ATTRIBUTES security;
    HANDLE template_file;
} CreateFile2Parameters;

static HANDLE WINAPI create_file_win7(LPCWSTR path, DWORD access, DWORD sharing, DWORD disposition,
                                      const CreateFile2Parameters *parameters)
{
    if (!parameters)
        return CreateFileW(path, access, sharing, NULL, disposition, FILE_ATTRIBUTE_NORMAL, NULL);
    if (parameters->size != sizeof(*parameters)) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return INVALID_HANDLE_VALUE;
    }
    return CreateFileW(path, access, sharing, parameters->security, disposition,
                       parameters->attributes | parameters->flags | parameters->security_qos,
                       parameters->template_file);
}

// Resolve the MSVC filesystem library's import inside the two compatible R79 DLLs.
HANDLE (WINAPI *__imp_CreateFile2)(LPCWSTR, DWORD, DWORD, DWORD, const CreateFile2Parameters *) = create_file_win7;
