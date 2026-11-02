"""The bottom screen as a Steam Deck's trackpads and back buttons: a virtual mouse, a virtual pad for L4 L5 R4 R5, and the
haptic motor for the click. Writes to /dev/uinput and the haptics node, both open to the `input` group, so it needs no setup.

shortcut: the back buttons are a second controller to Steam (InputPlumber's own one has no input for them, and its D-Bus
SendEvent crashes in 0.83); map them in Steam Input. A merged button needs an InputPlumber device file (root)."""
import fcntl, os, re, struct
import time
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

EVENT = struct.Struct("@llHHi")   # struct input_event on 64-bit: time, type, code, value
EV_SYN, EV_KEY, EV_REL, EV_ABS, EV_FF = 0, 1, 2, 3, 0x15
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0, 1, 6, 8
BTN_LEFT, BTN_RIGHT, BTN_SOUTH, BTN_TRIGGER_HAPPY1 = 0x110, 0x111, 0x130, 0x2C0
ABS_X, ABS_Y = 0, 1
FF_RUMBLE, FF_CONSTANT, FF_GAIN = 0x50, 0x52, 0x60
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045566, 0x40045567
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
EVIOCSFF = 0x40304580   # _IOW('E', 0x80, struct ff_effect), 48 bytes
EVIOCRMFF = 0x40044581  # _IOW('E', 0x81, int)
SENSITIVITY = 1.8
BACK = ("L4", "L5", "R4", "R5")
KEYS = {"esc": 1, "tab": 15, "enter": 28, "space": 57, "backspace": 14, "up": 103, "left": 105, "right": 106, "down": 108, "f11": 87}
FRICTION, STOP_SPEED, GLIDE_TICK = 0.93, 40.0, 45     # per 16 ms frame; px/s below which a glide ends; px between ticks


class Virtual:
    """One uinput device. Created on first use, gone with the app."""
    def __init__(self, name, keys=(), rels=(), abs_=()):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            for ev, bit, codes in ((EV_KEY, UI_SET_KEYBIT, keys), (EV_REL, UI_SET_RELBIT, rels), (EV_ABS, UI_SET_ABSBIT, abs_)):
                if codes:
                    fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
                    for code in codes:
                        fcntl.ioctl(self.fd, bit, code)
            absmax = [0] * 64
            absmin = [0] * 64
            for code in abs_:
                absmax[code], absmin[code] = 32767, -32767
            # struct uinput_user_dev: name, input_id (bus 6 = virtual), ff_effects_max, then four arrays of 64
            os.write(self.fd, struct.pack("80s4HI", name.encode(), 6, 0x1209, 0xA11, 1, 0)
                     + struct.pack("64i", *absmax) + struct.pack("64i", *absmin) + bytes(2 * 64 * 4))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def emit(self, kind, code, value):
        os.write(self.fd, EVENT.pack(0, 0, kind, code, value))

    def sync(self):
        self.emit(EV_SYN, 0, 0)


def rumble_effect(strong, length_ms):
    """struct ff_effect for a plain rumble, the id left to the kernel (-1)."""
    head = struct.pack("<HhHHHHH", FF_RUMBLE, -1, 0, 0, 0, length_ms, 0) + bytes(2)   # type id direction trigger replay, pad
    return bytearray(head + struct.pack("<HH", strong, 0) + bytes(28))


def constant_effect(length_ms, fade_ms=0, level=0x6000):
    """struct ff_effect for a constant force; a fade at the end keeps the motor from stopping with a knock. The driver takes this and rumble, not periodic waves."""
    head = struct.pack("<HhHHHHH", FF_CONSTANT, -1, 0, 0, 0, length_ms, 0) + bytes(2)
    return bytearray(head + struct.pack("<hHHHH", level, 0, 0x7FFF, fade_ms, 0) + bytes(22))


def node_named(pattern):
    """The /dev/input node of the first device whose name matches, or ''."""
    try:
        text = open("/proc/bus/input/devices").read()
    except OSError:
        return ""
    for block in text.split("\n\n"):
        name, node = re.search(r'Name="([^"]*)"', block), re.search(r"\b(event\d+)\b", block)
        if name and node and re.search(pattern, name.group(1), re.I):
            return "/dev/input/" + node.group(1)
    return ""


def haptics_node():
    return node_named("haptics")


class Motor:
    """One force-feedback device with room for one effect of ours at a time, opened when needed and given back after."""
    def __init__(self, pattern, make):
        self.pattern, self.make = pattern, make
        self.fd, self.effect = -1, -1

    def play(self, length_ms, fade_ms):
        if self.fd < 0:
            node = node_named(self.pattern)
            if not node:
                return
            self.fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
            os.write(self.fd, EVENT.pack(0, 0, EV_FF, FF_GAIN, 0xFFFF))
        buf = self.make(length_ms, fade_ms)
        struct.pack_into("<h", buf, 2, self.effect)
        fcntl.ioctl(self.fd, EVIOCSFF, buf, True)
        self.effect = struct.unpack_from("<h", buf, 2)[0]    # the kernel wrote the id back
        if self.effect >= 0:
            os.write(self.fd, EVENT.pack(0, 0, EV_FF, self.effect, 1))

    def free(self):
        if self.fd >= 0:
            try:
                fcntl.ioctl(self.fd, EVIOCRMFF, self.effect)
            except OSError:
                pass
            os.close(self.fd)
        self.fd, self.effect = -1, -1


