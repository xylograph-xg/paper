import AppKit
import SwiftUI
import WebKit

struct TaskRow: Decodable, Identifiable {
    let id: String, group: String, label: String, title: String, state: String, detail: String, issue: String, icon: String
    let elapsed: Int?
    let progress: Double?
    let resultPath: String?
    let endedAt: String?
    let formulaSlots: [FormulaSlot]?
    let formulaApp: Bool?
    let formulaAppWindows: AppWindowObservation?
    let formulaAppOnline: Bool?
    let formulaAppTurns: Int?
    let formulaEnabled: Bool?
    let formulaRetry: Bool?
    let concurrencyTarget: String?
    let concurrencyValue: Int?
    let reservedPages: Int?
    let actualParallel: Int?
    let actualParallelConfirmed: Bool?
}
struct CommandFile: Decodable, Identifiable {
    let id: String, name: String, path: String, relativePath: String
}
struct UserAction: Decodable, Identifiable {
    let id: String, title: String, action: String, source: String
    let conversation_url: String?
    let handling: String?
    let stage: String?
    let automatic_action: String?
}
struct PageGridCell: Decodable, Identifiable {
    let id: String, status: String, tooltip: String
    let column: Int, row: Int
    let lane: String?
    let severity: String?
}
struct PageGrid: Decodable {
    let columns: Int, rows: Int, cells: [PageGridCell], legend: String
}
struct GradualRestartStatus: Decodable {
    let state: String
    let remaining: Int?
    let message: String?
}
struct Snapshot: Decodable {
    let commands: [CommandFile]
    let updated: Double, rows: [TaskRow], warnings: [String]
    let ended: [TaskRow]
    let seedOnly: Bool?
    let continuousRunning: Bool?
    let actions: [UserAction]?
    let pageGrid: PageGrid?
}

