#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <datetime.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    int kind;
    const void *data;
} Text;

static Py_UCS4 character(Text text, Py_ssize_t index) {
    return PyUnicode_READ(text.kind, text.data, index);
}

static void strip_field(Text text, Py_ssize_t *start, Py_ssize_t *end) {
    while (*start < *end && Py_UNICODE_ISSPACE(character(text, *start))) {
        ++*start;
    }
    while (*start < *end && Py_UNICODE_ISSPACE(character(text, *end - 1))) {
        --*end;
    }
}

static int read_two_digits(Text text, Py_ssize_t start) {
    Py_UCS4 first = character(text, start);
    Py_UCS4 second = character(text, start + 1);
    if (first < '0' || first > '9' || second < '0' || second > '9') {
        return -1;
    }
    return (int)((first - '0') * 10 + second - '0');
}

static int64_t read_timestamp(Text text, Py_ssize_t start, Py_ssize_t end) {
    // Other timestamp spellings are interpreted by the Python parser.
    Py_ssize_t suffix = end - 9;
    if (suffix <= start || suffix - start > 6 ||
        character(text, suffix) != ':' || character(text, suffix + 3) != ':' ||
        character(text, suffix + 6) != '.') {
        return -1;
    }
    int minutes = read_two_digits(text, suffix + 1);
    int seconds = read_two_digits(text, suffix + 4);
    int fraction = read_two_digits(text, suffix + 7);
    if (minutes < 0 || seconds < 0 || fraction < 0) {
        return -1;
    }
    int64_t hours = 0;
    for (Py_ssize_t index = start; index < suffix; ++index) {
        Py_UCS4 digit = character(text, index);
        if (digit < '0' || digit > '9') {
            return -1;
        }
        hours = hours * 10 + (digit - '0');
    }
    return ((hours * 60 + minutes) * 60 + seconds) * 100 + fraction;
}

static PyObject *timestamp(int64_t centiseconds) {
    return PyDelta_FromDSU((int)(centiseconds / 8640000),
                           (int)(centiseconds / 100 % 86400),
                           (int)(centiseconds % 100) * 10000);
}

// A line outside the fast path is returned intact for the Python parser.
static int read_event(PyObject *line, Text text, Py_ssize_t length, PyObject *attributes,
                      int start_column, int end_column, PyObject *events, PyObject *event_type,
                      int64_t *maximum_end) {
    Py_ssize_t colon = PyUnicode_FindChar(line, ':', 0, length, 1);
    if (colon < 0) {
        return colon == -2 ? -1 : 0;
    }
    Py_ssize_t field_count = PyTuple_GET_SIZE(attributes);
    int duration_only = events == Py_None;
    Py_ssize_t last_column = duration_only
        ? (start_column > end_column ? start_column : end_column) : field_count - 1;
    PyObject *event = duration_only ? NULL : PyObject_CallNoArgs(event_type);
    if (!duration_only && !event) {
        return -1;
    }

    Py_ssize_t next = colon + 1;
    int64_t end_time = -1;
    for (Py_ssize_t column = duration_only ? 1 : 0; column <= last_column; ++column) {
        Py_ssize_t start = column == 0 ? 0 : next;
        Py_ssize_t end = length;
        if (column == 0) {
            end = colon;
        } else if (column < field_count - 1) {
            end = PyUnicode_FindChar(line, ',', start, length, 1);
            if (end < 0) {
                Py_XDECREF(event);
                return end == -2 ? -1 : 0;
            }
            next = end + 1;
        }
        int is_time = column == start_column || column == end_column;
        if (duration_only && !is_time) {
            continue;
        }
        if (column != field_count - 1) {
            strip_field(text, &start, &end);
        }
        PyObject *value;
        if (is_time) {
            int64_t ticks = read_timestamp(text, start, end);
            if (ticks < 0) {
                Py_XDECREF(event);
                return 0;
            }
            if (duration_only) {
                if (column == end_column) {
                    end_time = ticks;
                }
                continue;
            }
            value = timestamp(ticks);
        } else {
            value = PyUnicode_Substring(line, start, end);
        }
        if (!value) {
            Py_DECREF(event);
            return -1;
        }
        int status = PyObject_SetAttr(event, PyTuple_GET_ITEM(attributes, column), value);
        Py_DECREF(value);
        if (status < 0) {
            Py_DECREF(event);
            return -1;
        }
    }
    if (duration_only) {
        if (end_time > *maximum_end) {
            *maximum_end = end_time;
        }
        return 1;
    }
    int status = PyList_Append(events, event);
    Py_DECREF(event);
    return status < 0 ? -1 : 1;
}

