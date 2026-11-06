import AppKit

private let harnessBundleID = "com.deepseek.dsh"
private let iconHeight: CGFloat = 22
private let baseWidth: CGFloat = 23.35
private let badgeGap: CGFloat = 1.5
private let textPad: CGFloat = 0.75

struct SessionSample: Equatable {
    let id: String
    let title: String
    let cwd: String
    let working: Bool
    let waiting: Bool

    var engaged: Bool { working || waiting }
}

enum ActivityState: Equatable {
    case stopped
    case unreadable
    case idle
    case working(Int)
    case waiting(Int)

    var color: NSColor {
        switch self {
        case .stopped: return .systemGray
        case .unreadable: return .systemOrange
        case .idle: return .systemPurple
        case .working: return .systemGreen
        case .waiting: return .systemYellow
        }
    }

    var count: Int {
        switch self {
        case .working(let count), .waiting(let count): return count
        default: return 0
        }
    }

    var detail: String {
        switch self {
        case .stopped: return "DeepSeek Harness 未运行"
        case .unreadable: return "无法读取 DeepSeek Harness 会话状态"
        case .idle: return "DeepSeek Harness 空闲 · 没有进行中的任务"
        case .working(let count): return "DeepSeek Harness 正在工作 · \(count) 个会话"
        case .waiting(let count): return "DeepSeek Harness 等待确认 · \(count) 个进行中会话"
        }
    }
}

final class Monitor {
    let root: URL
    private(set) var readable = false
    private(set) var sessions: [SessionSample] = []

    init(root: URL) { self.root = root }

    func poll() {
        let fm = FileManager.default
        guard fm.isReadableFile(atPath: root.path),
              let files = try? fm.contentsOfDirectory(at: root,
                                                       includingPropertiesForKeys: nil,
                                                       options: [.skipsHiddenFiles]) else {
            readable = false
            sessions = []
            return
        }

        readable = true
        sessions = files
            .filter { $0.pathExtension == "json" }
            .compactMap(Self.parse)
            .sorted {
                if $0.waiting != $1.waiting { return $0.waiting && !$1.waiting }
                if $0.working != $1.working { return $0.working && !$1.working }
                return $0.title.localizedStandardCompare($1.title) == .orderedAscending
            }
    }

    func state(harnessRunning: Bool) -> ActivityState {
        guard harnessRunning else { return .stopped }
        guard readable else { return .unreadable }
        let engaged = sessions.filter(\.engaged)
        if engaged.contains(where: \.waiting) { return .waiting(engaged.count) }
        if !engaged.isEmpty { return .working(engaged.count) }
        return .idle
    }

    static func parse(_ url: URL) -> SessionSample? {
        guard let data = try? Data(contentsOf: url),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let record = root["record"] as? [String: Any],
              let rows = record["rows"] as? [String: Any] else { return nil }

        func value(_ key: String) -> Any? {
            (rows[key] as? [String: Any])?["val"]
        }

        let identity = record["identity"] as? [String: Any]
        let cwd = identity?["cwd"] as? String ?? ""
        let rawTitle = value("title") as? String ?? ""
        let fallback = cwd.isEmpty ? String(url.deletingPathExtension().lastPathComponent.suffix(8))
                                   : URL(fileURLWithPath: cwd).lastPathComponent
        let title = rawTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? fallback : rawTitle

        let stats = value("sessionStats") as? [String: Any]
        let openStep = stats?["openStep"]
        let hasOpenStep = openStep != nil && !(openStep is NSNull)
        let pending = stats?["pendingCalls"] as? [String: Any]
        let hasPendingCalls = !(pending?.isEmpty ?? true)

        let questions = value("userQuestions") as? [String: Any]
        let questionGroups = questions?["questions"] as? [String: Any]
        let activeQuestions = questionGroups?["active"] as? [Any]
        let waiting = !(activeQuestions?.isEmpty ?? true)

        return SessionSample(id: url.deletingPathExtension().lastPathComponent,
                             title: title, cwd: cwd,
                             working: hasOpenStep || hasPendingCalls,
                             waiting: waiting)
    }
}

private func harnessIsRunning() -> Bool {
    !NSRunningApplication.runningApplications(withBundleIdentifier: harnessBundleID).isEmpty
}

private func whaleArtwork() -> NSImage? {
    guard let url = Bundle.main.url(forResource: "WhaleTemplate", withExtension: "png"),
          let image = NSImage(contentsOf: url) else { return nil }
    image.isTemplate = false
    return image
}