class Model: ObservableObject {
    @Published var snapshot: Snapshot?
    @Published var error = ""
    @Published var pinned = false
    @Published var selected = ""
    @Published var controlling = false
    @Published var controlMessage = ""
    @Published var concurrencyOverrides: [String: Int] = [:]
    @Published var cardTemplateURL: URL?
    @Published var restartMessage = ""
    @Published var restartRemaining: Int?
    private var busy = false
    private var timer: Timer?
    let root: String
    init(root: String) { self.root = root }
    func setSeedOnly(_ enabled: Bool) {
        guard !controlling else { return }
        controlling = true
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process(), pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: self.root + "/infrastructure/environments/web/bin/python")
            process.currentDirectoryURL = URL(fileURLWithPath: self.root)
            process.arguments = ["-m", "core.seed_focus", enabled ? "--enable" : "--disable"]
            process.standardOutput = pipe; process.standardError = pipe
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                DispatchQueue.main.async {
                    self.controlling = false
                    self.controlMessage = process.terminationStatus == 0 ? (enabled ? "仅手选种子；其他文献停止新派发，在途回答继续归档" : "已关闭手选独占；原有暂停设置保持") : "切换失败：" + String(decoding: data.suffix(300), as: UTF8.self)
                    self.refresh()
                }
            } catch { DispatchQueue.main.async { self.controlling = false; self.controlMessage = error.localizedDescription } }
        }
    }
    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in self?.refresh() }
    }
    func runCommand(_ command: CommandFile) {
        let url = URL(fileURLWithPath: command.path).standardizedFileURL
        guard snapshot?.commands.contains(where: { $0.id == command.id && $0.path == url.path }) == true, url.pathExtension == "command",
              FileManager.default.fileExists(atPath: url.path) else {
            error = "运行入口无效，请刷新任务面板"; return
        }
        NSWorkspace.shared.open([url], withApplicationAt: URL(fileURLWithPath: "/System/Applications/Utilities/Terminal.app"), configuration: NSWorkspace.OpenConfiguration()) { _, failure in
            if let failure = failure { DispatchQueue.main.async { self.error = "打开运行入口失败：" + failure.localizedDescription } }
        }
    }
    func hasCardTemplate(_ command: CommandFile) -> Bool {
        command.path == URL(fileURLWithPath: root).appendingPathComponent("workbench/commands/启动文献工作台.command").standardizedFileURL.path
    }
    func showCardTemplate(_ command: CommandFile) {
        guard hasCardTemplate(command), snapshot?.commands.contains(where: { $0.id == command.id && $0.path == command.path }) == true else {
            error = "模板入口无效，请刷新任务面板"; return
        }
        let url = URL(fileURLWithPath: root).appendingPathComponent("infrastructure/docs/文献卡片模板.html")
        guard FileManager.default.isReadableFile(atPath: url.path) else {
            error = "文献卡片模板文件缺失，请重新运行启动任务面板"; return
        }
        cardTemplateURL = url
    }
    func controlContinuous(target: String, stop: Bool) {
        if stop {
            let alert = NSAlert()
            alert.messageText = "确认停止" + (["formula":"公式整理", "fetch":"拉取", "cards":"制卡", "review":"核验", "correction":"修正", "literature_level1":"一级标签", "literature_level2":"二级标签"][target] ?? target) + "？"
            alert.informativeText = "保留已有结果、任务记录和原会话；之后可点击启动继续。"
            alert.alertStyle = .warning
            alert.addButton(withTitle: "停止")
            alert.addButton(withTitle: "取消")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
        }
        guard !controlling else { return }
        controlling = true
        controlMessage = stop ? "正在停止…" : "正在启动…"
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process(), pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: self.root + "/infrastructure/environments/web/bin/python")
            process.currentDirectoryURL = URL(fileURLWithPath: self.root)
            process.arguments = ["-m", "core.continuous_start", "--target", target]
            if target == "literature_level1" || target == "literature_level2" {
                process.arguments = ["-m", target == "literature_level2" ? "literature.background_level2" : "literature.background", stop ? "--pause" : "--start"]
            }
            else if target == "formula" {
                process.arguments = ["-m", "oled_formulas", stop ? "pause" : "start"]
            }
            else if stop { process.arguments!.append("--stop") }
            else if target == "cards" { process.arguments!.append("--open-browser") }
            process.standardOutput = pipe; process.standardError = pipe
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let ok = process.terminationStatus == 0
                DispatchQueue.main.async {
                    self.controlling = false
                    self.controlMessage = ok ? (stop ? "暂停请求已提交" : "启动请求已提交") : "操作失败：" + String(decoding: data.suffix(400), as: UTF8.self)
                    self.refresh()
                }
            } catch {
                DispatchQueue.main.async { self.controlling = false; self.controlMessage = error.localizedDescription }
            }
        }
    }
    func setConcurrency(target: String, value: Int) {
        guard !controlling else { return }
        controlling = true; concurrencyOverrides[target] = value
        controlMessage = "正在调整并行数量…"
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process(), pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: self.root + "/infrastructure/environments/web/bin/python")
            process.currentDirectoryURL = URL(fileURLWithPath: self.root)
            process.arguments = ["-m", "core.concurrency_control", "--target", target, "--value", String(value)]
            process.standardOutput = pipe; process.standardError = pipe
            do {
                try process.run(); let data = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
                DispatchQueue.main.async {
                    self.controlling = false; self.concurrencyOverrides.removeValue(forKey: target)
                    self.controlMessage = process.terminationStatus == 0 ? "已设置并行 \(value)" : "调整失败：" + String(decoding: data.suffix(300), as: UTF8.self)
                    self.refresh()
                }
            } catch {
                DispatchQueue.main.async { self.controlling = false; self.concurrencyOverrides.removeValue(forKey: target); self.controlMessage = error.localizedDescription }
            }
        }
    }
    func gradualRestart() {
        guard !controlling else { return }
        let alert = NSAlert()
        alert.messageText = "渐进重启网页任务？"
        alert.informativeText = "等待当前生成和上传结束后再重启 owner；不丢弃在途任务。若超过 30 分钟仍有任务，则保留当前进程。"
        alert.alertStyle = .warning
        alert.addButton(withTitle: "等待并重启")
        alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        controlling = true
        restartMessage = "等待当前任务结束…"
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process(), pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: self.root + "/infrastructure/environments/web/bin/python")
            process.currentDirectoryURL = URL(fileURLWithPath: self.root)
            process.arguments = ["-m", "core.gradual_restart", "--timeout", "1800", "--config", "infrastructure/config/first_round.json"]
            process.standardOutput = pipe; process.standardError = pipe
            do {
                try process.run()
                let statusURL = URL(fileURLWithPath: self.root + "/infrastructure/data/web-gradual-restart.json")
                while process.isRunning {
                    if let data = try? Data(contentsOf: statusURL),
                       let status = try? JSONDecoder().decode(GradualRestartStatus.self, from: data) {
                        DispatchQueue.main.async {
                            self.restartRemaining = status.remaining
                            if let message = status.message {
                                self.restartMessage = status.remaining.map { "剩余 \($0) 项 · " + message } ?? message
                            }
                        }
                    }
                    Thread.sleep(forTimeInterval: 1)
                }
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let text = String(decoding: data.suffix(600), as: UTF8.self)
                DispatchQueue.main.async {
                    self.controlling = false
                    self.restartRemaining = nil
                    self.restartMessage = process.terminationStatus == 0 ? "重启完成，正在刷新" : "未重启：" + text
                    self.refresh()
                }
            } catch {
                DispatchQueue.main.async { self.controlling = false; self.restartMessage = error.localizedDescription }
            }
        }
    }
    func refresh() {
        guard !busy else { return }; busy = true
        let script = root + "/workbench/desktop_widget/snapshot.py"
        DispatchQueue.global(qos: .utility).async {
            let process = Process(), pipe = Pipe()
            let python = Bundle.main.object(forInfoDictionaryKey: "TaskPython") as? String ?? "/usr/bin/python3"
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [script]
            process.standardOutput = pipe
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else { throw NSError(domain: "读取状态失败", code: 1) }
                let value = try JSONDecoder().decode(Snapshot.self, from: data)
                DispatchQueue.main.async { self.snapshot = value; self.error = ""; self.busy = false }
            } catch {
                DispatchQueue.main.async { self.error = "状态读取失败，将自动重试"; self.busy = false }
            }
        }
    }
}

