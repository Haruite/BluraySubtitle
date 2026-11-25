"""FFmpeg hardware encoder discovery and arguments shared by probing and Encode."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from src.core.i18n import translate_text
from src.core.settings import FFMPEG_PATH
from src.core.video_format import CHROMA_FORMATS, planar_yuv_format, yuv_format_matches
from src.exports.utils import run_command
from src.runtime import TaskCancelled


GPU_CODECS = {'hevc': 'H.265', 'h264': 'H.264', 'av1': 'AV1', 'prores': 'ProRes', 'ffv1': 'FFV1'}
GPU_MUXERS = {'hevc': 'hevc', 'h264': 'h264', 'av1': 'ivf', 'prores': 'matroska', 'ffv1': 'matroska'}
GPU_BACKENDS = {
    'nvenc': 'NVENC', 'qsv': 'Quick Sync', 'amf': 'AMF',
    'videotoolbox': 'VideoToolbox', 'mf': 'Media Foundation', 'vulkan': 'Vulkan',
}
_FFV1_DEPTHS = ('8', '10', '12')
_VENDOR_BACKENDS = {0x10DE: 'nvenc', 0x8086: 'qsv', 0x1002: 'amf'}
_PRORES_PROFILES = {
    'standard': ('10', 'ProRes 422'), 'hq': ('10', 'ProRes 422 HQ'),
    'lt': ('10', 'ProRes 422 LT'), 'proxy': ('10', 'ProRes 422 Proxy'),
    '4444': ('12', 'ProRes 4444'), 'xq': ('12', 'ProRes 4444 XQ'),
}


@dataclass(frozen=True)
class GpuEncodeDevice:
    key: str
    name: str
    backend: str
    interface: str = ''
    adapter: str = ''
    formats: tuple[tuple[str, str], ...] = ()
    supported_presets: tuple[tuple[str, str, str], ...] = ()
    static_hdr_input_options: frozenset[str] = frozenset()
    hardware_id: str = ''
    vulkan_adapter: str | None = None
    cuda_adapter: str | None = None


@dataclass(frozen=True)
class VideoEncodeChoice:
    encoder: str
    bit_depth: str
    parameters: str
    device: GpuEncodeDevice | None = None
    chroma_format: str = 'yuv420'

    @property
    def output_chroma_format(self) -> str:
        if self.encoder == 'prores':
            return 'yuv444' if self.bit_depth == '12' else 'yuv422'
        return self.chroma_format


def gpu_detection_supported() -> bool:
    return sys.platform in ('win32', 'darwin') or sys.platform.startswith('linux')


def _windows_arm64() -> bool:
    if sys.platform != 'win32':
        return False
    # IsWow64Process2 also identifies the host when Python itself is emulated.
    query = getattr(ctypes.windll.kernel32, 'IsWow64Process2', None)
    process_machine = ctypes.c_ushort()
    native_machine = ctypes.c_ushort()
    if query and query(ctypes.c_void_p(-1), ctypes.byref(process_machine), ctypes.byref(native_machine)):
        return native_machine.value == 0xaa64
    return platform.machine().lower() in ('arm64', 'aarch64')


def gpu_device_label(device: GpuEncodeDevice) -> str:
    backend = GPU_BACKENDS[device.backend]
    formats = {codec for codec, _ in device.formats}
    if formats == {'ffv1'}:
        backend = GPU_BACKENDS['vulkan']
    elif 'ffv1' in formats:
        backend += ' / ' + GPU_BACKENDS['vulkan']
    name = device.name if device.name == backend else f'{device.name} ({backend})'
    return f'GPU · {name}'


def _windows_information(relationship: int) -> bytes:
    size = ctypes.c_ulong()
    query = ctypes.windll.kernel32.GetLogicalProcessorInformationEx
    query(relationship, None, ctypes.byref(size))
    if not size.value:
        return b''
    buffer = ctypes.create_string_buffer(size.value)
    return buffer.raw[:size.value] if query(relationship, buffer, ctypes.byref(size)) else b''


def cpu_package_count() -> int:
    if sys.platform == 'win32':
        records = _windows_information(3)  # RelationProcessorPackage
        count = offset = 0
        while offset + 8 <= len(records):
            size = int.from_bytes(records[offset + 4:offset + 8], 'little')
            if size < 8:
                break
            count += 1
            offset += size
        return max(1, count)
    if sys.platform.startswith('linux'):
        packages = set()
        for cpu in os.sched_getaffinity(0):
            try:
                packages.add(Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id').read_text().strip())
            except OSError:
                continue
        return max(1, len(packages))
    if sys.platform == 'darwin':
        try:
            result = run_command(['/usr/sbin/sysctl', '-n', 'hw.packages'], capture_output=True, check=True, timeout=2)
            return max(1, int(result.stdout))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return 1


@lru_cache(maxsize=1)
def cpu_device_name() -> str:
    """Name the CPU group without counting logical processors as packages."""
    names = []
    if sys.platform == 'win32':
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor') as processors:
                for index in range(winreg.QueryInfoKey(processors)[0]):
                    try:
                        with winreg.OpenKey(processors, winreg.EnumKey(processors, index)) as processor:
                            names.append(winreg.QueryValueEx(processor, 'ProcessorNameString')[0])
                    except OSError:
                        continue
        except OSError:
            pass
    elif sys.platform.startswith('linux'):
        try:
            models = {}
            for line in Path('/proc/cpuinfo').read_text(encoding='utf-8', errors='replace').splitlines():
                key, _, value = line.partition(':')
                if key.strip() in ('model name', 'Hardware'):
                    models.setdefault(key.strip(), []).append(value)
            names = models.get('model name') or models.get('Hardware') or []
            if not names:
                names = [Path('/sys/devices/soc0/machine').read_text(encoding='utf-8', errors='replace').strip()]
        except OSError:
            pass
    else:
        try:
            system_name = '/usr/sbin/sysctl' if sys.platform == 'darwin' else '/sbin/sysctl'
            key = 'machdep.cpu.brand_string' if sys.platform == 'darwin' else 'hw.model'
            result = run_command([system_name, '-n', key], capture_output=True, text=True, check=True, timeout=2)
            names.append(result.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    models = list(dict.fromkeys(' '.join(name.split()) for name in names if isinstance(name, str) and name.strip()))
    if not models and platform.processor():
        models.append(platform.processor())
    packages = cpu_package_count()
    count = 'CPU' if packages == 1 else f'{packages}×CPU'
    return f'{count} · {" + ".join(models)}' if models else count


def _windows_cuda_adapters() -> dict[str, str]:
    """Match CUDA ordinals to DXGI adapter LUIDs, including mixed-vendor systems."""
    try:
        cuda = ctypes.WinDLL('nvcuda.dll')
        if cuda.cuInit(0):
            return {}
        get_luid = cuda.cuDeviceGetLuid
        count = ctypes.c_int()
        if cuda.cuDeviceGetCount(ctypes.byref(count)):
            return {}
        adapters = {}
        for index in range(count.value):
            device = ctypes.c_int()
            luid = ctypes.create_string_buffer(8)
            mask = ctypes.c_uint()
            if not cuda.cuDeviceGet(ctypes.byref(device), index) and not get_luid(luid, ctypes.byref(mask), device):
                adapters['luid:' + luid.raw.hex()] = str(index)
        return adapters
    except (AttributeError, OSError):
        return {}


def _windows_adapters(report: Callable[[str], None]) -> list[GpuEncodeDevice]:
    class Luid(ctypes.Structure):
        _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_int32)]

    class AdapterDescription(ctypes.Structure):
        _fields_ = [
            ('name', ctypes.c_wchar * 128), ('vendor', ctypes.c_uint32),
            ('device', ctypes.c_uint32), ('subsystem', ctypes.c_uint32), ('revision', ctypes.c_uint32),
            ('video_memory', ctypes.c_size_t), ('system_memory', ctypes.c_size_t),
            ('shared_memory', ctypes.c_size_t), ('luid', Luid),
        ]

    class AdapterName(ctypes.Structure):
        _fields_ = [
            ('request', ctypes.c_uint32), ('size', ctypes.c_uint32), ('luid', Luid),
            ('target', ctypes.c_uint32), ('path', ctypes.c_wchar * 128),
        ]

    def method(instance, index, result, *parameters):
        table = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *parameters)(table[index])

    factory = ctypes.c_void_p()
    uuid = (ctypes.c_ubyte * 16).from_buffer_copy(UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    result = ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(uuid), ctypes.byref(factory))
    if result != 0:
        report(f'CreateDXGIFactory1: HRESULT 0x{result & 0xffffffff:08x}')
        return []
    found = []
    cuda_adapters = None
    try:
        enumerate_adapter = method(factory, 7, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
        # Use EnumAdapters order, the same indices FFmpeg uses for D3D11 devices.
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            if enumerate_adapter(factory, index, ctypes.byref(adapter)) != 0:
                break
            try:
                description = AdapterDescription()
                result = method(adapter, 8, ctypes.c_long, ctypes.POINTER(AdapterDescription))(
                    adapter, ctypes.byref(description),
                )
                if result != 0:
                    report(f'DXGI[{index}].GetDesc: HRESULT 0x{result & 0xffffffff:08x}')
                    continue
                report(f'DXGI[{index}]: {description.name} [{description.vendor:04x}:{description.device:04x}]')
                backend = _VENDOR_BACKENDS.get(description.vendor)
                if not backend:
                    continue
                if backend == 'nvenc' and cuda_adapters is None:
                    cuda_adapters = _windows_cuda_adapters()
                hardware_id = 'luid:' + bytes(description.luid).hex()
                identity = AdapterName(4, ctypes.sizeof(AdapterName), description.luid, 0)
                result = ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(identity))
                key = identity.path.casefold() if result == 0 and identity.path else (
                    f'{description.vendor:04x}:{description.device:04x}:{description.subsystem:08x}:{index}'
                )
                found.append(GpuEncodeDevice(
                    f'windows:{key}', description.name, backend, 'd3d11va', str(index),
                    hardware_id=hardware_id, cuda_adapter=(cuda_adapters or {}).get(hardware_id),
                ))
            finally:
                method(adapter, 2, ctypes.c_ulong)(adapter)
                index += 1
    finally:
        method(factory, 2, ctypes.c_ulong)(factory)
    return found


def _linux_adapters(backends: set[str], report: Callable[[str], None]) -> list[GpuEncodeDevice]:
    found = []
    if 'nvenc' in backends:
        try:
            cuda = ctypes.CDLL('libcuda.so.1')
            count = ctypes.c_int()
            init_result = cuda.cuInit(0)
            count_result = cuda.cuDeviceGetCount(ctypes.byref(count)) if init_result == 0 else None
            report(f'cuInit: {init_result}, cuDeviceGetCount: {count_result}, count: {count.value}')
            if init_result == 0 and count_result == 0:
                uuid_query = getattr(cuda, 'cuDeviceGetUuid', None) or getattr(cuda, 'cuDeviceGetUuid_v2', None)
                for index in range(count.value):
                    adapter = ctypes.c_int()
                    uuid = ctypes.create_string_buffer(16)
                    name = ctypes.create_string_buffer(256)
                    result = cuda.cuDeviceGet(ctypes.byref(adapter), index)
                    if result != 0:
                        report(f'cuDeviceGet[{index}]: {result}')
                        continue
                    identity = UUID(bytes=uuid.raw) if (
                        uuid_query is not None and uuid_query(ctypes.byref(uuid), adapter) == 0
                    ) else None
                    result = cuda.cuDeviceGetName(name, len(name), adapter)
                    device_name = name.value.decode(errors='replace') if result == 0 else f'CUDA {index}'
                    key = str(identity) if identity is not None else f'index:{index}'
                    report(f'CUDA[{index}]: {device_name}, {key}')
                    found.append(GpuEncodeDevice(
                        f'cuda:{key}', device_name, 'nvenc', 'cuda', str(index),
                        hardware_id='uuid:' + identity.hex if identity is not None else '',
                    ))
        except (OSError, AttributeError) as error:
            report(f'CUDA: {error}')
    amd = []
    for node in sorted(Path('/sys/class/drm').glob('renderD*')):
        try:
            device = (node / 'device').resolve(strict=True)
            vendor = int((device / 'vendor').read_text(), 16)
            product = int((device / 'device').read_text(), 16)
        except (OSError, ValueError) as error:
            report(f'{node}: {error}')
            continue
        report(f'{node.name}: {device.name} [{vendor:04x}:{product:04x}]')
        if vendor not in (0x8086, 0x1002):
            continue
        backend = _VENDOR_BACKENDS[vendor]
        brand = 'Intel' if backend == 'qsv' else 'AMD'
        name = f'{brand} {vendor:04x}:{product:04x} ({device.name})'
        try:
            result = run_command(['lspci', '-s', device.name], capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and ': ' in result.stdout:
                name = result.stdout.rstrip().split(': ', 1)[1]
        except (OSError, subprocess.SubprocessError):
            pass
        hardware_id = 'render:' + node.name.removeprefix('renderD')
        if backend == 'qsv':
            found.append(GpuEncodeDevice(
                f'drm:{device.name}', name, backend, 'vaapi', f'/dev/dri/{node.name}', hardware_id=hardware_id,
            ))
        else:
            amd.append(GpuEncodeDevice(f'drm:{device.name}', name, backend, hardware_id=hardware_id))
    # The FFmpeg AMF interface on Linux uses the driver's default Vulkan device.
    if len(amd) == 1:
        found.extend(amd)
    elif amd:
        report(translate_text('AMF uses the driver-selected adapter on Linux. Found {count} AMD adapters.').format(
            count=len(amd),
        ))
    return found


def _parse_vulkan_adapters(output: bytes, *, nvidia_only: bool) -> list[tuple[GpuEncodeDevice, tuple[str, ...]]]:
    found = []
    seen: set[str] = set()
    for line in output.decode('utf-8', errors='replace').splitlines():
        fields = line.split('\t', 4)
        if len(fields) != 5:
            continue
        vendor, raw_uuid, hardware_id, depths, name = fields
        if (nvidia_only and vendor != '10de') or hardware_id in seen:
            continue
        identity = UUID(hex=raw_uuid)
        valid_depths = tuple(depth for depth in depths.split(',') if depth in _FFV1_DEPTHS)
        if identity.int and valid_depths:
            seen.add(hardware_id)
            found.append((GpuEncodeDevice(
                f'vulkan:{identity}', name, 'vulkan', hardware_id=hardware_id, vulkan_adapter=str(identity),
            ), valid_depths))
    return found


def _merge_vulkan_adapters(
        vendor_devices: list[GpuEncodeDevice], vulkan_devices: list[GpuEncodeDevice],
) -> list[GpuEncodeDevice]:
    vulkan_by_hardware = {device.hardware_id: device for device in vulkan_devices}
    combined = []
    for device in vendor_devices:
        match = vulkan_by_hardware.pop(device.hardware_id, None)
        combined.append(replace(device, vulkan_adapter=match.vulkan_adapter) if match else device)
    combined.extend(vulkan_by_hardware.values())
    return combined


def _preset_parameters(device: GpuEncodeDevice, codec: str, depth: str) -> dict[str, str]:
    if codec == 'ffv1':
        return {
            'Fast': '-coder rice -context 0 -slices 16',
            'Balanced': '-coder range_tab -context 0 -slices 16',
        }
    if codec == 'prores':
        return {name: f'-profile:v {profile}' for profile, (bits, name) in _PRORES_PROFILES.items() if bits == depth}
    if device.backend == 'nvenc':
        return {
            'Fast': '-preset p3 -rc vbr -cq 28 -b:v 0',
            'Balanced': '-preset p5 -rc vbr -cq 23 -b:v 0',
            'High Quality': '-preset p7 -rc vbr -cq 19 -b:v 0',
        }
    if device.backend == 'qsv':
        return {
            'Fast': '-preset fast -global_quality 28',
            'Balanced': '-preset medium -global_quality 23',
            'High Quality': '-preset slow -global_quality 19',
        }
    if device.backend == 'amf':
        if codec == 'av1':
            return {
                'Fast': '-quality speed -rc cqp -qp_i 104 -qp_p 112',
                'Balanced': '-quality balanced -rc cqp -qp_i 84 -qp_p 92',
                'High Quality': '-quality quality -rc cqp -qp_i 68 -qp_p 76',
            }
        return {
            'Fast': '-quality speed -rc cqp -qp_i 26 -qp_p 28',
            'Balanced': '-quality balanced -rc cqp -qp_i 21 -qp_p 23',
            'High Quality': '-quality quality -rc cqp -qp_i 17 -qp_p 19',
        }
    if device.backend == 'mf':
        return {
            'Fast': '-rate_control quality -quality 40',
            'Balanced': '-rate_control quality -quality 60',
            'High Quality': '-rate_control quality -quality 80',
        }
    if platform.machine().lower() in ('arm64', 'aarch64'):
        return {'Fast': '-q:v 45', 'Balanced': '-q:v 60', 'High Quality': '-q:v 75'}
    return {'Fast': '-b:v 5M', 'Balanced': '-b:v 10M', 'High Quality': '-b:v 20M'}


def gpu_presets(device: GpuEncodeDevice, codec: str, depth: str, *, available_only: bool = True) -> dict[str, str]:
    return {
        name: parameters for name, parameters in _preset_parameters(device, codec, depth).items()
        if not available_only or (codec, depth, name) in device.supported_presets
    }


_HARDWARE_PARAMETERS = frozenset({
    '-preset', '-tune', '-rc', '-cq', '-qp', '-quality', '-q:v', '-global_quality',
    '-b:v', '-maxrate', '-bufsize', '-g', '-bf', '-refs', '-b_ref_mode', '-multipass',
    '-rc-lookahead', '-spatial-aq', '-temporal-aq', '-aq-strength', '-weighted_pred',
    '-look_ahead', '-look_ahead_depth', '-low_power', '-qvbr_quality_level',
    '-qp_i', '-qp_p', '-qp_b', '-prio_speed', '-constant_bit_rate',
    '-level', '-tier', '-usage', '-async_depth', '-mbbrc', '-extbrc', '-forced-idr',
    '-strict_gop', '-preanalysis', '-vbaq', '-coder', '-realtime', '-allow_frame_reordering',
    '-rate_control', '-scenario', '-profile:v', '-context', '-slices', '-slices_h', '-slices_v', '-slicecrc',
})


def hardware_encoder_parameters(text: str) -> list[str]:
    try:
        arguments = shlex.split(text)
    except ValueError as error:
        raise ValueError(translate_text('Invalid hardware encoder parameters: {detail}').format(detail=error)) from error
    for index in range(0, len(arguments), 2):
        option = arguments[index]
        value = arguments[index + 1] if index + 1 < len(arguments) else ''
        if (option not in _HARDWARE_PARAMETERS or not value
                or (value.startswith('-') and not re.fullmatch(r'-\d+(?:\.\d+)?', value))):
            raise ValueError(translate_text('Unsupported hardware encoder option or missing value: {option}').format(
                option=option,
            ))
    return arguments


def gpu_chroma_candidates(choice: VideoEncodeChoice) -> tuple[str, ...]:
    device = choice.device
    assert device is not None
    if choice.encoder == 'prores':
        return (choice.output_chroma_format,)
    if (
            choice.encoder == 'ffv1'
            or (device.backend == 'qsv' and choice.encoder == 'hevc')
            or (
                device.backend == 'nvenc' and choice.encoder in ('h264', 'hevc')
                and (device.interface == 'cuda' or device.cuda_adapter is not None)
            )
    ):
        return CHROMA_FORMATS
    return ('yuv420',)


def hardware_encode_command(
        ffmpeg: str, choice: VideoEncodeChoice, source_args: list[str], output_args: list[str], *,
        metadata_args: tuple[str, ...] = (),
) -> list[str]:
    device = choice.device
    assert device is not None
    initial = [ffmpeg, '-hide_banner', '-nostdin', '-n']
    backend = 'vulkan' if choice.encoder == 'ffv1' else device.backend
    chroma_format = choice.output_chroma_format
    if chroma_format not in gpu_chroma_candidates(choice):
        raise ValueError(translate_text('Unsupported chroma sampling: {chroma}').format(chroma=chroma_format))
    ten_bit = choice.bit_depth == '10'
    pixel_format = 'p010le' if ten_bit else 'nv12'
    if choice.encoder == 'ffv1':
        pixel_format = planar_yuv_format(chroma_format, choice.bit_depth)
    elif choice.encoder == 'prores':
        pixel_format = 'ayuv64le' if choice.bit_depth == '12' else 'p210le'
    elif chroma_format != 'yuv420':
        if backend == 'qsv':
            pixel_format = (
                ('y210le' if ten_bit else 'yuyv422') if chroma_format == 'yuv422'
                else ('xv30le' if ten_bit else 'vuyx')
            )
        elif chroma_format == 'yuv422':
            pixel_format = 'p210le' if ten_bit else 'nv16'
        else:
            # NVENC reads the most significant ten bits of this input format.
            pixel_format = 'yuv444p16le' if ten_bit else 'yuv444p'
    filters = [f'format={pixel_format}']
    encoder_options = []
    colour_options = {
        '--range': ('range', {'limited': 'limited', 'full': 'full'}),
        '--colorprim': ('color_primaries', {}),
        '--transfer': ('color_trc', {}),
        '--colormatrix': ('colorspace', {}),
    }
    input_metadata = []
    colour_values = []
    for option, value in zip(metadata_args[::2], metadata_args[1::2]):
        if option in ('--master-display', '--max-cll') and choice.encoder != 'h264':
            flag = '-mastering_display' if option == '--master-display' else '-content_light'
            if flag in device.static_hdr_input_options:
                input_metadata.extend((flag, value))
        elif option in colour_options:
            name, aliases = colour_options[option]
            colour_values.append(f'{name}={aliases.get(value, value)}')
        elif option == '--chromaloc' and chroma_format == 'yuv420':
            if choice.encoder == 'av1':
                position = {'0': 'vertical', '2': 'colocated'}.get(value)
                if position:
                    encoder_options.extend(('-bsf:v', f'av1_metadata=chroma_sample_position={position}'))
            elif choice.encoder in ('h264', 'hevc', 'ffv1'):
                locations = ('left', 'center', 'topleft', 'top', 'bottomleft', 'bottom')
                encoder_options.extend(('-chroma_sample_location', locations[int(value)]))
                # Some hardware encoders ignore the codec option when writing the bitstream.
                if choice.encoder != 'ffv1':
                    encoder_options.extend(('-bsf:v', f'{choice.encoder}_metadata=chroma_sample_loc_type={value}'))
    if colour_values:
        filters.append('setparams=' + ':'.join(colour_values))
    if backend == 'vulkan':
        assert device.vulkan_adapter is not None
        initial.extend(('-init_hw_device', f'vulkan=encode:{device.vulkan_adapter}', '-filter_hw_device', 'encode'))
        filters.append('hwupload')
        # Version 4 supports subsampled frames with dimensions not aligned to the slice grid.
        encoder_options.extend(('-level', '4', '-strict', 'experimental'))
    elif backend == 'nvenc' and chroma_format != 'yuv420' and device.cuda_adapter is not None:
        # D3D11 uploads use packed 4:2:2 and 4:4:4 surfaces that NVENC cannot register.
        encoder_options.extend(('-gpu', device.cuda_adapter))
    elif device.interface in ('d3d11va', 'vaapi'):
        initial.extend(('-init_hw_device', f'{device.interface}=adapter:{device.adapter}'))
        frame_device = 'adapter'
        if device.backend == 'qsv':
            initial.extend(('-init_hw_device', 'qsv=encode@adapter'))
            frame_device = 'encode'
        initial.extend(('-filter_hw_device', frame_device))
        # Let QSV accept system-memory frames on D3D11: explicit upload pools can
        # fail to create textures even when the selected device supports encoding.
        if device.backend != 'qsv' or device.interface != 'd3d11va':
            filters.append('hwupload=extra_hw_frames=32' if device.backend == 'qsv' else 'hwupload')
    elif device.interface == 'cuda':
        encoder_options.extend(('-gpu', device.adapter))
    elif device.backend == 'videotoolbox':
        encoder_options.extend(('-allow_sw', '0'))
    elif device.backend == 'mf':
        encoder_options.extend(('-hw_encoding', '1'))
    if choice.encoder == 'hevc' and device.backend != 'mf':
        profile = ('main10' if ten_bit else 'main') if chroma_format == 'yuv420' else 'rext'
        encoder_options.extend(('-profile:v', profile))
    elif choice.encoder == 'h264' and backend == 'nvenc' and chroma_format != 'yuv420':
        encoder_options.extend(('-profile:v', 'high422' if chroma_format == 'yuv422' else 'high444p'))
    parameters = hardware_encoder_parameters(choice.parameters)
    if choice.encoder == 'prores' and '-profile:v' not in parameters:
        supported = gpu_presets(device, choice.encoder, choice.bit_depth)
        parameters.extend(hardware_encoder_parameters(next(iter(supported.values()), '')))
    return [
        *initial, *input_metadata, *source_args, '-map', '0:v:0', '-an',
        '-vf', ','.join(filters), '-c:v', f'{choice.encoder}_{backend}',
        *encoder_options, *parameters,
        '-fps_mode', 'passthrough', *output_args,
    ]


def _parse_driver_modes(output: bytes) -> dict[tuple[str, str], set[str]]:
    modes: dict[tuple[str, str], set[str]] = {}
    for line in output.decode(errors='replace').splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in ('hevc', 'h264', 'av1') and fields[1] in ('8', '10'):
            modes.setdefault((fields[0], fields[1]), set())
        elif len(fields) == 3 and fields[0] == 'prores':
            depth, name = _PRORES_PROFILES.get(fields[2], ('', ''))
            if depth == fields[1]:
                modes.setdefault(('prores', depth), set()).add(name)
    return modes


def _verify_hardware_output(
        ffmpeg: str, ffprobe: str, choice: VideoEncodeChoice, run,
) -> tuple[bool, dict]:
    muxer = GPU_MUXERS[choice.encoder]
    probe_size = '640x360' if choice.device.backend == 'mf' or choice.encoder == 'ffv1' else '320x192'
    source = f'testsrc2=size={probe_size}:rate=24'
    source += ',format=' + planar_yuv_format(choice.output_chroma_format, choice.bit_depth)
    frames = '4'
    encoded = run(hardware_encode_command(
        ffmpeg, choice, ['-f', 'lavfi', '-i', source],
        ['-frames:v', frames, '-nostats', '-loglevel', 'error',
         '-f', muxer, 'pipe:1'],
    )).stdout
    probe_result = run([
        ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_entries', 'stream=codec_name,pix_fmt,profile,nb_read_frames',
        '-of', 'json', '-f', muxer, 'pipe:0',
    ], input=encoded)
    probe = json.loads(probe_result.stdout)
    streams = probe.get('streams') if isinstance(probe, dict) else None
    stream = streams[0] if isinstance(streams, list) and streams and isinstance(streams[0], dict) else {}
    accepted = (
        not probe_result.stderr.strip()
        and stream.get('codec_name') == choice.encoder
        and yuv_format_matches(stream.get('pix_fmt'), choice.output_chroma_format, choice.bit_depth)
        and str(stream.get('nb_read_frames')) == frames
    )
    return accepted, stream


def probe_gpu_chroma_formats(
        ffmpeg: str, ffprobe: str, choice: VideoEncodeChoice, cancel_event,
) -> tuple[str, ...]:
    """Test the selected hardware encoder settings using only candidate chroma formats."""
    def run(arguments, **kwargs):
        if cancel_event.is_set():
            raise TaskCancelled()
        return run_command(
            arguments, capture_output=True, timeout=10, cancel_event=cancel_event, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs,
        )

    supported = []
    failures = []
    for chroma_format in gpu_chroma_candidates(choice):
        try:
            accepted, stream = _verify_hardware_output(
                ffmpeg, ffprobe, replace(choice, chroma_format=chroma_format), run,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            stderr = getattr(error, 'stderr', None)
            detail = stderr.decode(errors='replace').strip() if stderr else str(error)
            failures.append(f'{chroma_format} · {detail}')
        else:
            if accepted:
                supported.append(chroma_format)
            else:
                failures.append(f'{chroma_format} · {json.dumps(stream, ensure_ascii=False)}')
    if not supported and failures:
        raise ValueError('\n'.join(failures))
    return tuple(supported)


def discover_gpu_encoders(
        ffmpeg: str,
        ffprobe: str,
        cancel_event=None,
        *,
        report: Callable[[str], None] | None = None,
) -> tuple[GpuEncodeDevice, ...]:
    """List the encoder modes advertised by the FFmpeg build and the driver."""

    def emit(message: str, **values) -> None:
        if report is not None:
            report(translate_text(message).format(**values))

    def run(arguments, **kwargs):
        if cancel_event is not None and cancel_event.is_set():
            raise TaskCancelled()
        if report is not None:
            command = subprocess.list2cmdline(arguments) if sys.platform == 'win32' else shlex.join(arguments)
            report(f'$ {command}')
        result = run_command(
            arguments, capture_output=True, timeout=10, cancel_event=cancel_event,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **kwargs,
        )
        if report is not None and result.stderr:
            report(result.stderr.decode(errors='replace').strip())
        result.check_returncode()
        return result

    if not gpu_detection_supported():
        emit('GPU detection is unavailable on this platform.')
        return ()
    if report is not None:
        emit('System: {system} ({machine}), Python {python}',
             system=platform.platform(), machine=platform.machine(), python=platform.python_version())
        for executable in (ffmpeg, ffprobe):
            try:
                version = run([executable, '-version']).stdout.decode(errors='replace').splitlines()
                report('\n'.join(version[:3]))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                emit('Probe failed: {error}', error=error)
    try:
        listed = run([ffmpeg, '-hide_banner', '-encoders']).stdout.decode(errors='replace')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        emit('Probe failed: {error}', error=error)
        listed = ''
    encoders = {line.split()[1] for line in listed.splitlines() if line.strip().startswith('V') and len(line.split()) > 1}
    backends = {backend for backend in GPU_BACKENDS if any(f'{codec}_{backend}' in encoders for codec in GPU_CODECS)}
    arm64_windows = _windows_arm64()
    if arm64_windows:
        backends.intersection_update(('nvenc', 'vulkan'))
        emit('Windows ARM64 uses NVIDIA GPUs for encoding.')
    emit('FFmpeg hardware encoders: {encoders}',
         encoders=', '.join(sorted(f'{codec}_{backend}' for codec in GPU_CODECS for backend in backends
                                   if f'{codec}_{backend}' in encoders)) or translate_text('None'))
    if not backends and report is None:
        return ()
    probe_name = 'bluraysub-gpu-capabilities.exe' if sys.platform == 'win32' else 'bluraysub-gpu-capabilities'
    probe_path = Path(ffmpeg).absolute().with_name(probe_name)
    if not probe_path.is_file():
        installed_probe = Path(FFMPEG_PATH).with_name(probe_name)
        if installed_probe.is_absolute() and installed_probe.is_file():
            probe_path = installed_probe
    static_hdr_options = frozenset()
    if backends:
        try:
            help_text = run([ffmpeg, '-hide_banner', '-h', 'long']).stdout.decode(errors='replace')
            static_hdr_options = frozenset(re.findall(
                r'^[ \t]*(-mastering_display|-content_light)\b', help_text, re.MULTILINE,
            ))
        except (OSError, subprocess.SubprocessError) as error:
            emit('Probe failed: {error}', error=error)
        emit('FFmpeg HDR input options: {options}',
             options=', '.join(sorted(static_hdr_options)) or translate_text('None'))
    adapter_report = report if report is not None else lambda _message: None
    if sys.platform == 'win32':
        try:
            candidates = _windows_adapters(adapter_report)
        except (OSError, AttributeError) as error:
            emit('Probe failed: {error}', error=error)
            candidates = []
        if arm64_windows:
            candidates = [device for device in candidates if device.backend == 'nvenc']
        if 'mf' in backends:
            candidates.append(GpuEncodeDevice('windows:mf', 'Media Foundation', 'mf'))
    elif sys.platform.startswith('linux'):
        candidates = _linux_adapters(backends, adapter_report)
    elif sys.platform == 'darwin' and 'videotoolbox' in backends:
        try:
            name = run(['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string']).stdout.decode(errors='replace').strip()
        except (OSError, subprocess.SubprocessError) as error:
            emit('Probe failed: {error}', error=error)
            name = ''
        candidates = [GpuEncodeDevice(
            'macos:videotoolbox', name or 'VideoToolbox', 'videotoolbox',
            hardware_id='apple:integrated' if platform.machine().lower() in ('arm64', 'aarch64') else '',
        )]
    else:
        candidates = []
    if backends and not probe_path.is_file():
        emit('GPU capability query tool is missing. Run setup to install it: {path}', path=probe_path)
        return ()
    vulkan_depths = {}
    if 'vulkan' in backends:
        try:
            vulkan = _parse_vulkan_adapters(run([str(probe_path), '--list-vulkan']).stdout, nvidia_only=arm64_windows)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            emit('GPU capability query failed: {error}', error=error)
        else:
            vulkan_depths = {device.vulkan_adapter: depths for device, depths in vulkan}
            candidates = _merge_vulkan_adapters(candidates, [device for device, _ in vulkan])
    devices = []
    codec_order = {codec: index for index, codec in enumerate(GPU_CODECS)}
    for device in candidates:
        device_name = gpu_device_label(device)
        emit('Adapter: {device}, interface {interface}, index or path {adapter}', device=device_name,
             interface=device.interface or translate_text('System default'),
             adapter=device.adapter or translate_text('System default'))
        # FFmpeg's Media Foundation encoder uses the system's first hardware transform.
        if device.backend == 'mf' and any(codec != 'ffv1' for gpu in devices for codec, _ in gpu.formats):
            emit('Media Foundation uses the system-selected encoder. A vendor encoder is already available.')
            continue
        advertised = {('ffv1', depth): set() for depth in vulkan_depths.get(device.vulkan_adapter, ())}
        if device.backend not in backends:
            emit('FFmpeg does not include the adapter encoder: {backend}', backend=GPU_BACKENDS[device.backend])
        elif device.backend != 'vulkan':
            try:
                advertised.update(_parse_driver_modes(run([str(probe_path), device.backend, device.adapter]).stdout))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                emit('GPU capability query failed: {error}', error=error)
        emit('Driver encoding modes: {modes}', modes=', '.join(
            f'{GPU_CODECS[codec]} {depth}-bit' + (f' ({", ".join(sorted(profiles))})' if profiles else '')
            for (codec, depth), profiles in advertised.items()
        ) or translate_text('None'))
        modes = []
        supported_presets = []
        for codec, depth in sorted(advertised, key=lambda mode: (codec_order[mode[0]], int(mode[1]))):
            backend = 'vulkan' if codec == 'ffv1' else device.backend
            if f'{codec}_{backend}' not in encoders:
                continue
            presets = [
                (codec, depth, name) for name in _preset_parameters(device, codec, depth)
                if codec != 'prores' or name in advertised[codec, depth]
            ]
            if presets:
                modes.append((codec, depth))
                supported_presets.extend(presets)
        if modes:
            devices.append(replace(device, formats=tuple(modes), supported_presets=tuple(supported_presets),
                                   static_hdr_input_options=static_hdr_options))
    emit('Available GPU devices: {count}', count=len(devices))
    for device in devices:
        report_formats = ', '.join(f'{GPU_CODECS[codec]} {depth}-bit' for codec, depth in device.formats)
        emit('{device}: {formats}', device=gpu_device_label(device), formats=report_formats)
    return tuple(devices)
