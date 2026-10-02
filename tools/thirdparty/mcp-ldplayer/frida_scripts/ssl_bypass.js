// SSL Pinning Bypass - Universal
// Bypasses: TrustManager, OkHttp3, HttpsURLConnection, WebView, Conscrypt
Java.perform(function() {
    // TrustManager bypass
    var TrustManagerImpl = Java.use('com.android.org.conscrypt.TrustManagerImpl');
    TrustManagerImpl.verifyChain.implementation = function(untrustedChain, trustAnchorChain, host, clientAuth, ocspData, tlsSctData) {
        return untrustedChain;
    };

    // OkHttp3 CertificatePinner
    try {
        var CertificatePinner = Java.use('okhttp3.CertificatePinner');
        CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function(hostname, peerCertificates) {
            return;
        };
    } catch(e) {}

    // HttpsURLConnection
    try {
        var HttpsURLConnection = Java.use('javax.net.ssl.HttpsURLConnection');
        HttpsURLConnection.setDefaultHostnameVerifier.implementation = function(hostnameVerifier) {
            return;
        };
    } catch(e) {}

    // WebView SSL errors
    try {
        var WebViewClient = Java.use('android.webkit.WebViewClient');
        WebViewClient.onReceivedSslError.implementation = function(view, handler, error) {
            handler.proceed();
        };
    } catch(e) {}

    // Retrofit / Conscrypt
    try {
        var PlatformImpl = Java.use('com.android.org.conscrypt.Platform');
        PlatformImpl.checkServerTrusted.overload('javax.net.ssl.X509TrustManager', '[Ljava.security.cert.X509Certificate;', 'java.lang.String', 'com.android.org.conscrypt.AbstractConscryptSocket').implementation = function(tm, chain, authType, socket) {
            return;
        };
    } catch(e) {}

    console.log('[+] SSL Pinning bypass loaded');
});
