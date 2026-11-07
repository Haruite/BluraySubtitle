# mpv-lazy shader sources and licenses

English | [简体中文](COPYRIGHT.zh-Hans.md)

The shader sources come from the [mpv-lazy 2026FM release](https://github.com/hooke007/mpv_PlayKit/tree/1ad89a52e8dab222b5628ab835bb0803995ead3a/portable_config/shaders). The copies in this directory retain their attribution and differ from the release only in whitespace.

| Shader files | Copyright and license |
| --- | --- |
| Adaptive_sharpen/Adaptive_sharpen_lite_RT.glsl | bacondither, BSD 2-Clause terms in the shader header |
| Anime4K/Anime4K_Restore_CNN_L.glsl and Anime4K_Upscale_GAN_x2_M.glsl | bloc97, MIT terms in the shader headers |
| EDI/nnedi3_nns64_win8x4.glsl and FSRCNNX/FSRCNNX_x2_16_0_4_1.glsl | LGPL-3.0-or-later as declared in the shader headers. [LGPL v3](licenses/LGPL-3.0.txt) incorporates [GPL v3](../vapoursynth_scripts/licenses/GPL-3.0.txt). |
| ESRGAN/k7_modernAnime_FHD_x2.glsl and k7_modernAnime_DT_FHD_x2.glsl | hooke007, [MIT](licenses/k7-MIT.txt) |

The desktop installer downloads the following files from the same release and checks their SHA-256 digests.

| Shader files | Attribution and license |
| --- | --- |
| Ani/Ani4Kv2_ArtCNN_C4F32_i2_dx.glsl and AniSD_ArtCNN_C4F32_i4_dx.glsl | Sirosky's model weights use [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). The ArtCNN architecture by Joao Chrisostomo uses MIT, included in each shader header. |
| QCOM/QCOM_SGEDS_ms_RT.glsl | The shader header links to the [original Qualcomm Innovation Center code's BSD 3-Clause license](https://github.com/SnapdragonGameStudios/snapdragon-gsr/blob/main/LICENSE). |
