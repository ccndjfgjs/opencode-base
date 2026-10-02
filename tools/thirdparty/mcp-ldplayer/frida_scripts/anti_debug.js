// Anti-Debug Bypass
Java.perform(function() {
    var Debug = Java.use('android.os.Debug');
    Debug.isDebuggerConnected.implementation = function() {
        console.log('[+] isDebuggerConnected bypassed');
        return false;
    };

    var BufferedReader = Java.use('java.io.BufferedReader');
    BufferedReader.readLine.implementation = function() {
        var line = this.readLine();
        if (line && line.indexOf('TracerPid') !== -1) {
            console.log('[+] TracerPid check bypassed');
            return 'TracerPid:\t0';
        }
        return line;
    };

    console.log('[+] Anti-Debug bypass loaded');
});
