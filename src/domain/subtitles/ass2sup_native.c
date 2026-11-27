#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>

// The public libass ASS_Image prefix, also represented by the ctypes binding.
// The renderer owns this list and its masks until the next render call.
typedef struct AssImage {
    int width, height, stride;
    const uint8_t *bitmap;
    uint32_t color;
    int x, y;
    const struct AssImage *next;
} AssImage;

typedef struct {
    int left, top, right, bottom;
} Rect;

static int clip_image(const AssImage *image, int width, int height, Rect *rect) {
    if (image->width <= 0 || image->height <= 0 || (image->color & 255) == 255) {
        return 0;
    }
    if (!image->bitmap || image->stride < image->width) {
        return -1;
    }
    int64_t right = (int64_t)image->x + image->width;
    int64_t bottom = (int64_t)image->y + image->height;
    rect->left = image->x > 0 ? image->x : 0;
    rect->top = image->y > 0 ? image->y : 0;
    rect->right = right < width ? (int)right : width;
    rect->bottom = bottom < height ? (int)bottom : height;
    return rect->left < rect->right && rect->top < rect->bottom;
}

static void include_rect(Rect *bounds, Rect rect) {
    if (rect.left < bounds->left) bounds->left = rect.left;
    if (rect.top < bounds->top) bounds->top = rect.top;
    if (rect.right > bounds->right) bounds->right = rect.right;
    if (rect.bottom > bounds->bottom) bounds->bottom = rect.bottom;
}

static void blend_mask(uint8_t *rgba, Rect bounds, Rect clip, const AssImage *image, Rect *visible) {
    size_t step = (size_t)(bounds.right - bounds.left) * 4;
    unsigned opacity = 255 - (image->color & 255);
    unsigned color[] = {image->color >> 24, (image->color >> 16) & 255, (image->color >> 8) & 255};
    for (int y = clip.top; y < clip.bottom; ++y) {
        const uint8_t *mask = image->bitmap +
            (size_t)((int64_t)y - image->y) * image->stride + ((int64_t)clip.left - image->x);
        uint8_t *dst = rgba + (size_t)(y - bounds.top) * step + (size_t)(clip.left - bounds.left) * 4;
        int first = -1;
        int last = 0;
        for (int x = clip.left; x < clip.right; ++x, ++mask, dst += 4) {
            unsigned alpha = (*mask * opacity + 127) / 255;
            if (!alpha) {
                continue;
            }
            if (first < 0) {
                first = x;
            }
            last = x + 1;
            if (!dst[3] || alpha == 255) {
                dst[0] = (uint8_t)color[0];
                dst[1] = (uint8_t)color[1];
                dst[2] = (uint8_t)color[2];
                dst[3] = (uint8_t)alpha;
            } else {
                unsigned source = alpha * 255;
                unsigned destination = (255 - alpha) * dst[3];
                unsigned combined = source + destination;
                for (int channel = 0; channel < 3; ++channel) {
                    dst[channel] = (uint8_t)((source * color[channel] + destination * dst[channel]
                                              + (combined >> 1)) / combined);
                }
                dst[3] = (uint8_t)((combined + 127) / 255);
            }
        }
        if (first >= 0) {
            Rect row = {first, y, last, y + 1};
            include_rect(visible, row);
        }
    }
}

PyObject *ass2sup_composite(PyObject *self, PyObject *args) {
    PyObject *address;
    int width, height;
    if (!PyArg_ParseTuple(args, "Oii", &address, &width, &height)) {
        return NULL;
    }
    const AssImage *head = PyLong_AsVoidPtr(address);
    if (PyErr_Occurred()) {
        return NULL;
    }
    if (width < 0 || height < 0) {
        PyErr_SetString(PyExc_ValueError, "Invalid ASS frame size");
        return NULL;
    }
    Rect bounds = {width, height, 0, 0};
    for (const AssImage *node = head; node; node = node->next) {
        Rect clip;
        int status = clip_image(node, width, height, &clip);
        if (status < 0) {
            PyErr_SetString(PyExc_ValueError, "Invalid libass mask");
            return NULL;
        }
        if (status) {
            include_rect(&bounds, clip);
        }
    }
    if (bounds.left >= bounds.right || bounds.top >= bounds.bottom) {
        Py_RETURN_NONE;
    }
    Py_ssize_t rows = bounds.bottom - bounds.top;
    Py_ssize_t columns = bounds.right - bounds.left;
    if (columns > PY_SSIZE_T_MAX / 4 / rows) {
        return PyErr_NoMemory();
    }
    Py_ssize_t row_size = columns * 4;
    PyObject *bitmap = PyBytes_FromStringAndSize(NULL, row_size * rows);
    if (!bitmap) {
        return NULL;
    }
    uint8_t *pixels = (uint8_t *)PyBytes_AS_STRING(bitmap);
    Rect visible = {width, height, 0, 0};
    Py_BEGIN_ALLOW_THREADS
    memset(pixels, 0, (size_t)(row_size * rows));
    for (const AssImage *node = head; node; node = node->next) {
        Rect clip;
        if (clip_image(node, width, height, &clip) > 0) {
            blend_mask(pixels, bounds, clip, node, &visible);
        }
    }
    Py_END_ALLOW_THREADS
    if (visible.left >= visible.right) {
        Py_DECREF(bitmap);
        Py_RETURN_NONE;
    }
    int visible_width = visible.right - visible.left;
    int visible_height = visible.bottom - visible.top;
    if (visible_width != columns || visible_height != rows) {
        Py_ssize_t crop_stride = (Py_ssize_t)visible_width * 4;
        PyObject *crop = PyBytes_FromStringAndSize(NULL, crop_stride * visible_height);
        if (!crop) {
            Py_DECREF(bitmap);
            return NULL;
        }
        uint8_t *target = (uint8_t *)PyBytes_AS_STRING(crop);
        const uint8_t *source = pixels + (visible.top - bounds.top) * row_size +
                                (Py_ssize_t)(visible.left - bounds.left) * 4;
        Py_BEGIN_ALLOW_THREADS
        for (int y = 0; y < visible_height; ++y) {
            memcpy(target + y * crop_stride, source + y * row_size, (size_t)crop_stride);
        }
        Py_END_ALLOW_THREADS
        Py_SETREF(bitmap, crop);
    }
    return Py_BuildValue("iiiiN", visible.left, visible.top, visible_width, visible_height, bitmap);
}

