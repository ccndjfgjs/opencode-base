// Root Detection Bypass - Universal
// Bypasses: File.exists, Runtime.exec, Build.TAGS, SystemProperties
Java.perform(function() {
    var File = Java.use('java.io.File');
    var rootPaths = ['/system/bin/su', '/system/xbin/su', '/sbin/su', '/data/local/su',
                     '/system/app/Superuser.apk', '/system/app/SuperSU.apk',
                     '/data/local/bin/su', '/data/local/xbin/su',
                     '/system/sd/xbin/su', '/system/bin/failsafe/su'];

    File.exists.implementation = function() {
        var path = this.getAbsolutePath();
        for (var i = 0; i < rootPaths.length; i++) {
            if (path === rootPaths[i]) {
                console.log('[+] Root check blocked: ' + path);
                return false;
            }
        }
        return this.exists();
    };

    var Runtime = Java.use('java.lang.Runtime');
    Runtime.exec.overload('[Ljava.lang.String;').implementation = function(cmd) {
        var blocked = ['su', 'which su', 'busybox'];
        for (var i = 0; i < blocked.length; i++) {
            if (cmd[0].indexOf(blocked[i]) !== -1) {
                console.log('[+] Root exec blocked: ' + cmd[0]);
                throw Java.use('java.io.IOException').$new('Permission denied');
            }
        }
        return this.exec(cmd);
    };

    var Build = Java.use('android.os.Build');
    Build.TAGS.value = 'release-keys';

    try {
        var SystemProperties = Java.use('android.os.SystemProperties');
        SystemProperties.get.overload('java.lang.String').implementation = function(key) {
            if (key === 'ro.build.tags') return 'release-keys';
            if (key === 'ro.debuggable') return '0';
            if (key === 'ro.secure') return '1';
            return this.get(key);
        };
    } catch(e) {}

    console.log('[+] Root detection bypass loaded');
});
