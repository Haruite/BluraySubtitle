# Video Encoding and VapourSynth

English | [简体中文](Video-Encoding-and-VapourSynth.zh-Hans.md)

This page covers encoder settings and the VPy processing path. For container, codec, remux, and encode terminology, see [Media Fundamentals](Media-Fundamentals.md). Final encoded output is muxed into MKV.

## Choosing H.264, H.265, or AV1

| Encoder | Supported output depth | Practical tradeoff |
| --- | --- | --- |
| x264 / AVC | 8-bit or 10-bit | Mature, generally faster, and broadly compatible with older players; usually needs more data than a well-configured newer codec |
| x265 / HEVC | 8/10/12-bit; 10-bit default | Project default; better compression efficiency at greater encoding cost. Dolby Vision preservation requires 10-bit. |
| SVT-AV1 | Depends on the selected build; standard builds support 8/10-bit | Modern compression and film-grain tools; check decoder support. The current workflow omits Dolby Vision with a task message. |

Ten-bit SDR output can reduce quantization/banding problems but does not turn SDR into HDR. Codec background belongs in [Media Formats](Media-Formats-and-Dolby-Vision.md#video-formats).

The setup scripts build unmodified upstream SVT-AV1. The Encode controls and settings dialog offer 12-bit for SVT-AV1 when the configured executable lists `12` among its `--input-depth` values in `--help`. Saving a new SVT-AV1 path refreshes the available bit depths.

Quality depends on source texture/motion, encoder version, rate control, preset, filters, and playback conditions. Compare representative samples from the same source at the intended viewing distance; transcoding one test result into another codec adds generation loss and biases the comparison.

## Video encoding devices

**Enable GPU encoding** is off by default. Turn it on in **Settings → Advanced → Video encoding devices** to show GPU settings and the **Video encoding device** column for main and SP videos. Each device groups its codec, bit depth, preset, and chroma sampling together.

**Detect GPUs** queries the available codecs, depths, and driver capabilities. **Copy report** includes the driver results and query commands. After you select a GPU and its encoding parameters, FFmpeg tries the chroma formats for that combination. The **Chroma sampling** list shows the formats that FFprobe confirms in the resulting streams. For a source installation, setup installs the capability query executable alongside FFmpeg.

| Setup target | Hardware backends |
| --- | --- |
| Standard Windows x64 | NVIDIA NVENC, Intel Quick Sync, AMD AMF, and Vulkan |
| Windows ARM64 | NVIDIA NVENC and Vulkan on NVIDIA GPUs with a native driver |
| Linux x64 | NVIDIA NVENC via CUDA, Intel Quick Sync via VAAPI and oneVPL, AMD AMF via the AMD runtime, and Vulkan |
| Linux ARM64 | NVIDIA NVENC and Vulkan where supported by the installed driver |
| macOS Intel and Apple silicon | The system-selected VideoToolbox hardware encoder and Vulkan via MoltenVK |

For a GPU to appear, the configured FFmpeg must include its hardware backend and the host needs a working vendor driver. The Linux AMF interface uses a driver-selected Vulkan adapter, so the app offers it when there is a single AMD render adapter. VideoToolbox exposes one system-selected device. A custom Windows x64 FFmpeg with Media Foundation can offer the system-selected 8-bit encoder when no vendor backend advertises a mode. [FFmpeg hardware device documentation](https://ffmpeg.org/ffmpeg.html#Advanced-Video-options) · [NVIDIA native ARM64 NVENC requirements](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-video-encoder-api-prog-guide/index.html#basic-encoding-flow)

Vulkan runs FFV1 encoding on the GPU's compute shaders. It requires a Vulkan 1.3 GPU driver and an FFmpeg build with `ffv1_vulkan`. BluraySubtitle can offer `yuv420`, `yuv422`, and `yuv444` at 8, 10, and 12 bits when the modes pass the short encode. The app muxes lossless FFV1 version 4 video into the final MKV. [FFV1 format and uses](Media-Formats-and-Dolby-Vision.md#ffv1) · [FFmpeg Vulkan compute codecs](https://www.khronos.org/blog/video-encoding-and-decoding-with-vulkan-compute-shaders-in-ffmpeg)

On macOS, the VideoToolbox ProRes preset determines sampling. The driver can offer 10-bit ProRes 422 and 12-bit ProRes 4444 profiles. [ProRes profiles and uses](Media-Formats-and-Dolby-Vision.md#apple-prores) · [Apple VideoToolbox encoder capabilities](https://developer.apple.com/documentation/videotoolbox/vtcopysupportedpropertydictionaryforencoder(width:height:codectype:encoderspecification:encoderidout:supportedpropertiesout:))

Each device processes its assigned rows in table order, and different devices can run concurrently. SP tracks attached to a main output use that output's encoder. The VPy for each row converts output 0 after filtering and hardsubs to that row's bit depth and chroma sampling. VSEdit preview uses the same format.

## Output resolution

In **Blu-ray Encode**, choose **Output resolution** above the lossless audio control. The default, **Original resolution**, uses the dimensions produced by the VPy. The 2160p, 1440p, 1080p, 720p, and custom settings fit the picture inside the selected width and height while preserving its display aspect ratio. For example, a cropped `3840×1600` input fits within 1080p as `1920×800`. Smaller pictures keep their size unless **Allow upscaling** is selected.

In **Custom resolution**, changing either dimension adjusts the other to match the source video’s display aspect ratio. With **Allow upscaling** cleared, the original width and height cap the two inputs. The batch controls use the first available main video as the reference, or the first selected standalone SP video if there is no main video. A row override uses that row’s source.

The batch setting applies to main and SP videos from Blu-ray and Remux sources. Right-click a video row and choose **Output resolution** to override it. VSEdit previews use the selected dimensions and can analyze black borders on the preview source. For a Blu-ray playlist, the encode analyzes the assembled source. Managed subtitles render at the output size, while scaling preserves the frame order and timestamps.

The existing color and format checks govern HDR retention. With a verified resize, Dolby Vision L5 offsets follow the crop and the final picture size. The automatic HDR10+ path retains verified full-frame metadata. If the picture geometry or processing windows cannot be verified, Encode reports the omitted metadata and keeps the encoded video.

## CPU encoder command

For either Blu-ray or Remux input, the CPU section generates **Encoder command** from the selected tool, bit depth, and chroma sampling. Choose these settings before editing the command. x264 and x265 offer `yuv420`, `yuv422`, and `yuv444`. The bundled SVT-AV1 uses `yuv420`. The default x264 command applies `--profile high422 --output-csp i422` for 4:2:2 and `--profile high444 --output-csp i444` for 4:4:4.

At launch, a standalone `{params}` expands to the arguments in **Encoder parameters**. Changing the preset or its parameters updates the arguments used by the command. For a fully manual command, enter the arguments directly in **Encoder command**.

Encode captures the visible command at launch and resolves `{X264_PATH}`, `{X265_PATH}`, or `{SVT_AV1_PATH}` to the configured encoder path. You can also enter a program on `PATH` or quote its full path.

The program receives Y4M on standard input at the selected bit depth and sampling. Keep one output placeholder to declare the temporary video format. Use `{output.h264}` for raw H.264, `{output.hevc}` for raw HEVC, or `{output.ivf}` for AV1 in IVF. Process every input frame and write a single video with the selected bit depth and sampling. BluraySubtitle supplies the temporary path for each row and muxes the result with the source timestamps and selected tracks.

With x264, x265, or SVT-AV1, keep `{metadata}` where you want the automatic encoder metadata options inserted. For a different encoder, specify its metadata options in the command as needed.

Select **10-bit** and **yuv420** for these AV1 examples. Edit the parameters to suit the source. [aomenc options](https://aomedia.googlesource.com/aom/+/master/apps/aomenc.c) · [rav1e documentation](https://github.com/xiph/rav1e#compressing-video)

```text
aomenc --codec=av1 --ivf --passes=1 --cpu-used=6 --end-usage=q --cq-level=25 --bit-depth=10 --input-bit-depth=10 --lag-in-frames=0 -o {output.ivf} -
rav1e --speed 10 --quantizer 80 -o {output.ivf} -
```

## The BluraySubtitle encode pipeline

For Blu-ray input, the high-level path is:

```text
selected MPLS and tracks
        │
        ▼
staging MKV with the authored playlist/chapter range
        │
        ▼
VapourSynth .vpy script
        │
        ▼
vspipe --container y4m
        │
        ├── x264  → .h264
        ├── x265  → .hevc
        ├── SVT-AV1 → .ivf
        └── FFmpeg hardware encoder → .h264, .hevc, .ivf or temporary .mkv
        │
        ▼
final MKV with selected audio, subtitles, chapters, attachments, and metadata
```

The staging remux preserves source audio. Audio conversion and final audio cleanup happen only in the final mux after video encoding succeeds. This avoids performing a lossy or expensive audio operation before the video result exists.

`vspipe` supplies Y4M frames to the encoder through a pipe, so a normal encode does not need a full uncompressed intermediate video file. The encoded video is temporary and becomes a track in the final MKV.

Set `VSPIPE_PATH` in **Settings → External tools** to the VSPipe executable for Encode and FrameCheck. A separate VapourSynth installation needs its own Python bindings and filter scripts such as `mvsfunc.py`. On Linux, `PLUGIN_PATH` supplies the directory of compatible plugins to the selected VSPipe. Set the encoder and VSEdit paths in their corresponding rows.

## Rate control and the meaning of presets

### CRF

The built-in presets use **CRF** (Constant Rate Factor) rate control. CRF asks the encoder to pursue a quality level rather than a fixed final size:

- a lower CRF generally means higher quality and a larger file;
- a higher CRF generally means more loss and a smaller file; and
- the result size still varies with source complexity.

CRF numbers are not equivalent between x264, x265, and SVT-AV1. A value of 18 in one encoder must not be treated as the same quality as 18 in another.

For a strict delivery size, bitrate-based one-pass or multi-pass workflows may be more appropriate, but BluraySubtitle's built-in presets are CRF-oriented. User-defined presets and direct parameter edits can use other modes when the selected encoder supports them.

### Encoder preset

An encoder's own `--preset` controls the speed/compression-efficiency tradeoff. A slower preset spends more CPU time searching coding choices and can usually store a chosen quality more efficiently. It is not a simple quality switch: using a slower preset with the same CRF does not guarantee the same size or a uniformly visible improvement.

BluraySubtitle adds a second, project-level preset layer:

| Project preset | Intended use |
| --- | --- |
| Very Fast | Quick previews and short test encodes |
| Fast | Faster full-length encodes |
| Balanced | Default starting point |
| High Quality | More quality and analysis work |
| Very High Quality | More analysis and a lower CRF than High Quality |
| Extreme | Very slow, large-quality-budget starting point |

Each CPU encoder has six built-in presets. In Advanced settings, **Parameter preview** shows the selected preset's parameters in a copyable line. Use **Custom encode presets** to copy a preset as a starting point, then rename it and edit its parameters. CPU presets belong to an encoder. GPU presets belong to a device, codec, and bit depth. Device defaults and user-defined presets are stored in `config.json`.

In Encode, selecting a preset fills the **Encoder parameters** field. Direct edits keep the selected preset name, and Encode uses the visible parameters at launch.

## Built-in parameter presets

The built-in parameters in [`src/core/encode_presets.py`](../../src/core/encode_presets.py) provide starting points for tuning. x265's `placebo` preset has sharply diminishing returns; higher numeric SVT-AV1 presets encode faster with lower compression efficiency.

## Common parameters in plain language

| Parameter | Practical meaning |
| --- | --- |
| `--crf` | Quality/size target for CRF rate control |
| `--preset` | Encoder effort versus speed |
| `--aq-mode`, `--aq-strength` | Redistribute quantization according to spatial/visual complexity |
| `--bframes` | Maximum use of bidirectionally predicted frames |
| `--ref` | Reference-frame budget |
| `--me`, `--subme`, `--merange` | Motion-search method, refinement, and range |
| `--keyint` | Maximum keyframe/GOP interval |
| `--rc-lookahead` | Frames inspected ahead for rate-control and frame-type decisions |
| `--psy-rd`, `--psy-rdoq` | Psychovisual weighting in mode and quantization decisions |
| `--deblock` | In-loop deblocking behavior |
| `--film-grain` in SVT-AV1 | Film-grain synthesis strength, not a generic denoiser |

Parameters interact. Copying a long command from a different source type can make the result worse or only make the encode slower. Always keep the final color range, primaries, transfer, matrix, bit depth, and chroma format consistent with the processed frames.

## What VapourSynth does

VapourSynth is a Python-driven frame server. A `.vpy` script:

1. opens and indexes the source;
2. constructs a graph of frame-processing filters;
3. exposes one or more output `VideoNode` objects with `set_output()`; and
4. produces requested frames on demand when `vspipe` or a preview application evaluates that graph.

It does not encode video by itself. In this project, `vspipe` evaluates the selected output and writes Y4M frames to x264, x265, or SVT-AV1.

The GUI can generate, edit, and preview a `.vpy` script. Before encoding it injects the actual source path and, when enabled, native-resolution information. The selected output bit depth is synchronized with the final `fmtc.bitdepth(..., bits=N)` conversion. Hardsub mode activates the `assrender.TextSub` line and supplies the selected ASS, SSA, or SRT subtitle path. SUP hardsubs are not supported by this text-rendering path.

### Previewing processed and source frames in VSEdit

The generated default VPy exposes the processed `res` as output index `0` and the original `src8` as output index `1`. Click **Preview script**, then choose **Script > Preview** in VSEdit or press `F5` to open the preview window. Keep the same frame selected and press `0` for the processed frame or `1` for the source frame; the preview window title confirms the active index. Press `S` in the preview window to run **Save snapshot** for the displayed frame. These default keys can be reviewed or changed under **Settings > Hotkeys** in VSEdit.

Use sufficient intermediate precision and dither when reducing bit depth. Verify output `0`, frame count/rate, scan type, color properties, crop dimensions, and representative motion/gradients before a full encode. The [short-test instructions](../../README.md#how-do-i-run-a-short-encode-test) explain when a VPy-only trim is sufficient and when the whole media timeline must be cut.

### Automatic getnative

BluraySubtitle's getnative is adapted from [Infiziert90/getnative](https://github.com/Infiziert90/getnative). It estimates the vertical resolution before mastering upscale and the scaling kernel. The results populate `native_h` and `native_kernel` in VPy for inverse scaling before filtering; this cannot restore detail absent from the source.

Automatic getnative handles sources no taller than 1080p. For higher resolutions, run `src/scripts/getnative_file.py` manually and write the returned `height` and `kernel` into the VPy as `native_h` and `native_kernel`.

#### Frame selection and scheduling

FFmpeg extracts candidate frames in incremental rounds. Frames are ranked by edge energy, luminance variance, and entropy so that detailed, high-contrast pictures are tried first. A round can launch at most 20 samples, further limited by the logical CPU count and currently available physical memory. The memory calculation reserves 2 GiB for the system and budgets 800 MiB for every sample process. The 800 MiB value is a scheduling estimate, not a hard process limit: a complex frame or a short-lived final scan may use more.

Every sample already launched is allowed to finish, and every kernel and sample result is printed as soon as it becomes available. Five valid curves are only the threshold for deciding whether another round is necessary; all valid results from the completed round still participate in the final decision. If fewer than five are found, extraction continues incrementally, up to a 100-sample safety ceiling. A final result still requires at least two usable curves.

#### What one sample analyzes

`getnative.py` coordinates extraction, sample workers, native VapourSynth graphs, and final ranking in the application's Python environment. Each worker converts its PNG sample from RGB to BT.709 grayscale and evaluates all 16 inverse-scaling candidates: bilinear; eight bicubic parameter sets; Lanczos with 2, 3, 4, and 5 taps; and Spline16, Spline36, and Spline64. Each candidate descales the frame to a trial height, scales it back to the source dimensions, and measures the reconstruction error. The vertical search range is normally 40% through 98% of the source height.

Windows x64 setup installs the upstream R79 wheel into the selected Python. The packaged application and VSScript share a bundled CPython runtime and NumPy package. Re-run setup and rebuild the application after changing the system Python minor version.

For speed, every kernel first receives a centered half-size, step-4 coarse scan and then a full-frame 1p scan around the best coarse height. The first three priority kernels always reach the fine scan. After that, a kernel whose like-for-like coarse score is below 45% of the best coarse score may skip its fine scan, while still reporting the coarse result. After all kernels have reported, the winning kernel is checked again with a full-frame step-4 pass followed by a full-frame ±20p, 1p scan.
Each sample worker uses one VapourSynth frame worker and a 256 MiB frame-cache ceiling to control concurrent memory growth.

#### Curve and multi-frame selection

For each reconstruction-error curve, getnative looks for the sharp adjacent-height error drop described by the upstream method. The candidate height is the current height at that drop, and its primary score is the previous height's error divided by the current height's error. The metric's five-pixel border crop only excludes unreliable edge pixels; it is not a five-pixel correction to the detected height. Broad valleys are used only as a fallback when no credible sharp drop exists.

Ranking excludes unstable or oscillating curve tails and a fixed 535p–545p false-positive band. The stable-curve upper limit is `source height × 1040 / 1080`; curve-tail spans and the high-resolution oscillation boundary also scale with source height. A 1080p source rejects values above 1040p; a 2160p source rejects values above 2080p and keeps candidates near 1080p.

Uniform-color samples are skipped before kernel analysis, excluding the same five-pixel border used by the error metric. Such frames contain no spatial detail from which to estimate a scaling kernel or native resolution.

Usable samples are grouped by rounded height. Each sample is weighted as `min(score, 2) * (height / search-range maximum)^4`; the sum of all sample weights in a height group determines which group wins, with the higher height breaking an exact tie. The selected group's weighted height and kernel votes produce the final VPy values.

Getnative is a heuristic: detailed line art usually gives clearer curves than dark scenes, credits, soft photography, noise, or mixed-resolution material. Compare per-kernel output across representative episodes.

### Generated VPy restoration controls

The five Encode controls replace `denoise_strength`, `dehalo_strength`, `dering_strength`, `deband_strength`, and `antialiasing_strength` in the generated VPy at launch. A custom script without these names is unchanged. Startup defaults are saved under **Advanced**.

| Control | Range / default | Use and processing |
| --- | --- | --- |
| Denoise | `0.0`–`3.0` / `0.6` | Conservative spatial luma `nlm_ispc.NLMeans` (`d=0`, small search), protected by a Prewitt mask and `mvsfunc.LimitFilter`. Reduce strength if grain/paper texture changes; inspect the removed noise before increasing it. |
| Dehalo | `0.0`–`1.0` / `0.0` | Enable for broad sharpening halos. A luma downscale/upscale estimate based on [abcxyz](https://github.com/xyx98/my-vapoursynth-script) is constrained by `rgvs.Repair` and blended by strength. |
| Dering | `0.0`–`1.0` / `0.0` | Enable for narrow DCT/rescale ringing. A `MinBlur`/`HQDering`-style mask excludes the edge itself and blends repaired, limited smoothing around it. |
| Deband | `0.0`–`1.0` / `0.5` | YUV `placebo.Deband` or CPU `muvsfunc.SmoothGrad` when vs-placebo is unavailable, with a softened multi-plane Prewitt mask restoring edges/texture; reduce or disable when gradients/effects are harmed. |
| Anti-aliasing | `0.0`–`1.0` / `0.5` | Limited EEDI2 luma blended toward the debanded source; disable for detailed or intentionally pixel-sharp material without aliasing. |

`0` disables a stage. Deband/anti-aliasing use a literal half blend at `0.5` and full limited output at `1`. Other restoration stages affect luma only. For dehalo/dering, start at `0.15`–`0.25`; use `0.25`–`0.35` only for clear defects after frame checks, and avoid more than `0.4` across a whole title. Their strength controls blending, not mask width or halo radius.

Identify the defect before enabling dehalo or dering together. Grain, paper texture, rain, glow, line art, and high-resolution artwork can resemble defects; inspect bright, dark, textured, and effects-heavy scenes. Use a custom VPy for shot-specific tuning of radius, masks, thresholds, or other internal parameters.

### Comparison images and full-frame corruption checks

**Output comparison images** writes a source/encoded PNG pair under `<actual output folder>/Compare`, selecting matching pictures by zero-based video frame number.

**Check corrupted frames** reruns the exact encoding VPy and compares every output frame with the final MKV using FFmpeg PSNR, also checking frame counts and decoder errors. `<actual output folder>/FrameCheck/<name>.frame-check.json` records `pass`, `suspect` (low PSNR), `fail` (count/decode error), or `error` (checker failure). Non-pass results retain the MKV and add a row warning; visual review remains necessary.

The frame-check switch is on Encode; its luma/chroma thresholds are under **Settings > Advanced > Default encode settings**. `encode.frame_check_luma_psnr_threshold_db` and `encode.frame_check_chroma_psnr_threshold_db` accept `0.0`–`100.0` and default to `30.0`; U/V share the chroma value. Any applicable plane below its threshold makes a frame suspicious. Higher thresholds increase sensitivity and false positives.

A full check renders every VPy frame and can take substantially longer than the video itself. Cost depends on the decoder, filters, resolution, storage, and runtime.

### Automatic black-border cropping

Automatic black-border cropping is opt-in. Before preparing the final VPy, BluraySubtitle probes duration and dimensions, then uses FFmpeg input-side seeks to analyze one pseudo-random point in each time bucket. It samples one point per 150 seconds, bounded to 4–24 points, and decodes only three nearby frames at each point without writing image files. The fixed crop is derived from the union of all detected active rectangles, so a pixel used by any sampled frame is kept. The managed `src8.std.Crop(...)` operation is inserted before the rest of the filter graph.
Automatic analysis is necessarily heuristic: dark scenes, credits, overlays, and unusual borders can produce a wrong result, so inspect the reported margins and encoded picture.

The crop is even-aligned. Existing managed blocks are replaced or removed between rows. A custom VPy must expose a safe `src8`/`res` insertion boundary; an unknown boundary or a non-managed `Crop`/`CropAbs` call combined with nonzero automatic cropping fails the row to prevent ambiguous or double cropping.

### HDR to SDR

In **Blu-ray Encode**, enable **Convert HDR to SDR** below **Output comparison images**. The switch applies to the whole batch, including CPU and GPU outputs. It is off by default. Change the default under **Settings > Advanced > Default encode settings**.

Preview and encoding tone-map HDR to BT.709. HDR10 and HDR10+ use the PQ picture, and HLG uses its HLG transfer. UHD Blu-ray Dolby Vision uses the HDR10-compatible Profile 7 base layer. For Remux input, a compatible base layer is used when available, and Profile 5 color reconstruction uses the decoder's RPU and Vulkan-enabled vs-placebo. The SDR output uses SDR color tags, and the batch treats the intentional omission of source HDR metadata and FEL residuals as part of the conversion.

### Automatic HDR metadata handling

For Dolby Vision input, x265 10-bit encodes the base layer with profile 8.1 RPU; FEL image residuals cannot be used. Profile 8 requires an HEVC Main10 base layer, as specified in [Dolby's profile table, section 3.1](https://professional.dolby.com/siteassets/content-creation/dolby-vision-for-content-creators/dolbyvisioninmpegdashspecification_v2_0_public_20190107.pdf). See [Dolby Vision layers](Media-Formats-and-Dolby-Vision.md#dolby-vision-fundamentals) for MEL/FEL and conversion conditions, and the [encoder comparison](#choosing-h264-h265-or-av1) for encoder and bit-depth choices.

Before starting the encoder, BluraySubtitle samples output 0's first, middle, and last frames. Stable `_ColorRange`, `_Primaries`, `_Transfer`, `_Matrix`, and `_ChromaLocation` properties take precedence over source metadata; missing properties fall back to the source. The row stops if the sampled values differ.

When the actual source exposes HDR10+, x265 10/12-bit encoding with 4:2:0 extracts its validated JSON and checks the metadata frame count against the VPy output. When x265 advertises `--dhdr10-info`, the metadata is supplied during encoding; otherwise, or when native verification fails, `hdr10plus_tool` performs verified post-injection. Failures continue without dynamic metadata and retain non-empty JSON for diagnosis. Custom scripts using this path must preserve frame order.

Dolby Vision uses native x265 RPU input when the executable advertises it and the row already has VBV and mastering-display parameters. Otherwise, or when native verification fails, it uses `dovi_tool` injection without changing rate control.

When both HDR10+ and Dolby Vision are present, x265 writes both in one encode if both native paths qualify. HEVC is checked for both metadata sets after the last injection and before final muxing.

Hardware encoding preserves HDR10+ and Dolby Vision with 10-bit 4:2:0 HEVC. It transfers compatible HDR10 mastering-display and light-level metadata to the Matroska track. After encoding, `dovi_tool` and `hdr10plus_tool` inject their respective metadata into temporary HEVC streams. The verified stream replaces the previous stream after checking that existing Dolby Vision metadata was preserved.

Encode continues with the selected settings when the output cannot preserve all source HDR metadata. For example, 8-bit output omits automatic mastering-display and light-level metadata. With 4:2:2 or 4:4:4 output, Encode omits automatic Dolby Vision and HDR10+ metadata. The completion report identifies what was omitted. Metadata tool failures also produce a diagnostic report and keep the usable encoded video.

If automatic cropping changes the coded dimensions, each Dolby Vision L5 active-area preset is adjusted by the physical crop before the resulting profile 8.1 RPU is supplied to either native x265 or post-injection. A manually supplied RPU is therefore incompatible with automatic cropping. HDR10+ does not have a corresponding crop-offset edit in this workflow: its source brightness statistics are retained without remeasurement after cropping.

After the final MKV is published, BluraySubtitle re-probes the static fields it added automatically and reruns the active dynamic-metadata checks. Dolby Vision must report profile 8 with the same RPU frame count as the VPy output. A mismatch retains the MKV, records a non-overwriting warning report, and lets later rows continue.

## VFR video and timing

CFR and VFR encoding both preserve the source MKV presentation timestamps and video start offset. Each VFR frame's presentation time comes from its timestamp; nominal frame rates alone cannot establish whether timelines match.

### Implementation notes

Encode restores the source video timeline with `mkvmerge --timestamps`; hardsubs use the same timeline. Full encoding extracts video timestamps with `mkvextract timestamps_v2`.

[Prefix tests](../../README.md#how-do-i-run-a-short-encode-test) read timestamps for the actual output frame count and its end boundary. An unavailable source frame count or timestamps requiring sub-microsecond precision requires full-track extraction.

## Interlaced, telecined, and mixed-cadence sources

The generated VPy cannot safely choose one automatic treatment for every source. `_FieldBased` can report whether a frame is progressive (`0`), bottom-field-first (`1`), or top-field-first (`2`), but it does not say why the fields exist. True interlaced camera or video material needs deinterlacing; 3:2 telecined film or animation normally needs field matching plus decimation (IVTC); mixed progressive, telecined, and interlaced sections may need range-specific handling.
Blindly using QTGMC can create an unnecessary doubled frame rate or preserve telecine judder, while blindly applying IVTC can discard real motion fields. Container metadata can also be wrong, so confirm the field order and cadence by frame-stepping representative motion, pans, and credits instead of trusting one metadata label.

Perform frame-count-changing deinterlacing, IVTC, and mixed-cadence processing externally first, keeping timestamps and audio synchronized, then use the progressive result as the new Encode source. The following examples are references for that external preparation. For interlaced material, a typical QTGMC starting point is:

```python
import havsfunc as haf

# TFF=True for top-field-first; use False for bottom-field-first.
# FPSDivisor=1 preserves both temporal field samples as double-rate progressive video.
src8 = haf.QTGMC(src8, TFF=True, Preset="Slower", FPSDivisor=1)
src8 = src8.std.SetFrameProps(_FieldBased=0)
```

Use `FPSDivisor=2` only when a single-rate progressive result is intentional and its motion has been checked. For regular 3:2 telecine, install a field-matching plugin such as VIVTC and start from its field match and decimation path instead:

```python
matched = core.vivtc.VFM(src8, order=1)  # order=1 TFF; order=0 BFF
src8 = core.vivtc.VDecimate(matched)
src8 = src8.std.SetFrameProps(_FieldBased=0)
```

Do not merely clear `_FieldBased`; that changes metadata without reconstructing a progressive picture. Put deinterlacing or IVTC before bit-depth conversion, getnative/descale, denoising, and other restoration. For mixed cadence, split or conditionally replace the affected ranges rather than forcing one filter over the whole title. Preview combing, motion cadence, fades, and scrolling credits, then verify the resulting frame rate, duration, and audio synchronization before a full encode.
QTGMC/VIVTC and their dependencies must be present in the VapourSynth runtime used for external preparation.

## Plugins used by the generated script

The default script is a usable starting point, not a universal restoration recipe. It accepts progressive video only and rejects field-based input instead of processing it incorrectly. L-SMASH indexes are stored under the system temporary directory rather than beside a potentially read-only disc source. When native inverse scaling is active, only luma uses the detected descale kernel; chroma follows Blu-ray's left chroma location, and a reconstruction mask restores the original YUV planes over credits and other final-resolution composites. Its current plugin chain includes:

Credits, on-picture text, and already-burned subtitles are not recognized by OCR or by their meaning. When native inverse scaling is active, the script compares the original 16-bit luma with luma that was descaled to the detected native height and then reconstructed to the output size. It binarizes absolute differences above two 8-bit code values (scaled to 16-bit), expands the mask twice, and inflates it once. After filtering and resizing, white mask regions receive the original YUV planes.
Text composited at the final master resolution normally differs strongly from the native-height reconstruction, which is why Staff rolls and burned subtitles are usually protected. Fine texture, sharpening, line art, or noise can also trigger the same mask; this is an intentional source-preserving false positive, not semantic text detection. Optional external ASS/SSA/SRT hardsubs are separate and are rendered directly by `assrender.TextSub` from the selected subtitle file.

| Namespace/package | Role in the generated script |
| --- | --- |
| `lsmas.LWLibavSource` | Indexed source reader |
| `fmtc` | Bit-depth conversion and resampling |
| `descale` | Optional inverse scaling from detected native resolution |
| `nlm_ispc` | Denoising |
| `placebo`, `muvsfunc.SmoothGrad` | Vulkan or CPU debanding |
| `mvsfunc.LimitFilter` | Limit filtered changes against reference clips |
| `eedi2` | Edge-directed antialiasing |
| `rgvs.Repair` | Constrain repaired planes |
| built-in `std` and `resize` | Plane operations, format-safe resizing, output construction |
| `assrender.TextSub` | Optional ASS/SSA/SRT rendering for hardsubs |

Availability is environment-dependent. A script fails at evaluation time if a required plugin or Python module is missing; the setup scripts and External Tools settings determine which runtime is used.

## Other commonly encountered VapourSynth plugins

Custom scripts often use a different chain. Common categories include:

| Task | Common examples | Main caution |
| --- | --- | --- |
| Source loading | BestSource, L-SMASH-Works, FFMS2 | Indexing and timestamp behavior differ |
| Deinterlacing/IVTC | QTGMC, VIVTC, TIVTC | Determine field order and cadence first |
| Rescaling/descaling | `resize`, fmtconv, descale, zimg-based helpers | Preserve range, matrix, chroma location, and aspect ratio |
| Denoising | BM3D variants, DFTTest, KNLMeansCL/NLMeans, MVTools-based filters | Excessive denoising destroys texture and grain |
| Debanding | neo_f3kdb, libplacebo | Add controlled grain/dither to avoid re-quantized bands |
| Antialiasing | EEDI2/EEDI3, NNEDI3/ZNEDI3, sangnom-based helpers | Mask changes when only line art needs correction |
| Subtitle rendering | assrender/libass-based filters | Fonts and script resolution affect layout |

These names describe ecosystem options, not guaranteed BluraySubtitle dependencies. A custom script owns its plugin requirements and output correctness.

The setup scripts build ZNEDI3, a CPU implementation of NNEDI3 for custom scripts. Use `core.znedi3.nnedi3` in VPy.

The bundled `vsmlrt.py` provides the Python interface. To run a VPy that uses VSMLRT, build an inference backend for your platform and architecture, install it and its dependencies in the VapourSynth runtime used by BluraySubtitle, and obtain the required models. [VSMLRT upstream](https://github.com/AmusementClub/vs-mlrt)

## Further reading

See [References](References.md) for the H.264, H.265, AV1, x265, SVT-AV1, and VapourSynth specifications and manuals.