static PyObject *parse_events(PyObject *self, PyObject *args) {
    PyObject *lines, *attributes, *events, *event_type;
    int start_column, end_column;
    Py_ssize_t limit;
    if (!PyArg_ParseTuple(args, "OO!iiOOn", &lines, &PyTuple_Type, &attributes,
                          &start_column, &end_column, &events, &event_type, &limit)) {
        return NULL;
    }
    Py_ssize_t field_count = PyTuple_GET_SIZE(attributes);
    if (limit < 1 || !PyIter_Check(lines) || (events != Py_None && !PyList_Check(events)) ||
        start_column < 1 || start_column >= field_count - 1 ||
        end_column < 1 || end_column >= field_count - 1) {
        PyErr_SetString(PyExc_ValueError, "Invalid ASS event reader arguments");
        return NULL;
    }

    int64_t maximum_end = -1;
    PyObject *pending = NULL;
    Py_ssize_t index;
    for (index = 0; index < limit; ++index) {
        PyObject *line = PyIter_Next(lines);
        if (!line) {
            if (PyErr_Occurred()) {
                return NULL;
            }
            break;
        }
        if (!PyUnicode_CheckExact(line)) {
            pending = line;
            break;
        }
        Text text = {PyUnicode_KIND(line), PyUnicode_DATA(line)};
        Py_ssize_t length = PyUnicode_GET_LENGTH(line);
        Py_UCS4 first = length ? character(text, 0) : 0;
        if (first == '[' || (first == ';' && length >= 3 &&
            character(text, 1) == ' ' && character(text, 2) == '[')) {
            pending = line;
            break;
        }
        if (first == ';' || (length == 1 && first == '\n')) {
            Py_DECREF(line);
            continue;
        }
        while (length && (character(text, length - 1) == '\r' ||
                          character(text, length - 1) == '\n')) {
            --length;
        }
        int status = read_event(line, text, length, attributes, start_column, end_column,
                                events, event_type, &maximum_end);
        if (!status) {
            pending = line;
            break;
        }
        Py_DECREF(line);
        if (status < 0) {
            return NULL;
        }
    }
    PyObject *latest = maximum_end < 0 ? Py_NewRef(Py_None) : timestamp(maximum_end);
    if (!latest) {
        Py_XDECREF(pending);
        return NULL;
    }
    return Py_BuildValue("NNi", pending ? pending : Py_NewRef(Py_None), latest,
                         index == limit);
}

static int valid_range(PyObject *events, Py_ssize_t start, Py_ssize_t end) {
    if (start < 0 || end < start || end > PyList_GET_SIZE(events)) {
        PyErr_SetString(PyExc_ValueError, "Invalid ASS event range");
        return 0;
    }
    return 1;
}

static int shift_timestamp(PyObject *event, PyObject *key, PyObject *offset) {
    PyObject *old = PyObject_GetAttr(event, key);
    if (!old) {
        return -1;
    }
    PyObject *value;
    if (PyDelta_CheckExact(old) && PyDelta_CheckExact(offset)) {
        value = PyDelta_FromDSU(
            PyDateTime_DELTA_GET_DAYS(old) + PyDateTime_DELTA_GET_DAYS(offset),
            PyDateTime_DELTA_GET_SECONDS(old) + PyDateTime_DELTA_GET_SECONDS(offset),
            PyDateTime_DELTA_GET_MICROSECONDS(old) + PyDateTime_DELTA_GET_MICROSECONDS(offset));
    } else {
        value = PyNumber_Add(old, offset);
    }
    Py_DECREF(old);
    if (!value) {
        return -1;
    }
    int status = PyObject_SetAttr(event, key, value);
    Py_DECREF(value);
    return status;
}

static PyObject *shift_events(PyObject *self, PyObject *args) {
    PyObject *events, *offset, *start_key, *end_key;
    Py_ssize_t start, end;
    if (!PyArg_ParseTuple(args, "O!OOOnn", &PyList_Type, &events, &offset,
                          &start_key, &end_key, &start, &end) ||
        !valid_range(events, start, end)) {
        return NULL;
    }
    for (Py_ssize_t index = start; index < end; ++index) {
        PyObject *event = PyList_GET_ITEM(events, index);
        if (shift_timestamp(event, start_key, offset) < 0 ||
            shift_timestamp(event, end_key, offset) < 0) {
            return NULL;
        }
    }
    Py_RETURN_NONE;
}