struct PanelView: View {
    @ObservedObject var model: Model
    var setPinned: (Bool) -> Void
    func category(_ row: TaskRow) -> String { row.group }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                if let app = model.snapshot?.rows.first(where: { $0.formulaApp == true }) {
                    Button {
                        model.selected = app.group
                    } label: {
                        VStack(alignment: .leading) {
                            Label("Codex Web GPT", systemImage: "macwindow")
                            Text(app.formulaAppOnline == true ? "网页任务 " + (app.formulaAppTurns.map { String($0) } ?? "待观测") : "未连接").font(.caption)
                        }
                    }.buttonStyle(.borderless)
                } else if let grid = model.snapshot?.pageGrid, grid.columns == 20, grid.rows == 5, grid.cells.count == 100 {
                    CompactPageGrid(grid: grid)
                }
                Image(systemName: "waveform.path").foregroundStyle(.mint).font(.title2)
                VStack(alignment: .leading, spacing: 3) {
                    Text("共享任务状态").font(.system(size: 20, weight: .semibold))
                    Text("任务状态 · 每20秒更新").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.gradualRestart() } label: {
                    Label("渐进重启", systemImage: "arrow.triangle.2.circlepath")
                }.buttonStyle(.bordered).disabled(model.controlling)
                    .help("等待当前生成和上传结束后再重启共享 owner")
                Toggle("仅手选种子", isOn: Binding(get: { model.snapshot?.seedOnly ?? false }, set: { model.setSeedOnly($0) }))
                    .toggleStyle(.switch).fixedSize().disabled(model.controlling)
                    .help("暂停其他文献的新派发，只让手选种子继续；在途回答先完整收取归档")
                if model.controlling, let remaining = model.restartRemaining {
                    Text("剩余 \(remaining) 项").font(.caption).foregroundStyle(.secondary)
                }
                Button { model.pinned.toggle(); setPinned(model.pinned) } label: { Image(systemName: model.pinned ? "pin.fill" : "pin") }
                    .buttonStyle(.borderless).help("置顶 / 普通窗口")
                Button { model.refresh() } label: { Image(systemName: "arrow.clockwise") }.buttonStyle(.borderless).help("立即刷新")
            }.padding(20)
            if !model.restartMessage.isEmpty {
                Text(model.restartMessage).font(.caption).foregroundStyle(.secondary)
                    .padding(.horizontal, 20).padding(.bottom, 8)
            }
            Divider()
            if let s = model.snapshot {
                HStack {
                    Label("\(s.rows.filter { ["运行中", "评审中"].contains($0.state) }.count) 项运行", systemImage: "circle.fill").foregroundStyle(.mint)
                    Spacer()
                    if s.rows.contains(where: { $0.state == "停滞超过3小时" }) {
                        Label("手选停滞 \(s.rows.filter { $0.state == "停滞超过3小时" }.count)", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    }
                    Text("\(s.rows.filter { $0.state == "等待附件额度恢复" }.count) 项等待附件额度").foregroundStyle(.secondary)
                }.font(.caption).padding(.horizontal, 20).padding(.vertical, 12)
                ForEach(s.warnings.filter { $0.contains("附件") }, id: \.self) { warning in
                    Label(warning, systemImage: "exclamationmark.triangle.fill")
                        .font(.caption).foregroundStyle(.orange).textSelection(.enabled)
                        .padding(.horizontal, 20).padding(.bottom, 8)
                }
                let workflowOrder = ["paper · 公式整理", "paper · 拉取", "paper · 制卡", "paper · 核验", "paper · 修正", "paper · 手选追踪", "paper · 一级标签", "paper · 二级标签"]
                let categories = Array(Set((s.rows + s.ended).map { category($0) })).sorted {
                    let first = workflowOrder.firstIndex(of: $0), second = workflowOrder.firstIndex(of: $1)
                    if first != nil || second != nil { return (first ?? 4) < (second ?? 4) }
                    return $0 < $1
                } + ["运行入口"]
                let current = categories.contains(model.selected) ? model.selected : (categories.first ?? "")
                HStack(alignment: .top, spacing: 0) {
                    ScrollView {
                        VStack(spacing: 8) {
                            if !model.controlMessage.isEmpty { Text(model.controlMessage).font(.caption).foregroundStyle(.secondary) }
                            ForEach(categories, id: \.self) { name in
                                let running = s.rows.contains { category($0) == name && ["运行中", "评审中"].contains($0.state) }
                                VStack(alignment: .leading, spacing: 2) {
                                HStack(spacing: 4) {
                                Button { model.selected = name } label: {
                                    HStack {
                                        Circle().fill(running ? Color.green : Color.secondary).frame(width: 9, height: 9)
                                        Text(name).font(.system(size: 13, weight: .medium)).multilineTextAlignment(.leading)
                                        Spacer()
                                        Image(systemName: "chevron.right").font(.caption2)
                                    }.padding(12).background(current == name ? Color.accentColor.opacity(0.15) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
                                }.buttonStyle(.plain)
                                if let target = ["paper · 拉取":"fetch", "paper · 制卡":"cards", "paper · 核验":"review", "paper · 修正":"correction", "paper · 一级标签":"literature_level1", "paper · 二级标签":"literature_level2"][name] {
                                    let active = s.rows.contains { $0.group == name && $0.label == "常驻服务" && !["已停止", "已暂停"].contains($0.state) }
                                    Button(active ? "停止" : "启动") { model.controlContinuous(target: target, stop: active) }
                                        .buttonStyle(.bordered).disabled(model.controlling)
                                        .help(active ? "确认后停止此任务" : "启动此任务")
                                }
                                }
                                if let entry = s.rows.first(where: { $0.group == name && $0.formulaEnabled != nil }) {
                                    HStack {
                                    Toggle("公式整理", isOn: Binding(
                                        get: { entry.formulaEnabled == true },
                                        set: { model.controlContinuous(target: "formula", stop: !$0) }
                                    )).toggleStyle(.switch).labelsHidden().disabled(model.controlling)
                                    Text(entry.state).font(.caption).foregroundStyle(.secondary)
                                    if entry.formulaRetry == true {
                                        Button("重试") { model.controlContinuous(target: "formula", stop: false) }
                                            .buttonStyle(.bordered).disabled(model.controlling)
                                    }
                                    }.padding(.horizontal, 12)
                                }
                                if let entry = s.rows.first(where: { $0.group == name && $0.concurrencyTarget != nil }), let target = entry.concurrencyTarget {
                                    if target == "fetch" {
                                    HStack {
                                        Text("并行").font(.caption).foregroundStyle(.secondary)
                                        Picker("并行", selection: Binding(get: { model.concurrencyOverrides[target] ?? model.snapshot?.rows.first(where: { $0.concurrencyTarget == target })?.concurrencyValue ?? 1 }, set: { model.setConcurrency(target: target, value: $0) })) {
                                            let currentValue = model.concurrencyOverrides[target] ?? model.snapshot?.rows.first(where: { $0.concurrencyTarget == target })?.concurrencyValue ?? 1
                                            if ![32, 54, 72, 85, 100, 120, 150].contains(currentValue) {
                                                Text("当前 \(currentValue)").tag(currentValue).disabled(true)
                                            }
                                            ForEach([32, 54, 72, 85, 100, 120, 150], id: \.self) { value in Text(String(value)).tag(value) }
                                        }.labelsHidden().pickerStyle(.menu).frame(width: 76).disabled(model.controlling)
                                        Spacer()
                                    }.padding(.horizontal, 12).padding(.bottom, 5)
                                     .help("增加允许领取新任务；减少时先完成当前任务，再缩减")
                                    }
                                    if target != "fetch", let minimum = entry.reservedPages {
                                        let minimumKey = target + "_min_pages"
                                        HStack {
                                            Text("最低并行").font(.caption).foregroundStyle(.secondary)
                                            Picker("最低并行数量", selection: Binding(get: { model.concurrencyOverrides[minimumKey] ?? model.snapshot?.rows.first(where: {  $0.concurrencyTarget == target })?.reservedPages ?? minimum }, set: { model.setConcurrency(target: minimumKey, value: $0) })) {
                                                ForEach(Array(1...20), id: \.self) { value in Text(String(value)).tag(value) }
                                            }.labelsHidden().pickerStyle(.menu).frame(width: 76).disabled(model.controlling)
                                            Spacer()
                                        }.padding(.horizontal, 12).padding(.bottom, 5)
                                         .help("本任务最低预留；三项合计最多20，不抢占在途页面")
                                    }
                                    if target != "fetch" {
                                        let awaiting = s.pageGrid?.cells.filter { $0.status == "awaiting" && $0.lane == target }.count ?? 0
                                        HStack {
                                            Text("实际并行").font(.caption).foregroundStyle(.secondary)
                                            Text(entry.actualParallelConfirmed == true ? String(entry.actualParallel ?? 0) : "待观测").font(.caption.monospacedDigit())
                                            if awaiting > 0 {
                                                Text("· 上传/准备 \(awaiting)").font(.caption).foregroundStyle(.secondary)
                                            }
                                            Spacer()
                                        }.padding(.horizontal, 12).padding(.bottom, 5)
                                    }
                                }
                                }
                            }
                        }.padding(10)
                    }.frame(width: 225)
                    Divider()
                    ScrollView {
                        VStack(alignment: .leading, spacing: 12) {
                            Text(current).font(.headline)
                            if current == "运行入口" {
                                Text("点击运行会在终端执行原 command 文件；任务面板不会自动启动它们。").font(.caption).foregroundStyle(.secondary)
                                ForEach(s.commands) { command in
                                    HStack {
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(command.name).font(.subheadline)
                                            Text(command.relativePath).font(.caption2).foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        Button("运行") { model.runCommand(command) }
                                        if model.hasCardTemplate(command) {
                                            Button("查看") { model.showCardTemplate(command) }
                                                .help("查看文献卡片模板")
                                                .accessibilityLabel("查看文献卡片模板")
                                        }
                                    }.padding(12).background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 8))
                                }
                            } else {
                            Text("当前任务").font(.subheadline).foregroundStyle(.secondary)
                            ForEach(s.rows.filter { category($0) == current }) { row in
                                TaskCard(row: row)
                                if row.formulaApp == true {
                                    CodexWebWindows(online: row.formulaAppOnline == true, turns: row.formulaAppTurns, observation: row.formulaAppWindows)
                                } else if let slots = row.formulaSlots { FormulaWindowView(slots: slots) }

                            }
                            if !s.rows.contains(where: { category($0) == current }) { Text("当前没有运行任务").foregroundStyle(.secondary) }
                            Divider()
                            Text("最近结束的任务").font(.subheadline)
                            ForEach(s.ended.filter { category($0) == current }) { row in TaskCard(row: row) }
                            if !s.ended.contains(where: { category($0) == current }) { Text("暂无结束结果").font(.caption).foregroundStyle(.secondary) }
                            }
                            ForEach(s.warnings.filter { !$0.contains("附件") }, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
                        }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                Divider()
                HStack {
                    Text(Date(timeIntervalSince1970: s.updated), style: .time).font(.caption2).foregroundStyle(.secondary)
                    Spacer()
                    Button("打开工作台") { NSWorkspace.shared.open(URL(string: "http://127.0.0.1:8767")!) }.buttonStyle(.borderless).font(.caption)
                }.padding(12)
            } else {
                ProgressView("正在读取任务…").frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            if !model.error.isEmpty { Text(model.error).font(.caption).foregroundStyle(.orange).padding(12) }
        }.frame(minWidth: 720, minHeight: 420).background(.regularMaterial)
            .sheet(isPresented: Binding(get: { model.cardTemplateURL != nil }, set: { if !$0 { model.cardTemplateURL = nil } })) {
                if let url = model.cardTemplateURL {
                    VStack(spacing: 0) {
                        HStack {
                            Text("文献卡片模板").font(.headline)
                            Spacer()
                            Button("关闭") { model.cardTemplateURL = nil }.keyboardShortcut(.cancelAction)
                        }.padding(16)
                        Divider()
                        CardTemplateDocument(url: url)
                    }.frame(minWidth: 660, idealWidth: 760, minHeight: 480, idealHeight: 620)
                }
            }
    }
}

struct AppTaskTab: Decodable, Identifiable {
    let id: String, state: String, checked: String
}
struct AppWindowObservation: Decodable {
    let registered: Int?
    let tabs: [AppTaskTab]?
}

struct CodexWebWindows: View {
    let online: Bool
    let turns: Int?
    let observation: AppWindowObservation?
    let bundle = "dev.codexwebgpt.launcher"
    var body: some View {
        let apps = NSRunningApplication.runningApplications(withBundleIdentifier: bundle)
        let pids = Set(apps.map { Int($0.processIdentifier) })
        let windows = (CGWindowListCopyWindowInfo(.optionAll, kCGNullWindowID) as? [[String: Any]] ?? [])
            .compactMap { window -> (Int, Bool)? in
                // The 6.2 launcher sets its main window minimum to 720 × 600.
                // Electron also registers menu strips and a small helper surface at layer zero.
                guard pids.contains(window[kCGWindowOwnerPID as String] as? Int ?? -1),
                      (window[kCGWindowLayer as String] as? Int) == 0,
                      let bounds = window[kCGWindowBounds as String] as? [String: Any],
                      (bounds["Width"] as? Double ?? 0) >= 720, (bounds["Height"] as? Double ?? 0) >= 600,
                      let number = window[kCGWindowNumber as String] as? Int else { return nil }
                return (number, window[kCGWindowIsOnscreen as String] as? Bool ?? false)
            }.sorted { $0.0 < $1.0 }
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Codex Web GPT 窗口").font(.headline)
                Spacer()
                Button("查看 App") {
                    if let app = apps.first { app.unhide(); app.activate(options: []) }
                }.disabled(apps.isEmpty)
            }
            Text(online ? "已连接 · App 当前网页任务 " + (turns.map { String($0) } ?? "待观测") : "App 未就绪")
            if let count = observation?.registered, let tabs = observation?.tabs {
                ForEach(tabs) { tab in
                    HStack {
                        Text("任务页 " + String(tab.id.prefix(8))).font(.system(.caption, design: .monospaced))
                            .help(tab.id)
                        Text(tab.state)
                        Spacer()
                        Text(tab.checked).monospacedDigit().foregroundStyle(.secondary)
                    }.font(.caption)
                }
                if tabs.count < count {
                    Text("另有 " + String(count - tabs.count) + " 个任务页待观测").font(.caption)
                }
                if count == 0 { Text("当前没有已登记的任务页").font(.caption) }
            } else {
                Text("任务页状态待观测").font(.caption)
            }
            Text(windows.isEmpty ? "当前未观测到窗口" : windows.map { "窗口 #" + String($0.0) + ($0.1 ? " · 屏幕可见" : " · 当前屏幕未显示") }.joined(separator: "、"))
                .font(.caption).foregroundStyle(.secondary)
        }.padding(12).background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 8))
    }
}

