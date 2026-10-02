// Input Monitor - Capture all text input events
Java.perform(function() {
    var EditText = Java.use('android.widget.EditText');

    EditText.setText.overload('java.lang.CharSequence').implementation = function(text) {
        if (text && text.toString().length > 0) {
            console.log('[INPUT] EditText.setText: ' + text.toString());
        }
        return this.setText(text);
    };

    EditText.append.overload('java.lang.CharSequence').implementation = function(text) {
        if (text && text.toString().length > 0) {
            console.log('[INPUT] EditText.append: ' + text.toString());
        }
        return this.append(text);
    };

    console.log('[+] Input monitor loaded');
});
