local mp = require('mp')

return function(path, content)
    assert(path and path:sub(1, 1) == '/', 'mpv has no user configuration directory')
    local temp = mp.command_native({
        name = 'subprocess', args = {'mktemp', '--', path .. '.XXXXXX'},
        capture_stdout = true, playback_only = false,
    })
    assert(temp and temp.status == 0, 'Could not create a temporary settings file')
    local temporary = temp.stdout:gsub('\n$', '')
    local file, err = io.open(temporary, 'wb')
    if file then
        local written, write_error = file:write(content)
        local closed, close_error = file:close()
        if written and closed then
            local renamed
            renamed, err = os.rename(temporary, path)
            if renamed then return end
        else
            err = write_error or close_error
        end
    end
    os.remove(temporary)
    error(err or 'Could not write the settings file')
end
