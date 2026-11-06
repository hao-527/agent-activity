import AppKit
import CoreText
import Darwin

/// One live Claude Code CLI session, as published by Claude Code itself in
/// `~/.claude/sessions/<pid>.json`. The registry is authoritative: a session
/// exists precisely as long as its process does.
struct Session {
    let pid: Int32
    let sessionId: String
    let cwd: String
    let name: String
    let status: String
    let updatedAt: Double // milliseconds since epoch

    /// Accepted registry statuses: busy, shell, idle, waiting.
    var working: Bool { status == "busy" || status == "shell" }
    var waiting: Bool { status == "waiting" }

    /// A conversation is underway when Claude is working or waiting on you. An
    /// idle session is alive but not talking, so it must not light the icon.
    var conversing: Bool { working || waiting }

    var folder: String {
        let tail = (cwd as NSString).lastPathComponent
        return tail.isEmpty ? cwd : tail
    }

    var title: String {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if !clean.isEmpty { return clean }
        return folder.isEmpty ? "会话 " + String(sessionId.prefix(8)) : folder
    }

    var age: TimeInterval {
        max(0, (Date().timeIntervalSince1970 * 1000 - updatedAt) / 1000)
    }
}

enum Registry {
    /// Claude Code's config directory: `$CLAUDE_CONFIG_DIR` when set, otherwise
    /// `~/.claude`. NSHomeDirectory() is read from the user record, not `$HOME`,
    /// so the environment variable is the only way to redirect this.
    static var root: URL {
        let override = ProcessInfo.processInfo.environment["CLAUDE_CONFIG_DIR"]?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !override.isEmpty {
            return URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
                .appendingPathComponent("sessions")
        }
        return URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent(".claude/sessions")
    }

    static func alive(_ pid: Int32) -> Bool {
        guard pid > 1 else { return false }
        if kill(pid, 0) == 0 { return true }
        return errno == EPERM // owned by another user, still running
    }

    /// Reads every `<pid>.json`, keeping only sessions whose process is alive.
    /// `readable` is false when the directory itself cannot be listed.
    static func snapshot() -> (sessions: [Session], readable: Bool) {
        guard let files = try? FileManager.default.contentsOfDirectory(atPath: root.path) else {
            return ([], false)
        }
        var found: [Session] = []
        for file in files where file.hasSuffix(".json") && !file.hasPrefix(".") {
            let stem = String(file.dropLast(5))
            guard let pid = Int32(stem) else { continue } // skips sibling *.key files
            let url = root.appendingPathComponent(file)
            guard let data = try? Data(contentsOf: url),
                  let decoded = try? JSONSerialization.jsonObject(with: data),
                  let raw = decoded as? [String: Any] else { continue }
            let recorded = (raw["pid"] as? NSNumber)?.int32Value ?? pid
            guard alive(recorded) else { continue }
            found.append(Session(
                pid: recorded,
                sessionId: raw["sessionId"] as? String ?? stem,
                cwd: raw["cwd"] as? String ?? "?",
                name: raw["name"] as? String ?? "",
                status: raw["status"] as? String ?? "idle",
                updatedAt: (raw["updatedAt"] as? NSNumber)?.doubleValue ?? 0
            ))
        }
        found.sort { $0.updatedAt > $1.updatedAt }
        return (found, true)
    }
}

struct Summary {
    /// Menu-bar text: how many sessions are talking right now. Empty when nothing
    /// is talking, so an idle bar carries only the icon. Idle sessions are alive,
    /// not talking, and must not be counted here — a session left open for hours
    /// would otherwise inflate it.
    let title: String
    /// Longer line for the tooltip and the top of the menu. Carries the total
    /// session count, which the bar deliberately does not show.
    let detail: String
    let color: NSColor
    let talking: Int
}