private func activityIcon(state: ActivityState, whale: NSImage?, count: Int, font: NSFont) -> NSImage {
    let text = count > 0 ? "\(count)" : ""
    let attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: NSColor.labelColor,
    ]
    let textWidth = text.isEmpty ? 0 : (text as NSString).size(withAttributes: attrs).width
    let width = baseWidth + (text.isEmpty ? 0 : badgeGap + textWidth + textPad)
    let image = NSImage(size: NSSize(width: width, height: iconHeight), flipped: false) { _ in
        if let whale {
            NSColor.labelColor.set()
            let target = NSRect(x: 0, y: 5.1, width: 17.0, height: 12.5)
            whale.draw(in: target, from: .zero, operation: .sourceOver, fraction: 1)
        } else {
            NSColor.labelColor.setStroke()
            let fallback = NSBezierPath(ovalIn: NSRect(x: 0.6, y: 6, width: 16, height: 11))
            fallback.lineWidth = 1.5
            fallback.stroke()
        }

        // A background disc keeps the state light legible over the whale's tail.
        NSColor.windowBackgroundColor.setFill()
        NSBezierPath(ovalIn: NSRect(x: 15.85, y: 0.75, width: 7.5, height: 7.5)).fill()
        state.color.setFill()
        NSBezierPath(ovalIn: NSRect(x: 16.6, y: 1.5, width: 6, height: 6)).fill()

        if !text.isEmpty {
            let baseline = (iconHeight - font.capHeight) / 2
            let y = baseline + font.descender
            (text as NSString).draw(
                at: NSPoint(x: baseWidth + badgeGap, y: y),
                withAttributes: attrs
            )
        }
        return true
    }
    image.isTemplate = false
    return image
}

final class Delegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private var item: NSStatusItem!
    private var timer: Timer?
    private let monitor: Monitor
    private let whale = whaleArtwork()

    override init() {
        let path = ProcessInfo.processInfo.environment["DSH_ACTIVITY_ROOT"]
            ?? NSHomeDirectory() + "/.dsh/storages/session_projcache/sessions"
        monitor = Monitor(root: URL(fileURLWithPath: path, isDirectory: true))
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if NSRunningApplication.runningApplications(withBundleIdentifier: "local.deepseek.harness.activity").count > 1 {
            NSApp.terminate(nil)
            return
        }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
        item.button?.imagePosition = .imageLeading
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        update(rebuild: true)
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            self?.update(rebuild: false)
        }
        RunLoop.main.add(timer!, forMode: .common)
    }

    func menuWillOpen(_ menu: NSMenu) { update(rebuild: true) }

    private func update(rebuild: Bool) {
        monitor.poll()
        let state = monitor.state(harnessRunning: harnessIsRunning())
        item.button?.title = ""
        item.button?.toolTip = state.detail
        item.button?.setAccessibilityLabel(state.detail)
        let font = item.button?.font ?? NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
        item.button?.image = activityIcon(state: state, whale: whale, count: state.count, font: font)
        if rebuild { rebuildMenu(state: state) }
    }

    private func rebuildMenu(state: ActivityState) {
        guard let menu = item.menu else { return }
        menu.removeAllItems()
        menu.addItem(NSMenuItem(title: "DeepSeek Harness · 会话活动", action: nil, keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: state.detail, action: nil, keyEquivalent: ""))
        let engaged = monitor.sessions.filter(\.engaged)
        if !engaged.isEmpty {
            menu.addItem(.separator())
            for sample in engaged.prefix(15) {
                let status = sample.waiting ? "等待确认" : "工作中"
                let row = NSMenuItem(title: String(sample.title.prefix(48)), action: nil, keyEquivalent: "")
                row.image = NSImage(systemSymbolName: sample.waiting ? "questionmark.circle.fill" : "circle.fill",
                                    accessibilityDescription: status)
                row.toolTip = sample.cwd.isEmpty ? status : "\(status) · \(sample.cwd)"
                menu.addItem(row)
            }
        }
        menu.addItem(.separator())
        let open = NSMenuItem(title: "打开 DeepSeek Harness", action: #selector(openHarness), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        menu.addItem(NSMenuItem(title: "数字：工作中或等待确认的会话数 · 每 2 秒刷新", action: nil, keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "绿：工作　黄：等待确认　紫：空闲　灰：未运行　橙：读取失败", action: nil, keyEquivalent: ""))
        let quit = NSMenuItem(title: "退出 DeepSeek Harness Activity", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
    }

    @objc private func openHarness() {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: harnessBundleID) {
            NSWorkspace.shared.openApplication(at: url, configuration: .init())
        }
    }

    @objc private func quit() { NSApp.terminate(nil) }
}