struct FormulaSlot: Decodable, Identifiable {
    let id: String, state: String, checked: String
    let previous: String?
    let pageLoad: String?
    let effort: String?
    let batch: Int?
    let imageWarning: Bool
}

struct FormulaWindowView: View {
    let slots: [FormulaSlot]

    func color(_ state: String) -> Color {
        switch state {
        case "生成中": return .green
        case "准备上传", "上传中", "核对模型", "收取中": return .blue
        case "需登录", "需验证", "额度受限", "网页报错", "空回答", "生成已停止", "发送前受阻": return .orange
        case "待收回答": return .purple
        default: return .secondary
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("公式专窗 · 20 个标签页").font(.headline)
            Text("最近 60 秒 · 生成中 \(slots.filter { $0.state == "生成中" }.count)  ·  空闲 \(slots.filter { $0.state == "空闲" }.count)  ·  图片异常 \(slots.filter { $0.imageWarning }.count)  ·  待观测 \(slots.filter { $0.state == "待观测" }.count)")
                .font(.caption).foregroundStyle(.secondary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 100),spacing: 5)], spacing: 5) {
                ForEach(slots) { slot in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 3) {
                        Text(slot.id).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        Text(slot.state).font(.caption).foregroundStyle(color(slot.state))
                        if slot.imageWarning {
                            Image(systemName: "exclamationmark.triangle.fill").font(.caption2).foregroundStyle(.red)
                        }
                        Spacer(minLength: 0)
                        }
                        if let effort = slot.effort {
                            Text(effort).font(.caption2).foregroundStyle(.secondary)
                        }
                        if let load = slot.pageLoad, !load.isEmpty {
                            Text(load).font(.caption2).foregroundStyle(.secondary)
                        }
                        if let previous = slot.previous, !previous.isEmpty {
                            Text("上次 · " + previous).font(.caption2).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(5).background(Color.primary.opacity(0.05),in: RoundedRectangle(cornerRadius: 4))
                    .help("槽位 \(slot.id) · \(slot.state)" + (slot.batch.map { " · 第 \($0) 批" } ?? "") +
                          (slot.imageWarning ? " · 图片异常，需对照原 PDF" : "") +
                          (slot.checked.isEmpty ? "" : " · 上次网页观测 \(slot.checked)") +
                          (slot.previous.flatMap { $0.isEmpty ? nil : " · 当时为 " + $0 } ?? ""))
                }
            }
            DisclosureGroup("状态说明") {
                Text("空闲表示已观察到空白首页。蓝色表示核对模型、准备上传、页面实际上传或正在收取。绿色表示网页正在生成，紫色表示请求已提交并等待回答。回答已保存表示已收取网页原文。橙色表示登录、验证、额度、发送前受阻、网页报错、生成停止或空回答。草稿或附件占用、归属待核对单独显示。红色三角表示该页有图片提示或加载失败，可与其他状态同时出现。超过 60 秒或缺少有效观测显示待观测，未绑定页面显示未登记。")
                    .font(.caption).foregroundStyle(.secondary).frame(maxWidth: .infinity,alignment: .leading)
            }.font(.caption)
        }
    }
}