/// Two states, by the user's design: purple is everyday, green means a
/// conversation is in flight. Waiting still counts as in flight — you are at the
/// keyboard, just not typing. Read faults get their own orange.
///
/// The number counts *talking* sessions, not live ones. A session left open and
/// idle for hours is still alive, but it has no work in flight, and counting it
/// would make the bar show a number for a Mac sitting untouched.
func summarize(_ sessions: [Session], readable: Bool) -> Summary {
    guard readable else {
        return Summary(title: "", detail: "无法读取 Claude Code 会话注册表",
                       color: .systemOrange, talking: 0)
    }
    let total = sessions.count
    guard total > 0 else {
        return Summary(title: "", detail: "Claude 空闲 · 没有正在运行的会话",
                       color: .systemPurple, talking: 0)
    }
    let talking = sessions.filter(\.conversing).count
    guard talking > 0 else {
        return Summary(title: "", detail: "\(total) 个会话 · 全部空闲",
                       color: .systemPurple, talking: 0)
    }
    let waiting = sessions.filter(\.waiting).count
    let note = waiting > 0 ? "（\(waiting) 个等待你确认）" : ""
    let scope = talking == total ? "" : "（共 \(total) 个会话）"
    return Summary(title: "\(talking)", detail: "\(talking) 个正在对话\(note)\(scope)",
                   color: .systemGreen, talking: talking)
}

/// The mark drawn in the menu bar.
///
/// `cc` is the mark in use: the two letters, in the weight and colour the system
/// already uses for menu-bar text, so the icon reads as part of the bar instead
/// of as a picture dropped into it. `burst` is the earlier eight-ray mark, kept
/// only so `--mark burst` can render it side by side for comparison.
enum Mark: String {
    case cc
    case burst
}

/// Chosen at launch with `--mark <name>`; defaults to `cc`.
let activeMark: Mark = {
    let args = CommandLine.arguments
    guard let flag = args.firstIndex(of: "--mark"), flag + 1 < args.count,
          let chosen = Mark(rawValue: args[flag + 1]) else { return .cc }
    return chosen
}()

/// Compact icon canvas; the light occupies the right-hand side without clipping.
let canvas = NSSize(width: 23.5, height: 22)
/// Vertical midline of the canvas. The letters are centred on it: an item whose
/// ink is centred sits level with its neighbours in the bar.
let midline: CGFloat = 11

/// The activity light keeps its 6×6 core, 8×8 background-coloured disc and 9×9
/// pulse. The group moves left only enough to tighten the canvas while keeping the
/// pulsing halo clear of the letters.
let lightCoreDiameter: CGFloat = 6
let lightHaloDiameter: CGFloat = 8
let lightPulseHaloDiameter: CGFloat = 9
let lightCenterX: CGFloat = 20.4
let lightCenterY: CGFloat = 5

/// Draws one whole icon: mark first, light on top.
func drawMark(style: Mark, light: NSColor, pulsing: Bool) {
    switch style {
    case .cc: drawLetters()
    case .burst: drawBurst()
    }
    drawLight(light, pulsing: pulsing)
}