static PyObject *copy_event(PyObject *event, PyObject *event_type) {
    PyObject *fields = PyObject_GenericGetDict(event, NULL);
    if (!fields) {
        return NULL;
    }
    PyObject *duplicate = PyDict_Copy(fields);
    Py_DECREF(fields);
    if (!duplicate) {
        return NULL;
    }
    PyObject *result = PyObject_CallNoArgs(event_type);
    if (result && PyObject_GenericSetDict(result, duplicate, NULL) < 0) {
        Py_CLEAR(result);
    }
    Py_DECREF(duplicate);
    return result;
}

static int map_style(PyObject *event, PyObject *styles, PyObject *key) {
    PyObject *original = PyObject_GetAttr(event, key);
    if (!original) {
        return -1;
    }
    PyObject *mapped = PyDict_GetItemWithError(styles, original);
    Py_DECREF(original);
    if (mapped) {
        return PyObject_SetAttr(event, key, mapped);
    }
    return PyErr_Occurred() ? -1 : 0;
}

static PyObject *append_events(PyObject *self, PyObject *args) {
    PyObject *target, *source, *offset, *styles, *event_type, *start_key, *end_key, *style_key;
    Py_ssize_t start, end;
    if (!PyArg_ParseTuple(args, "O!O!OO!OOOOnn", &PyList_Type, &target, &PyList_Type, &source,
                          &offset, &PyDict_Type, &styles, &event_type, &start_key, &end_key,
                          &style_key, &start, &end) || !valid_range(source, start, end)) {
        return NULL;
    }
    for (Py_ssize_t index = start; index < end; ++index) {
        PyObject *event = copy_event(PyList_GET_ITEM(source, index), event_type);
        if (!event) {
            return NULL;
        }
        int written = shift_timestamp(event, start_key, offset) == 0 &&
                      shift_timestamp(event, end_key, offset) == 0 &&
                      map_style(event, styles, style_key) == 0 &&
                      PyList_Append(target, event) == 0;
        Py_DECREF(event);
        if (!written) {
            return NULL;
        }
    }
    Py_RETURN_NONE;
}

static PyObject *clock_text(PyObject *delta) {
    // Match the existing timedelta display, including day prefixes and truncation.
    char result[64];
    char *next = result;
    int days = PyDateTime_DELTA_GET_DAYS(delta);
    int seconds = PyDateTime_DELTA_GET_SECONDS(delta);
    int centiseconds = PyDateTime_DELTA_GET_MICROSECONDS(delta) / 10000;
    if (days) {
        int length = PyOS_snprintf(result, sizeof(result), "%d day%s, ", days,
                                   days == -1 || days == 1 ? "" : "s");
        if (length < 0 || length >= (int)sizeof(result) - 11) {
            PyErr_SetString(PyExc_ValueError, "Could not format ASS timestamp");
            return NULL;
        }
        next += length;
    }
    int hours = seconds / 3600;
    int minutes = seconds / 60 % 60;
    seconds %= 60;
    if (hours >= 10) {
        *next++ = (char)('0' + hours / 10);
    }
    *next++ = (char)('0' + hours % 10);
    *next++ = ':';
    *next++ = (char)('0' + minutes / 10);
    *next++ = (char)('0' + minutes % 10);
    *next++ = ':';
    *next++ = (char)('0' + seconds / 10);
    *next++ = (char)('0' + seconds % 10);
    *next++ = '.';
    *next++ = (char)('0' + centiseconds / 10);
    *next++ = (char)('0' + centiseconds % 10);
    return PyUnicode_FromStringAndSize(result, next - result);
}

static PyObject *format_field(PyObject *event, PyObject *key, PyObject *fallback, int is_time) {
    PyObject *value = PyObject_GetAttr(event, key);
    if (!value) {
        if (!PyErr_ExceptionMatches(PyExc_AttributeError)) {
            return NULL;
        }
        PyErr_Clear();
        value = Py_NewRef(fallback);
    }
    if (is_time && PyDelta_CheckExact(value)) {
        PyObject *text = clock_text(value);
        Py_DECREF(value);
        return text;
    }
    PyObject *text = PyObject_Str(value);
    Py_DECREF(value);
    if (!text || !is_time) {
        return text;
    }
    Py_ssize_t length = PyUnicode_GET_LENGTH(text);
    Py_ssize_t colon = PyUnicode_FindChar(text, ':', 0, length, -1);
    if (colon == -2) {
        Py_DECREF(text);
        return NULL;
    }
    Py_ssize_t suffix = length - colon - 1;
    if (suffix == 5) {
        return text;
    }
    PyObject *formatted;
    if (suffix > 5) {
        formatted = PyUnicode_Substring(text, 0, length + 5 - suffix);
    } else {
        formatted = PyUnicode_FromFormat("%U.00", text);
    }
    Py_DECREF(text);
    return formatted;
}

