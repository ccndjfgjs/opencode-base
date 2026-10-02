// Network Hook - Monitor all HTTP/HTTPS requests
Java.perform(function() {
    // OkHttp3 Interceptor
    try {
        var RealCall = Java.use('okhttp3.RealCall');
        RealCall.execute.implementation = function() {
            var req = this.request();
            console.log('[NET] ' + req.method() + ' ' + req.url().toString());
            var headers = req.headers();
            for (var i = 0; i < headers.size(); i++) {
                console.log('[NET]   ' + headers.name(i) + ': ' + headers.value(i));
            }
            var resp = this.execute();
            console.log('[NET] Response: ' + resp.code());
            return resp;
        };
    } catch(e) {}

    // HttpURLConnection
    try {
        var URL = Java.use('java.net.URL');
        URL.openConnection.overload().implementation = function() {
            console.log('[NET] URL.openConnection: ' + this.toString());
            return this.openConnection();
        };
    } catch(e) {}

    console.log('[+] Network hooks loaded');
});