struct CompactPageGrid: View {
    let grid: PageGrid
    func color(_ cell: PageGridCell) -> Color {
        let lane = ["cards": Color.blue, "review": Color.purple, "correction": Color.green][cell.lane ?? ""] ?? Color.blue
        switch cell.severity {
        case "critical": return Color(red: 0.42, green: 0.02, blue: 0.02)
        case "warning": return .orange.opacity(0.82)
        case "unavailable": return Color(red: 0.30, green: 0.30, blue: 0.30)
        case "muted", "queue_wait": return lane.opacity(0.80)
        default: break
        }
        // Normal protection, running and queue all use the same task color.
        // Empty/idle cells still get a soft task color rather than gray.
        if cell.lane == nil && (cell.status == "idle" || cell.status == "empty" || cell.status == "unobserved") {
            return .clear
        }
        return lane.opacity(0.80)
    }
    var body: some View {
        LazyVGrid(columns: Array(repeating: GridItem(.fixed(8), spacing: 2), count: 20), spacing: 2) {
            ForEach(grid.cells) { cell in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(color(cell))
                    .overlay(RoundedRectangle(cornerRadius: 1.5).stroke(Color.primary.opacity(0.12), lineWidth: 0.5))
                    .frame(width: 8, height: 8)
                    .help(cell.tooltip)
                    .accessibilityLabel(cell.tooltip)
            }
        }.frame(width: 198, height: 48)
            .fixedSize()
            .help(grid.legend)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("20页任务分配，20列5行")
    }
}

