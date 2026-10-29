pragma Singleton
import QtQuick

// A page asks for a root step by setting `ask` to "helper" or "ayn"; the window shows the password dialog.
QtObject {
    property string ask: ""
}