static PyObject *render_events(PyObject *self, PyObject *args) {
    PyObject *events, *attributes, *timing, *deleted;
    Py_ssize_t start, end;
    if (!PyArg_ParseTuple(args, "O!O!O!O!nn", &PyList_Type, &events, &PyTuple_Type, &attributes,
                          &PyTuple_Type, &timing, &PySet_Type, &deleted, &start, &end) ||
        !valid_range(events, start, end)) {
        return NULL;
    }
    Py_ssize_t field_count = PyTuple_GET_SIZE(attributes);
    if (field_count == 0 || PyTuple_GET_SIZE(timing) != field_count) {
        PyErr_SetString(PyExc_ValueError, "Invalid ASS event format");
        return NULL;
    }
    PyObject *pieces = PyList_New(0);
    PyObject *empty = PyUnicode_FromString("");
    PyObject *dialogue = PyUnicode_FromString("Dialogue");
    PyObject *colon = PyUnicode_FromString(": ");
    PyObject *comma = PyUnicode_FromString(",");
    PyObject *newline = PyUnicode_FromString("\n");
    PyObject *result = NULL;
    if (!pieces || !empty || !dialogue || !colon || !comma || !newline) {
        goto done;
    }

    for (Py_ssize_t index = start; index < end; ++index) {
        if (PySet_GET_SIZE(deleted)) {
            PyObject *number = PyLong_FromSsize_t(index);
            if (!number) {
                goto done;
            }
            int skip = PySet_Contains(deleted, number);
            Py_DECREF(number);
            if (skip < 0) {
                goto done;
            }
            if (skip) {
                continue;
            }
        }
        PyObject *event = PyList_GET_ITEM(events, index);
        for (Py_ssize_t column = 0; column < field_count; ++column) {
            if (column && PyList_Append(pieces, column == 1 ? colon : comma) < 0) {
                goto done;
            }
            PyObject *text = format_field(event, PyTuple_GET_ITEM(attributes, column),
                                          column ? empty : dialogue,
                                          PyTuple_GET_ITEM(timing, column) == Py_True);
            if (!text) {
                goto done;
            }
            int status = PyList_Append(pieces, text);
            Py_DECREF(text);
            if (status < 0) {
                goto done;
            }
        }
        if ((field_count == 1 && PyList_Append(pieces, colon) < 0) ||
            PyList_Append(pieces, newline) < 0) {
            goto done;
        }
    }
    result = PyUnicode_Join(empty, pieces);

done:
    Py_XDECREF(pieces);
    Py_XDECREF(empty);
    Py_XDECREF(dialogue);
    Py_XDECREF(colon);
    Py_XDECREF(comma);
    Py_XDECREF(newline);
    return result;
}

static int valid_utf8(const unsigned char *cursor, const unsigned char *end) {
    while (cursor < end) {
        if (end - cursor >= (Py_ssize_t)sizeof(uint64_t)) {
            uint64_t word;
            memcpy(&word, cursor, sizeof(word));
            if (!(word & UINT64_C(0x8080808080808080))) {
                cursor += sizeof(word);
                continue;
            }
        }
        unsigned int value = *cursor++;
        if (value < 0x80) {
            continue;
        }
        unsigned int minimum;
        int continuation;
        if (value >= 0xc2 && value <= 0xdf) {
            continuation = 1;
            minimum = 0x80;
            value &= 0x1f;
        } else if (value >= 0xe0 && value <= 0xef) {
            continuation = 2;
            minimum = 0x800;
            value &= 0x0f;
        } else if (value >= 0xf0 && value <= 0xf4) {
            continuation = 3;
            minimum = 0x10000;
            value &= 0x07;
        } else {
            return 0;
        }
        if (end - cursor < continuation) {
            return 0;
        }
        for (int index = 0; index < continuation; ++index) {
            unsigned int byte = *cursor++;
            if ((byte & 0xc0) != 0x80) {
                return 0;
            }
            value = (value << 6) | (byte & 0x3f);
        }
        if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) {
            return 0;
        }
    }
    return 1;
}

static int equals(const unsigned char *start, size_t length, const char *expected) {
    return length == strlen(expected) && memcmp(start, expected, length) == 0;
}