struct CardTemplateDocument: NSViewRepresentable {
    let url: URL
    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.allowsMagnification = true
        view.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        return view
    }
    func updateNSView(_ view: WKWebView, context: Context) {}
}

struct TaskCard: View {
    let row: TaskRow
    var body: some View {
        VStack(alignment:.leading,spacing:8) {
            HStack {
                Label(row.label,systemImage:row.icon).font(.system(size:12,weight:.medium)).foregroundStyle(.secondary)
                Spacer()
                Text(row.state).font(.caption).foregroundStyle(row.state.contains("停滞") || row.state.contains("阻塞") || row.state.contains("失败") || row.state.contains("核验") || row.state.contains("需处理") || row.state.contains("等待附件") ? .orange : .mint)
            }
            Text(row.title).font(.system(size:14,weight:.medium)).lineLimit(2).textSelection(.enabled)
            if let fraction=row.progress { ProgressView(value:fraction).tint(.mint) }
            if !row.detail.isEmpty { Text(row.detail).font(.caption).foregroundStyle(.secondary).lineLimit(3).textSelection(.enabled) }
            HStack {
                if !row.issue.isEmpty { Text(row.issue).foregroundStyle(.orange) }
                Spacer()
                if let elapsed=row.elapsed { Text(elapsed < 60 ? "\(elapsed)秒" : "\(elapsed / 60)分\(elapsed % 60)秒").foregroundStyle(.tertiary) }
                if let path=row.resultPath {
                    Button("查看结果") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath:path)]) }.buttonStyle(.borderless)
                }
            }.font(.caption2)
        }.padding(14).background(Color.primary.opacity(0.045),in:RoundedRectangle(cornerRadius:13))
    }
}