class Trackpad(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._mouse = self._back = self._keys = None
        self._last = 0.0
        self._trackball, self._glide = True, None
        self._frame = QTimer(self)
        self._frame.setInterval(16)
        self._frame.timeout.connect(self._step)
        # the Thor's own haptic motor; the rumble motors of the grips (through InputPlumber's virtual controller) were hardly felt
        self._motors = (Motor("haptics", lambda ms, fade: constant_effect(ms, fade)),)
        self._release = QTimer(self)    # the motor has room for one effect: give it back when nobody is touching
        self._release.setSingleShot(True)
        self._release.setInterval(1500)
        self._release.timeout.connect(self._free)
        self._carry = [0.0, 0.0]
        self._error = ""

    @Property(bool, notify=changed)
    def trackball(self):
        return self._trackball

    @Slot(bool)
    def setTrackball(self, on):
        self._trackball = on
        self._stop()
        self.changed.emit()

    @Property(str, notify=changed)
    def error(self):
        return self._error

    def _device(self, which):
        try:
            if which == "mouse" and not self._mouse:
                self._mouse = Virtual("ArmadaLive Trackpad", keys=(BTN_LEFT, BTN_RIGHT), rels=(REL_X, REL_Y, REL_WHEEL, REL_HWHEEL))
            if which == "keys" and not self._keys:
                self._keys = Virtual("ArmadaLive Keys", keys=tuple(KEYS.values()))
            if which == "back" and not self._back:   # a gamepad button and two axes so that udev and SDL take it for a pad
                self._back = Virtual("ArmadaLive Back Buttons", keys=(BTN_SOUTH,) + tuple(BTN_TRIGGER_HAPPY1 + i for i in range(4)),
                                     abs_=(ABS_X, ABS_Y))
        except OSError as e:
            self._error = f"/dev/uinput: {e.strerror}"
            self.changed.emit()
        return {"mouse": self._mouse, "back": self._back, "keys": self._keys}[which]

    @Slot(float, float)
    def move(self, dx, dy):
        dev = self._device("mouse")
        if not dev:
            return
        out = []
        for i, d in enumerate((dx, dy)):
            self._carry[i] += d * SENSITIVITY
            whole = int(self._carry[i])    # the pointer moves in whole steps, the rest waits for the next touch event
            self._carry[i] -= whole
            out.append(whole)
        try:
            for code, v in ((REL_X, out[0]), (REL_Y, out[1])):
                if v:
                    dev.emit(EV_REL, code, v)
            dev.sync()
        except OSError:
            pass

    @Slot(float)
    def scroll(self, dy):
        dev = self._device("mouse")
        if dev:
            try:
                dev.emit(EV_REL, REL_WHEEL, -1 if dy > 0 else 1)
                dev.sync()
            except OSError:
                pass

    @Slot(str, bool)
    def button(self, which, down):
        """'left' or 'right' mouse button, or one of L4 L5 R4 R5."""
        if which in BACK:
            dev, code = self._device("back"), BTN_TRIGGER_HAPPY1 + BACK.index(which)
        elif which in ("left", "right"):
            dev, code = self._device("mouse"), BTN_LEFT if which == "left" else BTN_RIGHT
        else:
            return
        if dev:
            try:
                dev.emit(EV_KEY, code, int(down))
                dev.sync()
            except OSError:
                pass

    @Slot(str)
    def press(self, name):
        """A tap of a keyboard key: Esc, Tab, Enter, Space, Backspace, the arrows, F11."""
        dev, code = self._device("keys"), KEYS.get(name)
        if dev and code:
            try:
                dev.emit(EV_KEY, code, 1)
                dev.sync()
                dev.emit(EV_KEY, code, 0)
                dev.sync()
            except OSError:
                pass

    @Slot(float, float)
    def fling(self, vx, vy):
        """Let the pointer glide on after a flick, slowing down like a trackball (px/s in)."""
        if self._trackball and (vx * vx + vy * vy) ** 0.5 > 250:
            self._glide, self._since = [vx, vy], 0.0
            self._frame.start()

    @Slot()
    def stopGlide(self):
        self._stop()

    def _stop(self):
        self._frame.stop()
        self._glide = None

    def _step(self):
        vx, vy = self._glide or (0, 0)
        speed = (vx * vx + vy * vy) ** 0.5
        if speed < STOP_SPEED:
            self._stop()
            return
        self.move(vx * 0.016, vy * 0.016)
        self._since += speed * 0.016
        if self._since > GLIDE_TICK:        # the friction of the ball, felt as ticks that come further apart as it slows
            self._since = 0.0
            self.nudge()
        self._glide = [vx * FRICTION, vy * FRICTION]

    def _free(self):
        for motor in self._motors:
            motor.free()

    def _buzz(self, length_ms, fade_ms=0, gap=0.0):
        """Play on every motor that takes it; each fails on its own."""
        now = time.monotonic()
        if now - self._last < gap:
            return
        self._last = now
        for motor in self._motors:
            try:
                motor.play(length_ms, fade_ms)
            except OSError:
                pass
        self._release.start()

    @Slot()
    def tick(self):
        """A click under the finger: a tap, a button."""
        self._buzz(40, 12)

    @Slot()
    def nudge(self):
        """A light tick for every step of a scroll or drag; not more than 25 a second."""
        self._buzz(12, 5, gap=0.025)
