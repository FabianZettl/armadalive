pragma Singleton
import QtQuick

// Shared lock: while a slider, the curve editor or the quick-setting pages are being dragged, swiping must not change the page.
QtObject {
    id: g
    property bool locked: false

    // call with the pressed state; returns true when the press has just ended, so it can stand in for `!pressed`
    function hold(pressed) {
        if (pressed) { locked = true; release.stop() }
        else release.restart()      // stay locked a moment after letting go: the page handler reads the gesture at that point
        return !pressed
    }
    property Timer release: Timer { interval: 400; onTriggered: g.locked = false }
}