if CommandLine.arguments.contains("--render") {
    let arguments = CommandLine.arguments
    let output = arguments.firstIndex(of: "--out").flatMap {
        $0 + 1 < arguments.count ? arguments[$0 + 1] : nil
    } ?? "/tmp/deepseek-harness-activity.png"
    let scale: CGFloat = 8
    let states: [(ActivityState, Int)] = [
        (.stopped, 0), (.unreadable, 0), (.idle, 0), (.working(1), 1), (.waiting(1), 1),
    ]
    let font = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .semibold)
    let whale = whaleArtwork()
    let icons = states.map { activityIcon(state: $0.0, whale: whale, count: $0.1, font: font) }
    let gap: CGFloat = 8
    let cellWidth = (icons.map(\.size.width).max() ?? baseWidth) + gap
    let size = NSSize(width: cellWidth * scale * CGFloat(icons.count),
                      height: iconHeight * scale)
    let sheet = NSImage(size: size, flipped: false) { _ in
        NSColor.white.setFill()
        NSRect(origin: .zero, size: size).fill()
        for (index, icon) in icons.enumerated() {
            let context = NSGraphicsContext.current!.cgContext
            context.saveGState()
            context.translateBy(x: CGFloat(index) * cellWidth * scale, y: 0)
            context.scaleBy(x: scale, y: scale)
            icon.draw(in: NSRect(origin: .zero, size: icon.size))
            context.restoreGState()
        }
        return true
    }
    guard let tiff = sheet.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        print("渲染失败")
        exit(1)
    }
    try! png.write(to: URL(fileURLWithPath: output))
    print("已渲染 \(output)（\(Int(size.width))×\(Int(size.height))）")
    exit(0)
}

if CommandLine.arguments.contains("--check") {
    let path = ProcessInfo.processInfo.environment["DSH_ACTIVITY_ROOT"]
        ?? NSHomeDirectory() + "/.dsh/storages/session_projcache/sessions"
    let monitor = Monitor(root: URL(fileURLWithPath: path, isDirectory: true))
    monitor.poll()
    print(monitor.state(harnessRunning: harnessIsRunning()).detail)
    exit(monitor.readable ? 0 : 1)
}

if CommandLine.arguments.contains("--self-test") {
    let fm = FileManager.default
    let root = fm.temporaryDirectory.appendingPathComponent("dsh-activity-\(UUID().uuidString)")
    try! fm.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? fm.removeItem(at: root) }

    func fixture(_ name: String, open: Bool, waiting: Bool, pending: Bool = false) {
        let openStep: Any = open ? ["turn": 1, "step": 1] : NSNull()
        let pendingCalls: [String: Any] = pending ? ["call": ["name": "tool"]] : [:]
        let json: [String: Any] = [
            "record": [
                "identity": ["cwd": "/tmp/\(name)"],
                "rows": [
                    "title": ["val": name],
                    "sessionStats": ["val": [
                        "openStep": openStep,
                        "pendingCalls": pendingCalls
                    ]],
                    "userQuestions": ["val": ["questions": [
                        "active": waiting ? [["id": "q"]] : []
                    ]]]
                ]
            ]
        ]
        let data = try! JSONSerialization.data(withJSONObject: json)
        try! data.write(to: root.appendingPathComponent("\(name).json"))
    }

    fixture("idle", open: false, waiting: false)
    let monitor = Monitor(root: root)
    monitor.poll()
    assert(monitor.state(harnessRunning: true) == .idle)
    fixture("working", open: true, waiting: false)
    monitor.poll()
    assert(monitor.state(harnessRunning: true) == .working(1))
    fixture("pending", open: false, waiting: false, pending: true)
    monitor.poll()
    assert(monitor.state(harnessRunning: true) == .working(2))
    fixture("waiting", open: true, waiting: true)
    monitor.poll()
    assert(monitor.state(harnessRunning: true) == .waiting(3))
    assert(monitor.state(harnessRunning: false) == .stopped)
    let missing = Monitor(root: root.appendingPathComponent("missing"))
    missing.poll()
    assert(missing.state(harnessRunning: true) == .unreadable)
    print("PASS: Harness 运行检测、工作、等待确认、空闲与读取失败")
    exit(0)
}

let app = NSApplication.shared
let delegate = Delegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
