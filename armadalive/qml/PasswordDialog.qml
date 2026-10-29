import QtQuick

// Asks for the user's password for one root step. The password only ever goes to sudo (see admin.py).
Item {
    id: d
    property string action
    signal accepted(string password)
    signal cancelled()

    onVisibleChanged: if (visible) { field.text = ""; field.forceActiveFocus() }

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
}