PyObject *ass2sup_index_alpha(PyObject *self, PyObject *args) {
    Py_buffer indexed, rgba;
    if (!PyArg_ParseTuple(args, "y*y*", &indexed, &rgba)) {
        return NULL;
    }
    PyObject *result = NULL;
    if (rgba.len % 4 || indexed.len != rgba.len / 4) {
        PyErr_SetString(PyExc_ValueError, "Indexed and RGBA pixel counts differ");
        goto done;
    }
    PyObject *remapped = PyBytes_FromStringAndSize(NULL, indexed.len);
    if (!remapped) {
        goto done;
    }
    uint8_t *out = (uint8_t *)PyBytes_AS_STRING(remapped);
    const uint8_t *colors = indexed.buf;
    const uint8_t *alpha = rgba.buf;
    uint8_t maxima[256] = {0};
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t index = 0; index < indexed.len; ++index) {
        uint8_t opacity = alpha[4 * index + 3];
        uint8_t palette = opacity ? (uint8_t)(colors[index] + 1) : 0;
        out[index] = palette;
        if (opacity > maxima[palette]) {
            maxima[palette] = opacity;
        }
    }
    Py_END_ALLOW_THREADS
    PyObject *alphas = PyBytes_FromStringAndSize((const char *)maxima, sizeof(maxima));
    if (alphas) {
        result = Py_BuildValue("NN", remapped, alphas);
    } else {
        Py_DECREF(remapped);
    }

done:
    PyBuffer_Release(&indexed);
    PyBuffer_Release(&rgba);
    return result;
}

PyObject *ass2sup_encode_rle(PyObject *self, PyObject *args) {
    Py_buffer data;
    Py_ssize_t width, height;
    if (!PyArg_ParseTuple(args, "y*nn", &data, &width, &height)) {
        return NULL;
    }
    PyObject *result = NULL;
    if (width < 0 || height < 0 || (height && width > PY_SSIZE_T_MAX / height) ||
        width * height != data.len) {
        PyErr_SetString(PyExc_ValueError, "Invalid PGS pixel buffer size");
        goto done;
    }
    if (width > (PY_SSIZE_T_MAX - 2) / 2 ||
        (height && (width * 2 + 2) > PY_SSIZE_T_MAX / height)) {
        PyErr_NoMemory();
        goto done;
    }
    // Single zero pixels cost two bytes. Other runs never cost more.
    Py_ssize_t capacity = (width * 2 + 2) * height;
    uint8_t *output = PyMem_Malloc(capacity ? (size_t)capacity : 1);
    if (!output) {
        PyErr_NoMemory();
        goto done;
    }
    uint8_t *next = output;
    const uint8_t *pixels = data.buf;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t y = 0; y < height; ++y) {
        const uint8_t *row = pixels + y * width;
        Py_ssize_t x = 0;
        while (x < width) {
            uint8_t color = row[x];
            unsigned run = 1;
            while (run < 0x3fff && run < width - x && row[x + run] == color) {
                ++run;
            }
            if (color && run <= 2) {
                *next++ = color;
                if (run == 2) {
                    *next++ = color;
                }
            } else {
                *next++ = 0;
                if (run < 0x40) {
                    *next++ = (uint8_t)(run | (color ? 0x80 : 0));
                } else {
                    *next++ = (uint8_t)(0x40 | (run >> 8) | (color ? 0x80 : 0));
                    *next++ = (uint8_t)run;
                }
                if (color) {
                    *next++ = color;
                }
            }
            x += run;
        }
        *next++ = 0;
        *next++ = 0;
    }
    Py_END_ALLOW_THREADS
    result = PyBytes_FromStringAndSize((const char *)output, next - output);
    PyMem_Free(output);

done:
    PyBuffer_Release(&data);
    return result;
}
