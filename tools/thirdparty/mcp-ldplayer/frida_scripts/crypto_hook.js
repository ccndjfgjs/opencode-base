// Crypto Hook - Intercept encryption/decryption + SharedPreferences
Java.perform(function() {
    var Cipher = Java.use('javax.crypto.Cipher');

    Cipher.doFinal.overload('[B').implementation = function(data) {
        var mode = this.getOpMode();
        var algo = this.getAlgorithm();
        console.log('[CRYPTO] Algorithm: ' + algo + ' Mode: ' + (mode === 1 ? 'ENCRYPT' : 'DECRYPT'));
        console.log('[CRYPTO] Data (hex): ' + bytesToHex(data));
        var result = this.doFinal(data);
        console.log('[CRYPTO] Result (hex): ' + bytesToHex(result));
        return result;
    };

    function bytesToHex(bytes) {
        var hex = [];
        for (var i = 0; i < bytes.length; i++) {
            hex.push(('0' + (bytes[i] & 0xFF).toString(16)).slice(-2));
        }
        return hex.join('');
    }

    var SharedPreferencesImpl = Java.use('android.app.SharedPreferencesImpl');
    SharedPreferencesImpl.getString.implementation = function(key, defValue) {
        var value = this.getString(key, defValue);
        console.log('[PREFS] getString("' + key + '") = "' + value + '"');
        return value;
    };

    console.log('[+] Crypto & SharedPrefs hooks loaded');
});