/// "CC", set the way the bar would set it.
///
/// Positioned from the glyph outlines rather than from the font's line metrics.
/// "CC" has no descenders, so a line box centred on the midline leaves the ink
/// visibly high; centring the outline box is exact and needs no fudge constant.
func drawLetters() {
    // The mark owns x 0.5…15.5; the light begins beyond its right edge.
    let box = NSRect(x: 0.5, y: 0, width: 15, height: 22)

    func line(_ size: CGFloat) -> CTLine {
        let base = NSFont.systemFont(ofSize: size, weight: .bold)
        // Rounded reads softer than the default cut at this size, and its "C"
        // stays open instead of closing into a ring at 1× — the whole risk with a
        // letter mark this small.
        let font = base.fontDescriptor.withDesign(.rounded)
            .flatMap { NSFont(descriptor: $0, size: size) } ?? base
        let text = NSAttributedString(string: "CC", attributes: [
            .font: font,
            .foregroundColor: NSColor.labelColor,
            // The default tracking at this size leaves a gap wide enough to read
            // as two separate words; a little tighter and the "C" bowls nearly
            // merge. -0.6 is the gap that still reads as two letters but as one
            // mark. Measured at 1× and 2×, not guessed.
            .kern: -0.6,
        ])
        return CTLineCreateWithAttributedString(text)
    }

    func inkBox(_ line: CTLine) -> CGRect {
        CTLineGetBoundsWithOptions(line, .useGlyphPathBounds)
    }

    // Fit to the box: shrink only if the pair would overlap the light.
    var size: CGFloat = 11.5
    var prepared = line(size)
    var ink = inkBox(prepared)
    if ink.width > box.width {
        size *= box.width / ink.width
        prepared = line(size)
        ink = inkBox(prepared)
    }

    guard let context = NSGraphicsContext.current?.cgContext else { return }
    context.saveGState()
    context.textMatrix = .identity
    // Place the outline box: horizontally centred in the mark box, vertically
    // centred on the canvas midline.
    let originX = box.midX - ink.midX
    let originY = midline - ink.midY
    context.textPosition = CGPoint(x: originX, y: originY)
    CTLineDraw(prepared, context)
    context.restoreGState()
}

/// The previous mark: an eight-ray burst, kept for comparison.
func drawBurst() {
    NSColor.labelColor.setStroke()
    let rays = NSBezierPath()
    rays.lineWidth = 1.65
    rays.lineCapStyle = .round
    let center = NSPoint(x: 11, y: 11)
    let reach: [(CGFloat, CGFloat)] = [
        (9.0, 6.0),  // cardinals: right, up, left, down
        (6.48, 4.32) // diagonals, 0.72 of the cardinals
    ]
    for index in 0..<8 {
        let angle = Double(index) * .pi / 4
        let (rx, ry) = reach[index % 2]
        let cosA = CGFloat(cos(angle)), sinA = CGFloat(sin(angle))
        rays.move(to: NSPoint(x: center.x + cosA * rx * 0.24,
                              y: center.y + sinA * ry * 0.24))
        rays.line(to: NSPoint(x: center.x + cosA * rx,
                              y: center.y + sinA * ry))
    }
    rays.stroke()
}

/// The activity light keeps its diameters but now shares centre (20.4, 5):
/// halo `(16.4, 1, 8×8)`, core `(17.4, 2, 6×6)`. The halo grows to 9×9 for
/// the few seconds after the talking set changes, around the same centre, so the
/// core stays put and only the swell is noticeable.
///
/// The halo stays even though the `CC` mark no longer reaches into it: the light
/// is the part of the icon that is already familiar, and its size, colour and
/// place are not something to redesign in passing.
func drawLight(_ light: NSColor, pulsing: Bool) {
    let halo = pulsing ? lightPulseHaloDiameter : lightHaloDiameter
    NSColor.windowBackgroundColor.setFill()
    NSBezierPath(ovalIn: NSRect(x: lightCenterX - halo / 2,
                                y: lightCenterY - halo / 2,
                                width: halo, height: halo)).fill()
    light.setFill()
    NSBezierPath(ovalIn: NSRect(x: lightCenterX - lightCoreDiameter / 2,
                                y: lightCenterY - lightCoreDiameter / 2,
                                width: lightCoreDiameter,
                                height: lightCoreDiameter)).fill()
}

func relative(_ seconds: TimeInterval) -> String {
    if seconds < 5 { return "刚刚" }
    if seconds < 60 { return "\(Int(seconds)) 秒前" }
    if seconds < 3600 { return "\(Int(seconds / 60)) 分钟前" }
    return "\(Int(seconds / 3600)) 小时前"
}

func statusLabel(_ session: Session) -> String {
    switch session.status {
    case "busy": return "工作中"
    case "shell": return "执行命令"
    case "waiting": return "等待确认"
    default: return "空闲"
    }
}

func statusColor(_ session: Session) -> NSColor {
    if session.waiting { return .systemYellow }
    if session.working { return .systemGreen }
    return .systemPurple
}

