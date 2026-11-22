#include <mach-o/dyld.h>
#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Keep the Finder app as the process executable while sharing the exact CPython
   runtime used by VSScript and multiprocessing helpers. */
int main(int argc, char **argv) {
    char image[PATH_MAX], path[PATH_MAX], python[PATH_MAX], entry[PATH_MAX], library[PATH_MAX];
    uint32_t size = sizeof(image);
    if (_NSGetExecutablePath(image, &size) || !realpath(image, path)) return 1;
    char *separator = strrchr(path, '/');
    if (!separator) return 1;
    *separator = '\0';
    const char *runtime = "/../Resources/Runtime";
    if (snprintf(python, sizeof(python), "%s%s/python/bin/python3", path, runtime) >= sizeof(python) ||
        snprintf(library, sizeof(library), "%s%s/python/lib/libpython.dylib", path, runtime) >= sizeof(library) ||
        snprintf(entry, sizeof(entry), "%s%s/app/tools/macos_entry.py", path, runtime) >= sizeof(entry)) return 1;
    void *handle = dlopen(library, RTLD_NOW | RTLD_GLOBAL);
    if (!handle) { fprintf(stderr, "%s\n", dlerror()); return 1; }
    int (*python_main)(int, char **) = dlsym(handle, "Py_BytesMain");
    if (!python_main) return 1;
    char **args = calloc((size_t)argc + 4, sizeof(*args));
    if (!args) return 1;
    args[0] = python; args[1] = "-I"; args[2] = "-B"; args[3] = entry;
    for (int i = 1; i < argc; i++) args[i+3] = argv[i];
    int result = python_main(argc+3, args);
    free(args);
    return result;
}
