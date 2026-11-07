local mp = require('mp')
local msg = require('mp.msg')
local utils = require('mp.utils')
local write_atomic = dofile(mp.command_native({'expand-path', '~~home/bluray-modules/atomic_write.lua'}))
local options = {language = 'en'}
require('mp.options').read_options(options, 'bluray_defaults')

local settings = {
    'video-sync', 'interpolation', 'interpolation-threshold', 'interpolation-preserve',
    'correct-downscaling', 'linear-downscaling', 'linear-upscaling', 'scaler-resizes-only',
    'sigmoid-upscaling', 'sigmoid-center', 'sigmoid-slope',
    'deband', 'deband-iterations', 'deband-threshold', 'deband-range', 'deband-grain',
    'dither', 'dither-depth', 'temporal-dither', 'temporal-dither-period',
    'deinterlace', 'deinterlace-field-parity', 'brightness', 'contrast', 'gamma',
    'gamma-factor', 'saturation', 'hue', 'sharpen',
    'tone-mapping', 'tone-mapping-param', 'gamut-mapping-mode', 'hdr-compute-peak',
    'hdr-reference-white', 'hdr-peak-percentile', 'hdr-contrast-recovery',
    'target-colorspace-hint', 'target-peak', 'target-prim', 'target-trc',
    'blend-subtitles', 'sub-auto', 'sub-file-paths', 'sub-codepage', 'slang', 'subs-fallback',
    'sub-font', 'sub-font-size', 'sub-color', 'sub-back-color', 'sub-border-style',
    'sub-outline-color', 'sub-outline-size', 'sub-shadow-offset', 'sub-blur',
    'sub-bold', 'sub-italic', 'sub-spacing', 'sub-line-spacing', 'sub-hinting',
    'sub-align-x', 'sub-align-y', 'sub-justify', 'sub-margin-x', 'sub-margin-y',
    'sub-scale', 'sub-scale-signs', 'sub-scale-by-window', 'sub-scale-with-window',
    'sub-use-margins', 'sub-ass', 'sub-ass-force-margins', 'sub-ass-override',
    'sub-ass-scale-with-window', 'sub-ass-style-overrides', 'sub-ass-styles',
    'sub-delay', 'secondary-sub-delay', 'sub-visibility', 'secondary-sub-visibility',
    'sub-pos', 'secondary-sub-pos', 'sub-hdr-peak', 'image-subs-hdr-peak',
    'glsl-shaders', 'glsl-shader-opts',
}

for _, scaler in ipairs({'scale', 'cscale', 'dscale', 'tscale'}) do
    for _, suffix in ipairs({
        '', '-antiring', '-blur', '-clamp', '-param1', '-param2', '-radius',
        '-taper', '-window', '-wparam', '-wtaper',
    }) do
        settings[#settings + 1] = scaler .. suffix
    end
end

local function quote(value)
    assert(not value:find('[%z\r\n]'), 'A setting contains a line break or a NUL byte')
    if not value:find('"', 1, true) then
        return '"' .. value .. '"'
    end
    return '%' .. #value .. '%' .. value
end

local function persistent_path(value)
    if value == '' or value:match('^[/~]') or value:match('^%a[%w+.-]*://') then
        return value
    end
    return utils.join_path(mp.get_property('working-directory'), value)
end

local function collect_settings()
    local lines = {'# Settings saved from the mpv context menu'}
    for _, name in ipairs(settings) do
        local property = 'options/' .. name
        local info = mp.get_property_native('option-info/' .. name)
        if info and info.type == 'String list' then
            -- Each append takes one value even if a path contains a list separator.
            lines[#lines + 1] = name .. '-clr'
            for _, value in ipairs(mp.get_property_native(property, {})) do
                if value ~= '' then
                    if name == 'glsl-shaders' then value = persistent_path(value) end
                    lines[#lines + 1] = name .. '-append=' .. quote(value)
                end
            end
        elseif info and info.type == 'Key/value list' then
            lines[#lines + 1] = name .. '-clr'
            local entries = {}
            for key, value in pairs(mp.get_property_native(property, {})) do
                entries[#entries + 1] = '%' .. #key .. '%' .. key .. '=' .. value
            end
            table.sort(entries)
            for _, entry in ipairs(entries) do
                lines[#lines + 1] = name .. '-append=' .. quote(entry)
            end
        elseif info then
            local value = mp.get_property(property)
            -- mpv reports zero for an automatic scaler radius but rejects zero in config files.
            if value ~= nil and not (name:match('-radius$') and tonumber(value) == 0) then
                if name == 'sub-ass-styles' then value = persistent_path(value) end
                lines[#lines + 1] = name .. '=' .. quote(value)
            end
        end
    end
    return table.concat(lines, '\n') .. '\n'
end

mp.register_script_message('save', function()
    local ok, err = pcall(function()
        local path = mp.command_native({'expand-path', '~~home/bluray-defaults.conf'})
        write_atomic(path, collect_settings())
        msg.info('Saved default settings to ' .. path)
    end)
    if ok then
        mp.osd_message(options.language == 'zh' and '已保存为默认设置' or 'Saved as default settings')
    else
        msg.error(err)
        mp.osd_message(options.language == 'zh' and '默认设置保存失败，请查看 mpv 日志' or
            'Could not save default settings. See the mpv log.')
    end
end)