/// Single-instance guard. A launchd job starts the Mach-O directly rather than
/// through LaunchServices, so the process may have no bundle identifier — the
/// `NSRunningApplication` check alone cannot see it. An exclusive lock on a
/// per-user file is exact, whatever route the app was started by.
enum InstanceLock {
    private static var handle: FileHandle?

    static func acquire() -> Bool {
        let path = (NSTemporaryDirectory() as NSString)
            .appendingPathComponent("local.claude.activity.lock")
        let fd = open(path, O_CREAT | O_RDWR, 0o600)
        guard fd >= 0 else { return true } // no lock file: running beats disappearing
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            close(fd)
            return false
        }
        handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        return true
    }
}

class Delegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var item: NSStatusItem!
    var timer: Timer?
    var sessions: [Session] = []
    var readable = true
    /// A short highlight after the set of *talking* sessions changes, so a
    /// session going quiet is visible even when no process exits.
    var pulseUntil = Date.distantPast
    var lastActive: Set<Int32> = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        if !InstanceLock.acquire() {
            NSApp.terminate(nil)
            return
        }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
        item.button?.imagePosition = .imageLeading
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        update(initial: true)
        rebuildMenu()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            self?.update(initial: false)
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    func menuWillOpen(_ menu: NSMenu) {
        update(initial: false, rebuild: false)
        rebuildMenu()
    }

    func rebuildMenu() {
        guard let menu = item.menu else { return }
        menu.removeAllItems()
        menu.addItem(NSMenuItem(title: "Claude · 会话活动", action: nil, keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: summarize(sessions, readable: readable).detail, action: nil, keyEquivalent: ""))

        if !sessions.isEmpty {
            menu.addItem(.separator())
            for session in sessions.prefix(15) {
                let row = NSMenuItem(
                    title: "\(session.title.prefix(30))  ·  \(statusLabel(session))  ·  \(relative(session.age))",
                    action: nil,
                    keyEquivalent: ""
                )
                row.image = dot(statusColor(session))
                row.toolTip = "\(session.folder)\nPID \(session.pid)\n\(session.sessionId)"
                menu.addItem(row)
            }
            if sessions.count > 15 {
                menu.addItem(NSMenuItem(title: "另有 \(sessions.count - 15) 个会话…", action: nil, keyEquivalent: ""))
            }
        }

        menu.addItem(.separator())
        menu.addItem(NSMenuItem(title: "数字：正在对话的会话数 · 每 2 秒刷新", action: nil, keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "紫：空闲　绿：正在对话　橙：读不到注册表", action: nil, keyEquivalent: ""))
        let quit = NSMenuItem(title: "退出 Claude Activity", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
    }

    func update(initial: Bool, rebuild: Bool = false) {
        let (found, ok) = Registry.snapshot()
        readable = ok
        sessions = found
        let pids = Set(found.filter(\.conversing).map(\.pid))
        // Four seconds outlives two 2-second polls, so a conversation starting or
        // ending never flickers past unseen. Watching the talking set rather than
        // every live pid means going quiet pulses too — a session that finishes
        // its work stays open, so no process exits to catch.
        if !initial && pids != lastActive { pulseUntil = Date().addingTimeInterval(4) }
        lastActive = pids

        let summary = summarize(found, readable: ok)
        let pulsing = Date() < pulseUntil
        item.button?.title = summary.title
        item.button?.toolTip = summary.detail
        item.button?.setAccessibilityLabel(summary.detail)
        item.button?.image = icon(light: summary.color, pulsing: pulsing)

        if rebuild { rebuildMenu() }
    }

    /// The mark plus a coloured activity light, drawn into a 23.5×22 box.
    ///
    /// The shape lives in `drawMark`, together with the two alternatives it was
    /// chosen over, so the preview renderer can draw the same code the app uses.
    /// Only the light changes with state — colour always, radius briefly after the
    /// session set changes. The mark itself never moves.
    func icon(light: NSColor, pulsing: Bool) -> NSImage {
        let image = NSImage(size: canvas, flipped: false) { _ in
            drawMark(style: activeMark, light: light, pulsing: pulsing)
            return true
        }
        image.isTemplate = false // keep the light's colour; the mark is labelColor
        return image
    }

    func dot(_ color: NSColor) -> NSImage {
        NSImage(size: NSSize(width: 10, height: 10), flipped: false) { _ in
            color.setFill()
            NSBezierPath(ovalIn: NSRect(x: 1.5, y: 1.5, width: 7, height: 7)).fill()
            return true
        }
    }

    @objc func quit() { NSApp.terminate(nil) }
}

