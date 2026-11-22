// JXA exposes the system frameworks on Big Sur and later without a separate runtime.
ObjC.import("CoreServices");
ObjC.bindFunction("renamex_np", ["int", ["char *", "char *", "unsigned int"]]);

function run(args) {
    if (args.length === 2 && args[0] === "register") {
        const status = $.LSRegisterURL($.NSURL.fileURLWithPath(args[1]), true);
        if (status !== 0) throw Error("Launch Services error " + status);
    } else if (args.length === 3 && args[0] === "exchange") {
        // RENAME_SWAP exchanges both directories in one filesystem transaction.
        if ($.renamex_np(args[1], args[2], 2) !== 0) throw Error("Cannot exchange the application bundles");
    } else if (args.length === 3 && args[0] === "place") {
        // FileManager preserves an existing destination on local and shared volumes.
        const error = Ref();
        if (!$.NSFileManager.defaultManager.moveItemAtPathToPathError(args[1], args[2], error))
            throw Error(ObjC.unwrap(error[0].localizedDescription));
    } else {
        throw Error("Invalid application file operation");
    }
}