static int64_t scan_utf8_events(const unsigned char *cursor, const unsigned char *end) {
    if (end - cursor >= 3 && memcmp(cursor, "\xef\xbb\xbf", 3) == 0) {
        cursor += 3;
    }
    if (!valid_utf8(cursor, end)) {
        return -1;
    }

    // The focused scan handles the standard event layout. The stream parser
    // handles other layouts, encodings, and row spellings.
    int in_events = 0;
    int has_format = 0;
    int64_t maximum = 0;
    while (cursor < end) {
        const unsigned char *newline = memchr(cursor, '\n', (size_t)(end - cursor));
        const unsigned char *last = newline ? newline : end;
        if (newline && last > cursor && last[-1] == '\r') {
            --last;
        }
        size_t length = (size_t)(last - cursor);
        const unsigned char *line = cursor;
        cursor = newline ? newline + 1 : end;
        if (memchr(line, '\r', length)) {
            return -1;
        }
        if (!length) {
            continue;
        }
        if (newline && last[-1] == ']' &&
            (*line == '[' || (length >= 3 && memcmp(line, "; [", 3) == 0))) {
            if (equals(line, length, "[Events]")) {
                if (in_events || has_format) {
                    return -1;
                }
                in_events = 1;
            } else {
                if (!equals(line, length, "[Script Info]") &&
                    !equals(line, length, "[V4+ Styles]") &&
                    !equals(line, length, "[V4 Styles]") &&
                    !equals(line, length, "[Aegisub Project Garbage]") &&
                    !equals(line, length, "[Aegisub Extradata]") &&
                    !equals(line, length, "[Fonts]") &&
                    !equals(line, length, "[Graphics]")) {
                    return -1;
                }
                in_events = 0;
            }
            continue;
        }
        if (!in_events || *line == ';') {
            continue;
        }
        if (!has_format) {
            if (!equals(line, length, "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")) {
                return -1;
            }
            has_format = 1;
            continue;
        }
        const unsigned char *colon = memchr(line, ':', length);
        if (!colon) {
            return -1;
        }
        const unsigned char *start = memchr(colon + 1, ',', (size_t)(last - colon - 1));
        if (!start) {
            return -1;
        }
        const unsigned char *middle = memchr(start + 1, ',', (size_t)(last - start - 1));
        if (!middle) {
            return -1;
        }
        const unsigned char *stop = memchr(middle + 1, ',', (size_t)(last - middle - 1));
        if (!stop) {
            return -1;
        }
        Text text = {PyUnicode_1BYTE_KIND, line};
        Py_ssize_t first = start + 1 - line;
        Py_ssize_t finish = middle - line;
        strip_field(text, &first, &finish);
        if (read_timestamp(text, first, finish) < 0) {
            return -1;
        }
        first = middle + 1 - line;
        finish = stop - line;
        strip_field(text, &first, &finish);
        int64_t elapsed = read_timestamp(text, first, finish);
        if (elapsed < 0) {
            return -1;
        }
        if (elapsed > maximum) {
            maximum = elapsed;
        }
    }
    return has_format ? maximum : -1;
}

static PyObject *scan_duration(PyObject *self, PyObject *input) {
    char *data;
    Py_ssize_t size;
    if (PyBytes_AsStringAndSize(input, &data, &size) < 0) {
        return NULL;
    }
    int64_t maximum;
    Py_BEGIN_ALLOW_THREADS
    maximum = scan_utf8_events((const unsigned char *)data, (const unsigned char *)data + size);
    Py_END_ALLOW_THREADS
    return maximum < 0 ? Py_NewRef(Py_None) : PyFloat_FromDouble((double)maximum / 100.0);
}

PyObject *ass2sup_composite(PyObject *self, PyObject *args);
PyObject *ass2sup_index_alpha(PyObject *self, PyObject *args);
PyObject *ass2sup_encode_rle(PyObject *self, PyObject *args);

static PyMethodDef methods[] = {
    {"composite_ass_images", ass2sup_composite, METH_VARARGS, NULL},
    {"index_pgs_alpha", ass2sup_index_alpha, METH_VARARGS, NULL},
    {"encode_pgs_rle", ass2sup_encode_rle, METH_VARARGS, NULL},
    {"scan_duration", scan_duration, METH_O, NULL},
    {"parse_events", parse_events, METH_VARARGS, NULL},
    {"shift_events", shift_events, METH_VARARGS, NULL},
    {"append_events", append_events, METH_VARARGS, NULL},
    {"render_events", render_events, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_bluraysubtitle_ass", NULL, -1, methods
};

PyMODINIT_FUNC PyInit__bluraysubtitle_ass(void) {
    PyDateTime_IMPORT;
    if (!PyDateTimeAPI) {
        return NULL;
    }
    return PyModule_Create(&module);
}
