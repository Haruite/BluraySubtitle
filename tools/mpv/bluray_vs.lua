local mp = require('mp')
local msg = require('mp.msg')
local utils = require('mp.utils')
local write_atomic = dofile(mp.command_native({'expand-path', '~~home/bluray-modules/atomic_write.lua'}))
local options = {language = 'en'}
require('mp.options').read_options(options, 'bluray_vs')

local filter_label = 'bluray-vs'
local preset_names = {mvtools = 'MVTools', rife = 'RIFE', ccd = 'CCD', bm3d = 'BM3D'}
local interpolates = {mvtools = true, rife = true}
local multiplier_path = mp.command_native({'expand-path', '~~home/bluray-vs/interpolation-multiplier'})
local preset_files = {}
for name in pairs(preset_names) do
    preset_files[name] = mp.command_native({'expand-path', '~~home/bluray-vs/' .. name .. '.vpy'})
end

local function normalize_multiplier(text)
    if type(text) ~= 'string' then return end
    local numerator, denominator = text:match('^%s*(%d+)%s*/%s*(%d+)%s*$')
    if numerator then
        numerator, denominator = tonumber(numerator), tonumber(denominator)
    else
        local whole, decimals = text:match('^%s*(%d+)%.(%d+)%s*$')
        if whole then
            decimals = decimals:gsub('0+$', '')
            if #decimals > 6 then return end
            denominator = 10 ^ #decimals
            numerator = tonumber(whole) * denominator + (tonumber(decimals) or 0)
        else
            numerator, denominator = tonumber(text:match('^%s*(%d+)%s*$')), 1
        end
    end
    if not numerator or denominator <= 0 or numerator <= denominator or numerator > denominator * 10
        or numerator > 100000000 or denominator > 100000000 then
        return
    end
    local a, b = numerator, denominator
    while b ~= 0 do a, b = b, a % b end
    numerator, denominator = numerator / a, denominator / a
    if denominator > 100 then return end
    if denominator == 1 then return string.format('%d', numerator) end
    return string.format('%d/%d', numerator, denominator)
end

local function load_multiplier()
    if not multiplier_path or multiplier_path:sub(1, 1) ~= '/' then return end
    local file = io.open(multiplier_path, 'rb')
    if not file then return end
    local text = file:read(128)
    local extra = file:read(1)
    file:close()
    local value = not extra and normalize_multiplier(text)
    if not value then msg.warn('Ignoring an invalid saved interpolation multiplier') end
    return value
end

local preferred_multiplier = load_multiplier()
local multiplier = preferred_multiplier or '2'

local function set_multiplier_state(value)
    multiplier = value
    mp.set_property_native('user-data/bluray-vs/multiplier', value)
end

local function multiplier_text()
    local decimal_labels = {['3/2'] = '1.5', ['5/2'] = '2.5'}
    return (decimal_labels[multiplier] or multiplier) .. '×'
end

local function active_preset(filters)
    for _, filter in ipairs(filters) do
        if filter.label == filter_label and filter.enabled ~= false and filter.params then
            for name, file in pairs(preset_files) do
                if filter.params.file == file then return name, filter end
            end
        end
    end
end

local function set_filters(updated)
    local ok, err = mp.set_property_native('vf', updated)
    if not ok then
        msg.error('Could not update VapourSynth preset: ' .. tostring(err))
        mp.osd_message(options.language == 'zh' and 'VapourSynth 预设切换失败' or 'Could not switch VapourSynth preset')
    end
    return ok
end

local function apply_multiplier(filters, filter, value)
    if normalize_multiplier(filter.params['user-data'] or '2') == value then return true end
    filter.params['user-data'] = value
    return set_filters(filters)
end

set_multiplier_state(multiplier)
mp.observe_property('vf', 'native', function(_, filters)
    local name, filter = active_preset(filters or {})
    if interpolates[name] then
        local value = normalize_multiplier(filter.params['user-data'] or '2')
        -- A managed filter may have been restored with an older rate by watch-later.
        if preferred_multiplier and value ~= preferred_multiplier
            and apply_multiplier(filters, filter, preferred_multiplier) then
            value = preferred_multiplier
        end
        if value then set_multiplier_state(value) end
    elseif preferred_multiplier then
        set_multiplier_state(preferred_multiplier)
    end
    mp.set_property('user-data/bluray-vs/active', name or '')
end)

local function set_multiplier(text)
    local value = normalize_multiplier(text)
    if not value then
        mp.osd_message(options.language == 'zh' and '请输入大于 1 且不超过 10 的倍率，约分后分母不超过 100'
            or 'Enter a multiplier above 1 and at most 10, with a reduced denominator of at most 100')
        return
    end
    local filters = mp.get_property_native('vf', {})
    local name, filter = active_preset(filters)
    if interpolates[name] and not apply_multiplier(filters, filter, value) then return end
    preferred_multiplier = value
    set_multiplier_state(value)
    local saved, err = pcall(write_atomic, multiplier_path, value .. '\n')
    local title = (options.language == 'zh' and '补帧倍率 ' or 'Interpolation multiplier ') .. multiplier_text()
    if saved then
        mp.osd_message(title .. (options.language == 'zh' and ' 已保存' or ' saved'))
    else
        msg.error(err)
        mp.osd_message(title .. (options.language == 'zh' and ' 已应用，自动保存失败' or ' applied, but could not be saved'))
    end
end

local function toggle(name)
    local filters = mp.get_property_native('vf', {})
    local active = active_preset(filters)
    local replacement
    if name and name ~= active then
        local file = preset_files[name]
        local info = file and utils.file_info(file)
        if not info or not info.is_file then
            msg.error('VapourSynth preset is missing: ' .. name)
            mp.osd_message(options.language == 'zh' and '找不到 VapourSynth 预设' or 'VapourSynth preset is missing')
            return
        end
        replacement = {
            name = 'vapoursynth', label = filter_label, enabled = true,
            params = {file = file, ['concurrent-frames'] = name == 'bm3d' and '8' or '4'},
        }
        if interpolates[name] then replacement.params['user-data'] = preferred_multiplier or multiplier end
    end

    local updated = {}
    local replaced = false
    for _, filter in ipairs(filters) do
        if filter.label ~= filter_label then
            updated[#updated + 1] = filter
        elseif replacement and not replaced then
            updated[#updated + 1] = replacement
            replaced = true
        end
    end
    if replacement and not replaced then
        updated[#updated + 1] = replacement
    end
    if not set_filters(updated) then return end
    if replacement then
        local title = preset_names[name] .. (interpolates[name] and ' ' .. multiplier_text() or '')
        mp.osd_message(title .. (options.language == 'zh' and ' 已开启' or ' enabled'))
    else
        mp.osd_message(options.language == 'zh' and '已关闭 VapourSynth 预设' or 'VapourSynth preset disabled')
    end
end

mp.register_script_message('toggle', toggle)
mp.register_script_message('off', function() toggle(nil) end)
mp.register_script_message('multiplier', set_multiplier)
mp.register_script_message('custom-multiplier', function()
    require('mp.input').get({
        prompt = options.language == 'zh' and '补帧倍率，例如 2.5 或 5/2' or 'Interpolation multiplier, e.g. 2.5 or 5/2',
        default_text = multiplier,
        submit = set_multiplier,
    })
end)