class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var item: NSStatusItem!
    var model: Model!
    func applicationDidFinishLaunching(_ notification: Notification) {
        let root = Bundle.main.object(forInfoDictionaryKey: "TaskProjectRoot") as? String ?? FileManager.default.currentDirectoryPath
        model = Model(root: root)
        let view = PanelView(model: model) { [weak self] pinned in self?.window.level = pinned ? .floating : .normal }
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 820, height: 620), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "任务状态"
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("TaskStatusPanel")
        window.contentView = NSHostingView(rootView: view)
        window.minSize = NSSize(width: 720, height: 420)
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        if let screen = NSScreen.main, !window.setFrameUsingName("TaskStatusPanel") {
            let frame = screen.visibleFrame
            window.setFrameOrigin(NSPoint(x: frame.maxX - 840, y: frame.maxY - 640))
        }
        if window.frame.width < 720 { window.setContentSize(NSSize(width: 820, height: 620)) }
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "waveform.path", accessibilityDescription: "任务状态")
        let menu = NSMenu()
        let show = menu.addItem(withTitle: "显示任务面板", action: #selector(showPanel), keyEquivalent: ""); show.target = self
        menu.addItem(NSMenuItem.separator())
        let quit = menu.addItem(withTitle: "退出任务面板", action: #selector(quitApp), keyEquivalent: "q"); quit.target = self
        item.menu = menu
        window.orderFrontRegardless()
        model.start()
        if let position = CommandLine.arguments.firstIndex(of: "--preview"), CommandLine.arguments.count > position + 1 {
            let destination = CommandLine.arguments[position + 1]
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                if let view = self.window.contentView, let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
                    view.cacheDisplay(in: view.bounds, to: bitmap)
                    try? bitmap.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: destination))
                }
                NSApplication.shared.terminate(nil)
            }
        }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { sender.orderOut(nil); return false }
    @objc func showPanel() { window.orderFrontRegardless() }
    @objc func quitApp() { NSApplication.shared.terminate(nil) }
}
let application = NSApplication.shared
application.setActivationPolicy(.accessory)
let delegate = AppDelegate()
application.delegate = delegate
application.run()
