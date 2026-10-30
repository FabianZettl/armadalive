import QtQuick

// Asks for the user's password for one root step. The password only ever goes to sudo (see admin.py).
Item {
    id: d
    property string action
    signal accepted(string password)
    signal cancelled()

    // An own on-screen keyboard: keys from a Bluetooth or system keyboard go to the session on the top screen, never to this one.
    property bool shift: false
    property bool symbols: false
    readonly property var letters: [["q","w","e","r","t","y","u","i","o","p"], ["a","s","d","f","g","h","j","k","l"], ["z","x","c","v","b","n","m"]]
    readonly property var marks: [["1","2","3","4","5","6","7","8","9","0"], ["@","#","$","%","&","*","-","+","=","_"], ["!","?",".",",",":",";","/","\\","(",")"]]
    readonly property var rows: symbols ? marks : [["1","2","3","4","5","6","7","8","9","0"]].concat(letters)
    function press(ch) {
        field.text += shift && !symbols ? ch.toUpperCase() : ch
        if (shift) shift = false
    }
    onVisibleChanged: if (visible) { field.text = ""; shift = false; symbols = false }

    Rectangle { anchors.fill: parent; color: "#000000"; opacity: 0.7 }
    MouseArea { anchors.fill: parent }          // modal: nothing behind it reacts

    Rectangle {
        // in the upper part of the screen, so the on-screen keyboard does not cover it
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: parent.height * 0.12 }
        width: Math.min(parent.width - 40, 520)
        height: col.height + 36
        radius: Theme.radius
        color: Theme.card
        border.color: Theme.border

        Column {
            id: col
            x: 18; y: 18
            width: parent.width - 36
            spacing: 12
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                color: Theme.text
                font.pixelSize: 17
                font.weight: Font.Medium
                text: d.action === "helper" ? Tr.t("Install the root helper") : Tr.t("Route the AYN button to ArmadaLive")
            }
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                color: Theme.muted
                font.pixelSize: 14
                text: Tr.t("Enter your password to confirm. It is passed to sudo and not stored.")
            }
            Rectangle {
                width: parent.width; height: 46; radius: 10
                color: Theme.circle
                border.color: field.activeFocus ? Theme.accent : Theme.border
                TextInput {
                    id: field
                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                    verticalAlignment: TextInput.AlignVCenter
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                    color: Theme.text
                    font.pixelSize: 18
                    clip: true
                    readOnly: true      // keeps the system keyboard away (this dialog has its own); text is set by the keys below
                    cursorVisible: true
                    onAccepted: if (text !== "") d.accepted(text)
                }
            }
            Row {
                spacing: 10
                PillButton { label: Tr.t("Cancel"); onClicked: d.cancelled() }
                PillButton { label: Tr.t("Confirm"); primary: true; enabled: field.text !== ""; onClicked: d.accepted(field.text) }
            }
        }
    }

    Rectangle {
        id: kb
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: Math.min(272, parent.height * 0.5)
        color: Theme.bg
        readonly property real kh: (height - 6 * 6) / 5
        Column {
            anchors { fill: parent; margins: 6 }
            spacing: 6
            Repeater {
                model: d.rows
                delegate: Row {
                    id: kr
                    readonly property int cols: 10
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 6
                    Repeater {
                        model: modelData
                        delegate: Rectangle {
                            width: (kb.width - 12 - 9 * 6) / 10
                            height: kb.kh
                            radius: 8
                            color: kt.pressed ? Theme.accent : Theme.circle
                            Text { anchors.centerIn: parent; color: kt.pressed ? Theme.bg : Theme.text; font.pixelSize: kb.kh * 0.5; text: d.shift && !d.symbols ? modelData.toUpperCase() : modelData }
                            MouseArea { id: kt; anchors.fill: parent; onClicked: d.press(modelData) }
                        }
                    }
                }
            }
            Row {
                spacing: 6
                anchors.horizontalCenter: parent.horizontalCenter
                Rectangle {
                    width: (kb.width - 12 - 6 * 6) / 7 * 1.5; height: kb.kh; radius: 8
                    color: d.shift ? Theme.accent : Theme.circle
                    Text { anchors.centerIn: parent; color: d.shift ? Theme.bg : Theme.text; font.pixelSize: kb.kh * 0.5; text: "⇧" }
                    MouseArea { anchors.fill: parent; enabled: !d.symbols; onClicked: d.shift = !d.shift }
                }
                Rectangle {
                    width: (kb.width - 12 - 6 * 6) / 7 * 1.5; height: kb.kh; radius: 8
                    color: d.symbols ? Theme.accent : Theme.circle
                    Text { anchors.centerIn: parent; color: d.symbols ? Theme.bg : Theme.text; font.pixelSize: kb.kh * 0.4; text: d.symbols ? "abc" : "?123" }
                    MouseArea { anchors.fill: parent; onClicked: { d.symbols = !d.symbols; d.shift = false } }
                }
                Rectangle {
                    width: (kb.width - 12 - 6 * 6) / 7 * 2.5; height: kb.kh; radius: 8
                    color: sp.pressed ? Theme.accent : Theme.circle
                    MouseArea { id: sp; anchors.fill: parent; onClicked: d.press(" ") }
                }
                Rectangle {
                    width: (kb.width - 12 - 6 * 6) / 7 * 1.5; height: kb.kh; radius: 8
                    color: bs.pressed ? Theme.accent : Theme.circle
                    Text { anchors.centerIn: parent; color: bs.pressed ? Theme.bg : Theme.text; font.pixelSize: kb.kh * 0.5; text: "⌫" }
                    MouseArea { id: bs; anchors.fill: parent; onClicked: field.text = field.text.slice(0, -1) }
                }
            }
        }
    }
}