if CommandLine.arguments.contains("--render") {
    // Writes a contact sheet so the icon can be looked at before installing it.
    // Same drawing code the menu bar uses, just rendered at a readable scale.
    let args = CommandLine.arguments
    let out = (args.firstIndex(of: "--out").flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil })
        ?? "preview.png"
    let scale: CGFloat = (args.firstIndex(of: "--scale").flatMap {
        $0 + 1 < args.count ? Double(args[$0 + 1]).map { CGFloat($0) } : nil
    }) ?? 8
    let states: [(String, NSColor, Bool)] = [
        ("空闲", .systemPurple, false),
        ("对话", .systemGreen, false),
        ("脉冲", .systemGreen, true),
        ("等待", .systemYellow, false),
        ("读不到", .systemOrange, false),
    ]
    let styles: [Mark] = args.contains("--both") ? [.cc, .burst] : [activeMark]
    let rowHeight = canvas.height * scale + 16
    let sheet = NSSize(width: canvas.width * scale * CGFloat(states.count) + 16,
                       height: rowHeight * CGFloat(styles.count) + 8)
    let image = NSImage(size: sheet, flipped: false) { _ in
        NSColor.white.setFill()
        NSRect(origin: .zero, size: sheet).fill()
        for (row, style) in styles.enumerated() {
            for (column, state) in states.enumerated() {
                let context = NSGraphicsContext.current!.cgContext
                context.saveGState()
                let originX = 8 + CGFloat(column) * canvas.width * scale
                let originY = 8 + CGFloat(styles.count - 1 - row) * rowHeight
                context.translateBy(x: originX, y: originY)
                context.scaleBy(x: scale, y: scale)
                drawMark(style: style, light: state.1, pulsing: state.2)
                context.restoreGState()
            }
        }
        // Hairline box around each 23.5×22 cell, so spacing is visible, not guessed.
        // Two dashed guides: y = 11 is the canvas midline the mark's ink is centred
        // on; y = 5 is the light's centre. They are deliberately different — the
        // light has always sat low in the right-hand column and must stay there.
        NSColor(white: 0.85, alpha: 1).setStroke()
        let grid = NSBezierPath()
        grid.lineWidth = 0.5
        for (row, _) in styles.enumerated() {
            for column in 0..<states.count {
                let rect = NSRect(x: 8 + CGFloat(column) * canvas.width * scale,
                                  y: 8 + CGFloat(styles.count - 1 - row) * rowHeight,
                                  width: canvas.width * scale, height: canvas.height * scale)
                grid.appendRect(rect)
            }
        }
        grid.stroke()
        for (guideY, guideColor) in [(midline, NSColor(red: 0.85, green: 0.2, blue: 0.2, alpha: 0.55)),
                                     (lightCenterY, NSColor(red: 0.15, green: 0.45, blue: 0.85, alpha: 0.55))] {
            guideColor.setStroke()
            let guide = NSBezierPath()
            guide.lineWidth = 1
            guide.setLineDash([6, 6], count: 2, phase: 0)
            for (row, _) in styles.enumerated() {
                let baseY = 8 + CGFloat(styles.count - 1 - row) * rowHeight
                for column in 0..<states.count {
                    let x0 = 8 + CGFloat(column) * canvas.width * scale
                    guide.move(to: NSPoint(x: x0, y: baseY + guideY * scale))
                    guide.line(to: NSPoint(x: x0 + canvas.width * scale, y: baseY + guideY * scale))
                }
            }
            guide.stroke()
        }
        return true
    }
    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let png = rep.representation(using: .png, properties: [:]) else {
        print("渲染失败")
        exit(1)
    }
    try! png.write(to: URL(fileURLWithPath: out))
    print("已渲染 \(out)  (\(Int(sheet.width))×\(Int(sheet.height)))")
    exit(0)
}

