"""Query the Vulkan loader without creating a logical device or rendering."""

from __future__ import annotations

import ctypes
import sys


class VkApplicationInfo(ctypes.Structure):
    _fields_ = [
        ("s_type", ctypes.c_uint32), ("next", ctypes.c_void_p),
        ("application_name", ctypes.c_char_p), ("application_version", ctypes.c_uint32),
        ("engine_name", ctypes.c_char_p), ("engine_version", ctypes.c_uint32),
        ("api_version", ctypes.c_uint32),
    ]


class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("s_type", ctypes.c_uint32), ("next", ctypes.c_void_p),
        ("flags", ctypes.c_uint32), ("application_info", ctypes.POINTER(VkApplicationInfo)),
        ("layer_count", ctypes.c_uint32), ("layers", ctypes.c_void_p),
        ("extension_count", ctypes.c_uint32), ("extensions", ctypes.c_void_p),
    ]


class VkPhysicalDevicePropertiesHeader(ctypes.Structure):
    _fields_ = [
        ("api_version", ctypes.c_uint32), ("driver_version", ctypes.c_uint32),
        ("vendor_id", ctypes.c_uint32), ("device_id", ctypes.c_uint32),
        ("device_type", ctypes.c_uint32),
    ]


def vulkan_device_available(*, gpu_only: bool = False) -> bool:
    """Check for a Vulkan device usable by the current process architecture."""
    try:
        if sys.platform == "win32":
            loader = ctypes.WinDLL("vulkan-1.dll", winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
        else:
            loader = ctypes.CDLL("libvulkan.so.1")
        create = loader.vkCreateInstance
        destroy = loader.vkDestroyInstance
        enumerate_devices = loader.vkEnumeratePhysicalDevices
        get_properties = loader.vkGetPhysicalDeviceProperties if gpu_only else None
    except (OSError, AttributeError):
        return False

    create.argtypes = [ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    destroy.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    destroy.restype = None
    enumerate_devices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p)]

    application = VkApplicationInfo(s_type=0, api_version=(1 << 22) | (2 << 12))
    configuration = VkInstanceCreateInfo(s_type=1, application_info=ctypes.pointer(application))
    instance = ctypes.c_void_p()
    if create(ctypes.byref(configuration), None, ctypes.byref(instance)) != 0:
        return False
    try:
        count = ctypes.c_uint32()
        if enumerate_devices(instance, ctypes.byref(count), None) != 0 or not count.value:
            return False
        if get_properties is None:
            return True
        devices = (ctypes.c_void_p * count.value)()
        if enumerate_devices(instance, ctypes.byref(count), devices) != 0:
            return False
        get_properties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        get_properties.restype = None
        # The Vulkan 1.0 call writes the whole fixed-size properties structure.
        # Provide aligned storage with room for its limits and sparse properties.
        storage = (ctypes.c_uint64 * 512)()
        properties = VkPhysicalDevicePropertiesHeader.from_buffer(storage)
        for device in devices[:count.value]:
            get_properties(device, ctypes.byref(storage))
            if properties.device_type in (1, 2, 3):  # Integrated, discrete, or virtual GPU.
                return True
        return False
    finally:
        destroy(instance, None)


if __name__ == "__main__":
    sys.exit(0 if vulkan_device_available(gpu_only=True) else 1)
