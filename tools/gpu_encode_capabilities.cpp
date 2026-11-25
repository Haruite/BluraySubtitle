// Query the installed hardware driver before FFmpeg receives any video frames.
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#ifdef BLURAY_GPU_MF
#include <mfapi.h>
#include <mfidl.h>
#endif
#else
#include <dlfcn.h>
#ifdef __APPLE__
#include <VideoToolbox/VideoToolbox.h>
#endif
#endif

#include <vulkan/vulkan.h>

#ifdef BLURAY_GPU_NVENC
#include <ffnvcodec/nvEncodeAPI.h>
#ifndef _WIN32
#include <ffnvcodec/dynlink_cuda.h>
#endif
#endif

#ifdef BLURAY_GPU_QSV
#include <vpl/mfxdispatcher.h>
#include <vpl/mfxstructures.h>
#ifndef _WIN32
#include <fcntl.h>
#include <unistd.h>
#include <va/va_drm.h>
#endif
#endif

#ifdef BLURAY_GPU_AMF
#include <AMF/core/Factory.h>
#include <AMF/components/VideoEncoderVCE.h>
#include <AMF/components/VideoEncoderHEVC.h>
#include <AMF/components/VideoEncoderAV1.h>
#endif

namespace {
using Modes = std::set<std::tuple<std::string, int, std::string>>;

void check_status(const char *operation, long long status) {
    if (status != 0)
        throw std::runtime_error(std::string(operation) + ": " + std::to_string(status));
}

class Library {
public:
    explicit Library(const char *name)
#ifdef _WIN32
        : handle_(LoadLibraryExA(name, nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32)) {
#else
        : handle_(dlopen(name, RTLD_NOW | RTLD_LOCAL)) {
#endif
        if (!handle_) {
#ifdef _WIN32
            std::string detail = std::to_string(GetLastError());
#else
            std::string detail = dlerror();
#endif
            throw std::runtime_error(std::string("Could not load ") + name + ": " + detail);
        }
    }
    Library(const Library &) = delete;
    Library &operator=(const Library &) = delete;

    ~Library() {
#ifdef _WIN32
        FreeLibrary(handle_);
#else
        dlclose(handle_);
#endif
    }

    template<typename Function>
    Function get(const char *name) const {
#ifdef _WIN32
        auto address = GetProcAddress(handle_, name);
#else
        auto address = dlsym(handle_, name);
#endif
        if (!address)
            throw std::runtime_error(std::string("Missing driver entry point ") + name);
        Function function;
        static_assert(sizeof(function) == sizeof(address));
        std::memcpy(&function, &address, sizeof(function));
        return function;
    }

private:
#ifdef _WIN32
    HMODULE handle_;
#else
    void *handle_;
#endif
};

std::string hex_id(const uint8_t *bytes, size_t size) {
    std::ostringstream value;
    value << std::hex << std::setfill('0');
    for (size_t i = 0; i < size; ++i)
        value << std::setw(2) << static_cast<unsigned>(bytes[i]);
    return value.str();
}

void list_vulkan_devices() {
#ifdef _WIN32
    Library loader("vulkan-1.dll");
#elif defined(__APPLE__)
    Library loader("@loader_path/../lib/libvulkan.1.dylib");
#else
    Library loader("libvulkan.so.1");
#endif
    auto create_instance = loader.get<PFN_vkCreateInstance>("vkCreateInstance");
    auto destroy_instance = loader.get<PFN_vkDestroyInstance>("vkDestroyInstance");
    auto enumerate_devices = loader.get<PFN_vkEnumeratePhysicalDevices>("vkEnumeratePhysicalDevices");
    auto properties = loader.get<PFN_vkGetPhysicalDeviceProperties2>("vkGetPhysicalDeviceProperties2");
    auto queue_properties = loader.get<PFN_vkGetPhysicalDeviceQueueFamilyProperties>("vkGetPhysicalDeviceQueueFamilyProperties");
    auto format_properties = loader.get<PFN_vkGetPhysicalDeviceFormatProperties>("vkGetPhysicalDeviceFormatProperties");

    VkApplicationInfo application = {};
    application.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    application.apiVersion = VK_API_VERSION_1_3;
    VkInstanceCreateInfo configuration = {};
    configuration.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    configuration.pApplicationInfo = &application;
#ifdef __APPLE__
    const char *portability = VK_KHR_PORTABILITY_ENUMERATION_EXTENSION_NAME;
    configuration.flags = VK_INSTANCE_CREATE_ENUMERATE_PORTABILITY_BIT_KHR;
    configuration.enabledExtensionCount = 1;
    configuration.ppEnabledExtensionNames = &portability;
#endif
    VkInstance instance = nullptr;
    check_status("vkCreateInstance", create_instance(&configuration, nullptr, &instance));
    auto release = [destroy_instance](VkInstance value) { destroy_instance(value, nullptr); };
    std::unique_ptr<std::remove_pointer_t<VkInstance>, decltype(release)> owner(instance, release);

    uint32_t count = 0;
    check_status("vkEnumeratePhysicalDevices", enumerate_devices(instance, &count, nullptr));
    std::vector<VkPhysicalDevice> devices(count);
    if (count)
        check_status("vkEnumeratePhysicalDevices", enumerate_devices(instance, &count, devices.data()));
    for (uint32_t index = 0; index < count; ++index) {
        const auto device = devices[index];
        VkPhysicalDeviceIDProperties identity = {};
        identity.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
        VkPhysicalDeviceProperties2 info = {};
        info.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
        info.pNext = &identity;
#if !defined(_WIN32) && !defined(__APPLE__)
        auto enumerate_extensions = loader.get<PFN_vkEnumerateDeviceExtensionProperties>("vkEnumerateDeviceExtensionProperties");
        VkPhysicalDeviceDrmPropertiesEXT drm = {};
        drm.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT;
        uint32_t extension_count = 0;
        if (enumerate_extensions(device, nullptr, &extension_count, nullptr) == VK_SUCCESS && extension_count) {
            std::vector<VkExtensionProperties> extensions(extension_count);
            if (enumerate_extensions(device, nullptr, &extension_count, extensions.data()) == VK_SUCCESS &&
                    std::any_of(extensions.begin(), extensions.end(), [](const auto &extension) {
                        return std::strcmp(extension.extensionName, VK_EXT_PHYSICAL_DEVICE_DRM_EXTENSION_NAME) == 0;
                    }))
                identity.pNext = &drm;
        }
#endif
        properties(device, &info);
        const auto &details = info.properties;
        std::cerr << "Vulkan[" << index << "]: " << details.deviceName << " ("
                  << VK_API_VERSION_MAJOR(details.apiVersion) << '.' << VK_API_VERSION_MINOR(details.apiVersion)
                  << ", device type " << details.deviceType << ")\n";
        if (details.apiVersion < VK_API_VERSION_1_3 ||
                (details.deviceType != VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU &&
                 details.deviceType != VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU &&
                 details.deviceType != VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU))
            continue;

        uint32_t queue_count = 0;
        queue_properties(device, &queue_count, nullptr);
        std::vector<VkQueueFamilyProperties> queues(queue_count);
        if (queue_count)
            queue_properties(device, &queue_count, queues.data());
        if (std::none_of(queues.begin(), queues.end(), [](const auto &queue) {
                return queue.queueCount && (queue.queueFlags & VK_QUEUE_COMPUTE_BIT);
            }))
            continue;

        // FFV1's planar input can be uploaded as separate single-component images.
        auto supports_plane = [&](VkFormat format) {
            VkFormatProperties plane = {};
            format_properties(device, format, &plane);
            constexpr auto required = VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT | VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
            return (plane.optimalTilingFeatures & required) == required;
        };
        std::string depths = supports_plane(VK_FORMAT_R8_UNORM) ? "8" : "";
        if (supports_plane(VK_FORMAT_R16_UNORM))
            depths += depths.empty() ? "10,12" : ",10,12";
        if (depths.empty())
            continue;

        const auto uuid = hex_id(identity.deviceUUID, VK_UUID_SIZE);
        std::string hardware_id = "uuid:" + uuid;
#ifdef _WIN32
        if (identity.deviceLUIDValid)
            hardware_id = "luid:" + hex_id(identity.deviceLUID, VK_LUID_SIZE);
#elif defined(__APPLE__)
        if (details.vendorID == 0x106b && details.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU)
            hardware_id = "apple:integrated";
#else
        if (drm.hasRender && details.vendorID != 0x10de)
            hardware_id = "render:" + std::to_string(drm.renderMinor);
#endif
        std::string name = details.deviceName;
        std::replace_if(name.begin(), name.end(), [](char character) {
            return character == '\t' || character == '\r' || character == '\n';
        }, ' ');
        std::cout << std::hex << details.vendorID << std::dec << '\t' << uuid << '\t'
                  << hardware_id << '\t' << depths << '\t' << name << '\n';
    }
}

#ifdef _WIN32
struct ReleaseCom {
    void operator()(IUnknown *value) const { value->Release(); }
};

template<typename Interface>
using ComPtr = std::unique_ptr<Interface, ReleaseCom>;

ComPtr<IDXGIAdapter> dxgi_adapter(unsigned index) {
    IDXGIFactory1 *factory = nullptr;
    check_status("CreateDXGIFactory1", CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIFactory1> owner(factory);
    IDXGIAdapter *adapter = nullptr;
    check_status("IDXGIFactory::EnumAdapters", factory->EnumAdapters(index, &adapter));
    return ComPtr<IDXGIAdapter>(adapter);
}

ComPtr<ID3D11Device> d3d11_device(unsigned index) {
    auto adapter = dxgi_adapter(index);
    ID3D11Device *device = nullptr;
    check_status("D3D11CreateDevice", D3D11CreateDevice(
        adapter.get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
        nullptr, 0, D3D11_SDK_VERSION, &device, nullptr, nullptr));
    return ComPtr<ID3D11Device>(device);
}
#endif

#ifdef BLURAY_GPU_NVENC
Modes nvenc_modes(unsigned index) {
#ifdef _WIN32
#if defined(_M_ARM64) || defined(__aarch64__)
    Library encoder_library("nvEncodeAPIa64.dll");
#else
    Library encoder_library("nvEncodeAPI64.dll");
#endif
    auto device = d3d11_device(index);
    void *native_device = device.get();
    auto device_type = NV_ENC_DEVICE_TYPE_DIRECTX;
#else
    Library encoder_library("libnvidia-encode.so.1");
    Library cuda("libcuda.so.1");
    auto init_cuda = cuda.get<tcuInit *>("cuInit");
    auto get_cuda_device = cuda.get<tcuDeviceGet *>("cuDeviceGet");
    auto create_context = cuda.get<tcuCtxCreate_v2 *>("cuCtxCreate_v2");
    auto destroy_context = cuda.get<tcuCtxDestroy_v2 *>("cuCtxDestroy_v2");
    CUdevice adapter;
    CUcontext context = nullptr;
    check_status("cuInit", init_cuda(0));
    check_status("cuDeviceGet", get_cuda_device(&adapter, index));
    check_status("cuCtxCreate_v2", create_context(&context, 0, adapter));
    std::unique_ptr<std::remove_pointer_t<CUcontext>, tcuCtxDestroy_v2 *> cuda_context(context, destroy_context);
    void *native_device = context;
    auto device_type = NV_ENC_DEVICE_TYPE_CUDA;
#endif

    auto maximum_version = encoder_library.get<NVENCSTATUS (NVENCAPI *)(uint32_t *)>(
        "NvEncodeAPIGetMaxSupportedVersion");
    uint32_t driver_version = 0;
    check_status("NvEncodeAPIGetMaxSupportedVersion", maximum_version(&driver_version));
    std::cerr << "NVENC driver API " << (driver_version >> 4) << '.' << (driver_version & 15) << '\n';
    auto create_api = encoder_library.get<NVENCSTATUS (NVENCAPI *)(NV_ENCODE_API_FUNCTION_LIST *)>(
        "NvEncodeAPICreateInstance");
    NV_ENCODE_API_FUNCTION_LIST api = {};
    api.version = NV_ENCODE_API_FUNCTION_LIST_VER;
    check_status("NvEncodeAPICreateInstance", create_api(&api));

    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS session = {};
    session.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    session.deviceType = device_type;
    session.device = native_device;
    session.apiVersion = NVENCAPI_VERSION;
    void *encoder = nullptr;
    check_status("NvEncOpenEncodeSessionEx", api.nvEncOpenEncodeSessionEx(&session, &encoder));
    std::unique_ptr<void, PNVENCDESTROYENCODER> owner(encoder, api.nvEncDestroyEncoder);

    uint32_t count = 0;
    check_status("NvEncGetEncodeGUIDCount", api.nvEncGetEncodeGUIDCount(encoder, &count));
    std::vector<GUID> guids(count);
    if (count)
        check_status("NvEncGetEncodeGUIDs", api.nvEncGetEncodeGUIDs(encoder, guids.data(), count, &count));
    const std::pair<GUID, const char *> codecs[] = {
        {NV_ENC_CODEC_H264_GUID, "h264"}, {NV_ENC_CODEC_HEVC_GUID, "hevc"}, {NV_ENC_CODEC_AV1_GUID, "av1"},
    };
    Modes modes;
    for (uint32_t i = 0; i < count; ++i) {
        for (const auto &[guid, codec] : codecs) {
            if (std::memcmp(&guid, &guids[i], sizeof(GUID)) != 0)
                continue;
            uint32_t available = 0;
            check_status("NvEncGetInputFormatCount", api.nvEncGetInputFormatCount(encoder, guid, &available));
            std::vector<NV_ENC_BUFFER_FORMAT> formats(available);
            if (available)
                check_status("NvEncGetInputFormats", api.nvEncGetInputFormats(
                    encoder, guid, formats.data(), available, &available));
            for (uint32_t format = 0; format < available; ++format) {
                if (formats[format] == NV_ENC_BUFFER_FORMAT_NV12)
                    modes.emplace(codec, 8, "");
                if (formats[format] == NV_ENC_BUFFER_FORMAT_YUV420_10BIT) {
                    NV_ENC_CAPS_PARAM caps = {};
                    caps.version = NV_ENC_CAPS_PARAM_VER;
                    caps.capsToQuery = NV_ENC_CAPS_SUPPORT_10BIT_ENCODE;
                    int ten_bit = 0;
                    check_status("NvEncGetEncodeCaps", api.nvEncGetEncodeCaps(encoder, guid, &caps, &ten_bit));
                    if (ten_bit)
                        modes.emplace(codec, 10, "");
                }
            }
        }
    }
    return modes;
}
#endif

#ifdef BLURAY_GPU_QSV
#ifndef _WIN32
Modes intel_vaapi_modes(const std::string &adapter) {
    int descriptor = open(adapter.c_str(), O_RDWR | O_CLOEXEC);
    if (descriptor < 0)
        throw std::runtime_error("open " + adapter + ": " + std::strerror(errno));
    auto close_device = [](int *fd) { close(*fd); };
    std::unique_ptr<int, decltype(close_device)> device_owner(&descriptor, close_device);
    VADisplay display = vaGetDisplayDRM(descriptor);
    if (!display)
        throw std::runtime_error("vaGetDisplayDRM failed for " + adapter);
    int major = 0, minor = 0;
    check_status("vaInitialize", vaInitialize(display, &major, &minor));
    std::unique_ptr<void, decltype(&vaTerminate)> display_owner(display, vaTerminate);
    std::cerr << "VA-API " << major << '.' << minor << " " << vaQueryVendorString(display) << '\n';

    struct Profile { VAProfile profile; const char *codec; int depth; };
    const Profile profiles[] = {
        {VAProfileH264Main, "h264", 8}, {VAProfileH264High, "h264", 8},
#if VA_CHECK_VERSION(1, 20, 0)
        {VAProfileH264High10, "h264", 10},
#endif
        {VAProfileHEVCMain, "hevc", 8}, {VAProfileHEVCMain10, "hevc", 10},
        {VAProfileAV1Profile0, "av1", 8}, {VAProfileAV1Profile0, "av1", 10},
    };
    Modes modes;
    for (const auto &[profile, codec, depth] : profiles) {
        for (auto entry : {VAEntrypointEncSlice, VAEntrypointEncSliceLP}) {
            VAConfigAttrib attribute = {VAConfigAttribRTFormat, VA_ATTRIB_NOT_SUPPORTED};
            auto format = depth == 10 ? VA_RT_FORMAT_YUV420_10 : VA_RT_FORMAT_YUV420;
            if (vaGetConfigAttributes(display, profile, entry, &attribute, 1) == VA_STATUS_SUCCESS &&
                    attribute.value != VA_ATTRIB_NOT_SUPPORTED && (attribute.value & format))
                modes.emplace(codec, depth, "");
        }
    }
    return modes;
}
#endif

Modes qsv_modes(const std::string &adapter) {
#ifdef _WIN32
    unsigned index = std::stoul(adapter);
    DXGI_ADAPTER_DESC device = {};
    check_status("IDXGIAdapter::GetDesc", dxgi_adapter(index)->GetDesc(&device));
#else
    unsigned index = 0;
    if (std::sscanf(adapter.c_str(), "/dev/dri/renderD%u", &index) != 1)
        throw std::runtime_error("Expected a DRM render node: " + adapter);
#endif
    mfxLoader loader = MFXLoad();
    if (!loader)
        throw std::runtime_error("MFXLoad did not create a oneVPL loader");
    std::unique_ptr<std::remove_pointer_t<mfxLoader>, decltype(&MFXUnload)> owner(loader, MFXUnload);
    Modes modes;
    for (mfxU32 i = 0;; ++i) {
        mfxHDL capabilities = nullptr;
        auto status = MFXEnumImplementations(loader, i, MFX_IMPLCAPS_IMPLDESCSTRUCTURE, &capabilities);
        if (status == MFX_ERR_NOT_FOUND)
            break;
        check_status("MFXEnumImplementations", status);
        auto release = [loader](void *value) { MFXDispReleaseImplDescription(loader, value); };
        std::unique_ptr<void, decltype(release)> capability_owner(capabilities, release);
        auto *impl = static_cast<mfxImplDescription *>(capabilities);
        auto acceleration =
#ifdef _WIN32
            MFX_ACCEL_MODE_VIA_D3D11;
#else
            MFX_ACCEL_MODE_VIA_VAAPI;
#endif
        if (impl->Impl != MFX_IMPL_TYPE_HARDWARE || impl->AccelerationMode != acceleration || impl->VendorID != 0x8086)
            continue;
        bool matched = false;
#if MFX_VERSION >= 2010
        mfxHDL identifier = nullptr;
        if (MFXEnumImplementations(loader, i, MFX_IMPLCAPS_DEVICE_ID_EXTENDED, &identifier) == MFX_ERR_NONE) {
            std::unique_ptr<void, decltype(release)> identifier_owner(identifier, release);
            auto *id = static_cast<mfxExtendedDeviceId *>(identifier);
#ifdef _WIN32
            if (id->LUIDValid) {
                if (std::memcmp(id->DeviceLUID, &device.AdapterLuid, sizeof(LUID)) != 0)
                    continue;
                matched = true;
            }
#else
            matched = id->DRMRenderNodeNum == index;
#endif
        }
#endif
#ifdef _WIN32
        if (!matched) {
            // Legacy implementations identify the adapter as hexadecimal PCI ID / DXGI index.
            unsigned pci_id = 0, adapter_index = 0;
            matched = std::sscanf(impl->Dev.DeviceID, "%x/%u", &pci_id, &adapter_index) == 2 &&
                      pci_id == device.DeviceId && adapter_index == index;
        }
#endif
        if (!matched)
            continue;
        std::cerr << "oneVPL " << impl->ApiVersion.Major << '.' << impl->ApiVersion.Minor
                  << " " << impl->ImplName << '\n';
        for (mfxU16 codec_index = 0; codec_index < impl->Enc.NumCodecs; ++codec_index) {
            const auto &entry = impl->Enc.Codecs[codec_index];
            const char *codec = nullptr;
            switch (entry.CodecID) {
                case MFX_CODEC_AVC: codec = "h264"; break;
                case MFX_CODEC_HEVC: codec = "hevc"; break;
                case MFX_CODEC_AV1: codec = "av1"; break;
                default: continue;
            }
            for (mfxU16 p = 0; p < entry.NumProfiles; ++p) {
                const auto &profile = entry.Profiles[p];
                const bool hevc = entry.CodecID == MFX_CODEC_HEVC;
                const bool avc = entry.CodecID == MFX_CODEC_AVC;
                const bool eight_bit = !hevc || profile.Profile == MFX_PROFILE_HEVC_MAIN;
                const bool ten_bit = (!hevc || profile.Profile == MFX_PROFILE_HEVC_MAIN10) &&
                                     (!avc || (profile.Profile & 0xff) == MFX_PROFILE_AVC_HIGH10);
                for (mfxU16 m = 0; m < profile.NumMemTypes; ++m) {
                    const auto &memory = profile.MemDesc[m];
                    for (mfxU16 f = 0; f < memory.NumColorFormats; ++f) {
                        if (eight_bit && memory.ColorFormats[f] == MFX_FOURCC_NV12)
                            modes.emplace(codec, 8, "");
                        if (ten_bit && memory.ColorFormats[f] == MFX_FOURCC_P010)
                            modes.emplace(codec, 10, "");
                    }
                }
            }
        }
    }
#ifndef _WIN32
    if (modes.empty()) {
        std::cerr << "oneVPL did not report modes for " << adapter << "; querying its Intel VA-API driver\n";
        return intel_vaapi_modes(adapter);
    }
#endif
    return modes;
}
#endif

#ifdef BLURAY_GPU_AMF
Modes amf_modes(const std::string &adapter) {
#ifdef _WIN32
    auto device = d3d11_device(std::stoul(adapter));
#else
    (void)adapter;
#endif
    Library library(AMF_DLL_NAMEA);
    auto init_amf = library.get<AMFInit_Fn>(AMF_INIT_FUNCTION_NAME);
    auto query_version = library.get<AMFQueryVersion_Fn>(AMF_QUERY_VERSION_FUNCTION_NAME);
    amf_uint64 driver_version = 0;
    check_status("AMFQueryVersion", query_version(&driver_version));
    std::cerr << "AMF " << (driver_version >> 48) << '.' << ((driver_version >> 32) & 0xffff)
              << '.' << ((driver_version >> 16) & 0xffff) << '.' << (driver_version & 0xffff) << '\n';
    amf::AMFFactory *factory = nullptr;
    check_status("AMFInit", init_amf(AMF_FULL_VERSION, &factory));
    amf::AMFContextPtr context;
    check_status("AMFFactory::CreateContext", factory->CreateContext(&context));
#ifdef _WIN32
    check_status("AMFContext::InitDX11", context->InitDX11(device.get()));
#else
    amf::AMFContext1Ptr vulkan(context);
    if (!vulkan)
        throw std::runtime_error("AMFContext1 is unavailable");
    check_status("AMFContext1::InitVulkan", vulkan->InitVulkan(nullptr));
#endif
    const std::pair<const wchar_t *, const char *> codecs[] = {
        {AMFVideoEncoderVCE_AVC, "h264"}, {AMFVideoEncoder_HEVC, "hevc"}, {AMFVideoEncoder_AV1, "av1"},
    };
    Modes modes;
    for (const auto &[component_id, codec] : codecs) {
        amf::AMFComponentPtr component;
        auto status = factory->CreateComponent(context, component_id, &component);
        if (status != AMF_OK) {
            std::cerr << "AMF CreateComponent " << codec << ": " << status << '\n';
            continue;
        }
        amf::AMFCapsPtr caps;
        amf::AMFIOCapsPtr inputs;
        status = component->GetCaps(&caps);
        if (status != AMF_OK || !caps) {
            std::cerr << "AMF GetCaps " << codec << ": " << status << '\n';
            continue;
        }
        auto acceleration = caps->GetAccelerationType();
        status = caps->GetInputCaps(&inputs);
        if (acceleration != amf::AMF_ACCEL_HARDWARE || status != AMF_OK || !inputs) {
            std::cerr << "AMF GetInputCaps " << codec << ": " << status << ", acceleration " << acceleration << '\n';
            continue;
        }
        for (amf_int32 i = 0; i < inputs->GetNumOfFormats(); ++i) {
            amf::AMF_SURFACE_FORMAT format;
            amf_bool native;
            if (inputs->GetFormatAt(i, &format, &native) != AMF_OK || !native)
                continue;
            if (format == amf::AMF_SURFACE_NV12)
                modes.emplace(codec, 8, "");
            if (format == amf::AMF_SURFACE_P010)
                modes.emplace(codec, 10, "");
        }
    }
    context->Terminate();
    return modes;
}
#endif

#ifdef BLURAY_GPU_MF
Modes mf_modes() {
    // Media Foundation is optional on Windows N and Windows Server.
    Library media_foundation("mfplat.dll");
    auto startup = media_foundation.get<decltype(&MFStartup)>("MFStartup");
    auto shutdown = media_foundation.get<decltype(&MFShutdown)>("MFShutdown");
    auto enumerate = media_foundation.get<decltype(&MFTEnumEx)>("MFTEnumEx");
    check_status("MFStartup", startup(MF_VERSION, MFSTARTUP_LITE));
    const std::pair<GUID, const char *> codecs[] = {
        {MFVideoFormat_H264, "h264"}, {MFVideoFormat_HEVC, "hevc"}, {MFVideoFormat_AV1, "av1"},
    };
    Modes modes;
    for (const auto &[format, codec] : codecs) {
        MFT_REGISTER_TYPE_INFO input = {MFMediaType_Video, MFVideoFormat_NV12};
        MFT_REGISTER_TYPE_INFO output = {MFMediaType_Video, format};
        IMFActivate **encoders = nullptr;
        UINT32 count = 0;
        HRESULT status = enumerate(MFT_CATEGORY_VIDEO_ENCODER, MFT_ENUM_FLAG_HARDWARE,
                                   &input, &output, &encoders, &count);
        if (SUCCEEDED(status) && count)
            modes.emplace(codec, 8, "");
        for (UINT32 i = 0; i < count; ++i)
            encoders[i]->Release();
        CoTaskMemFree(encoders);
    }
    shutdown();
    return modes;
}
#endif

#ifdef __APPLE__
constexpr CMVideoCodecType fourcc(char a, char b, char c, char d) {
    return (CMVideoCodecType(a) << 24) | (CMVideoCodecType(b) << 16) | (CMVideoCodecType(c) << 8) | d;
}

using EncoderProperties = std::unique_ptr<std::remove_pointer_t<CFDictionaryRef>, decltype(&CFRelease)>;

EncoderProperties videotoolbox_properties(CMVideoCodecType codec, const char *name) {
    const void *keys[] = {kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder};
    const void *values[] = {kCFBooleanTrue};
    auto specification = CFDictionaryCreate(nullptr, keys, values, 1,
                                            &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionaryRef properties = nullptr;
    OSStatus status = VTCopySupportedPropertyDictionaryForEncoder(320, 192, codec, specification, nullptr, &properties);
    CFRelease(specification);
    EncoderProperties owner(properties, CFRelease);
    std::cerr << "VideoToolbox " << name << ": " << status << '\n';
    if (status != noErr)
        owner.reset();
    return owner;
}

Modes videotoolbox_modes() {
    Modes modes;
    if (videotoolbox_properties(kCMVideoCodecType_H264, "H.264"))
        modes.emplace("h264", 8, "");
    if (auto properties = videotoolbox_properties(kCMVideoCodecType_HEVC, "HEVC")) {
        modes.emplace("hevc", 8, "");
        auto profile_info = static_cast<CFDictionaryRef>(
            CFDictionaryGetValue(properties.get(), kVTCompressionPropertyKey_ProfileLevel));
        auto profiles = profile_info ? static_cast<CFArrayRef>(
            CFDictionaryGetValue(profile_info, kVTPropertySupportedValueListKey)) : nullptr;
        if (profiles && CFArrayContainsValue(profiles, CFRangeMake(0, CFArrayGetCount(profiles)),
                                            kVTProfileLevel_HEVC_Main10_AutoLevel))
            modes.emplace("hevc", 10, "");
    }
    struct ProResProfile { CMVideoCodecType codec; int depth; const char *profile; };
    const ProResProfile profiles[] = {
        {fourcc('a', 'p', 'c', 'o'), 10, "proxy"}, {fourcc('a', 'p', 'c', 's'), 10, "lt"},
        {fourcc('a', 'p', 'c', 'n'), 10, "standard"}, {fourcc('a', 'p', 'c', 'h'), 10, "hq"},
        {fourcc('a', 'p', '4', 'h'), 12, "4444"}, {fourcc('a', 'p', '4', 'x'), 12, "xq"},
    };
    for (const auto &[codec, depth, profile] : profiles) {
        if (videotoolbox_properties(codec, profile))
            modes.emplace("prores", depth, profile);
    }
    return modes;
}
#endif
} // namespace

int main(int argc, char **argv) {
    if (argc == 2 && std::string(argv[1]) == "--version") {
        std::cout << "2\n";
        return 0;
    }
    try {
        if (argc == 2 && std::string(argv[1]) == "--list-vulkan") {
            list_vulkan_devices();
            return 0;
        }
        if (argc != 3) {
            std::cerr << "Usage: bluraysub-gpu-capabilities BACKEND ADAPTER | --list-vulkan\n";
            return 2;
        }
        const std::string backend = argv[1];
        const std::string adapter = argv[2];
        Modes modes;
#ifdef BLURAY_GPU_NVENC
        if (backend == "nvenc") modes = nvenc_modes(std::stoul(adapter));
        else
#endif
#ifdef BLURAY_GPU_QSV
        if (backend == "qsv") modes = qsv_modes(adapter);
        else
#endif
#ifdef BLURAY_GPU_AMF
        if (backend == "amf") modes = amf_modes(adapter);
        else
#endif
#ifdef BLURAY_GPU_MF
        if (backend == "mf") modes = mf_modes();
        else
#endif
#ifdef __APPLE__
        if (backend == "videotoolbox") modes = videotoolbox_modes();
        else
#endif
            throw std::runtime_error("Configured probe does not provide " + backend);

        for (const auto &[codec, depth, profile] : modes) {
            std::cout << codec << ' ' << depth;
            if (!profile.empty())
                std::cout << ' ' << profile;
            std::cout << '\n';
        }
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