if CommandLine.arguments.contains("--check") {
    let (sessions, readable) = Registry.snapshot()
    let summary = summarize(sessions, readable: readable)
    let number = summary.title.trimmingCharacters(in: .whitespaces)
    print(number.isEmpty ? summary.detail : "菜单栏数字「\(number)」 · \(summary.detail)")
    for session in sessions {
        print("  \(session.title)  ·  \(statusLabel(session))  ·  \(relative(session.age))  ·  \(session.folder)")
    }
    exit(readable ? 0 : 1)
}

if CommandLine.arguments.contains("--self-test") {
    func make(_ pid: Int32, _ status: String, age: Double = 0) -> Session {
        Session(pid: pid, sessionId: UUID().uuidString, cwd: "/tmp/project", name: "s\(pid)",
                status: status, updatedAt: Date().timeIntervalSince1970 * 1000 - age * 1000)
    }
    // Nothing running and unreadable: no number at all.
    assert(summarize([], readable: true).title.isEmpty)
    assert(summarize([], readable: true).color == .systemPurple)
    assert(summarize([], readable: true).talking == 0)
    assert(summarize([], readable: false).color == .systemOrange)
    assert(summarize([], readable: false).title.isEmpty)
    // The bar carries the number of *talking* sessions and nothing else — never a
    // status phrase, and never a session that is merely alive. An idle session left
    // open for hours must leave the bar empty and the light purple.
    let idleOnly = summarize([make(2, "idle")], readable: true)
    assert(idleOnly.title.isEmpty)
    assert(idleOnly.color == .systemPurple)
    assert(idleOnly.talking == 0)
    assert(idleOnly.detail.contains("全部空闲"))
    // Two idle sessions hanging around: still nothing in the bar. This is the bug
    // the user reported — the bar read "2" while neither session was doing work.
    let twoIdle = summarize([make(2, "idle"), make(3, "idle", age: 3600)], readable: true)
    assert(twoIdle.title.isEmpty)
    assert(twoIdle.color == .systemPurple)
    assert(twoIdle.detail.contains("2 个会话"))
    // Talking turns the light green and puts the number up.
    for status in ["busy", "shell", "waiting"] {
        let s = summarize([make(2, status)], readable: true)
        assert(s.title == "1")
        assert(s.color == .systemGreen)
        assert(s.talking == 1)
    }
    // One talking session is enough, and the number counts only the talking ones.
    let mixed = [make(2, "busy"), make(3, "idle"), make(4, "waiting")]
    let summary = summarize(mixed, readable: true)
    assert(summary.title == "2")
    assert(!summary.title.contains("对话")) // the phrase lives in the menu, not the bar
    assert(summary.detail.contains("2 个正在对话"))
    assert(summary.detail.contains("共 3 个会话"))
    // Ending the last talking session clears the number and returns to purple.
    let quiet = summarize([make(3, "idle")], readable: true)
    assert(quiet.title.isEmpty)
    assert(quiet.color == .systemPurple)
    // Status classification.
    assert(make(2, "busy").conversing && make(2, "waiting").conversing)
    assert(!make(2, "idle").conversing)
    // Our own pid must register as alive, and pid 0 must not.
    assert(Registry.alive(getpid()))
    assert(!Registry.alive(0))
    print("PASS: 只算正在对话的会话、空闲不计数不显示、对话转绿、结束回落")
    exit(0)
}

let app = NSApplication.shared
let delegate = Delegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
