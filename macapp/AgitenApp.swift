// Agiten — 네이티브 macOS 채팅 앱 (SwiftUI) · 모던 화이트 + 사이드바 기록
//
// 왼쪽 사이드바에 지난 대화 기록, 오른쪽에 채팅. 대화는 디스크에 저장된다.
// 두뇌(모델)+손발(자동화 엔진)은 파이썬 서버(scripts/serve.py)가 담당한다.

import SwiftUI
import AppKit

let REPO_PATH = "/Users/hobak/Agiten"
let SERVER_URL = "http://localhost:8000"

// ---------------------------------------------------------------- 색상 (모던 화이트)

extension Color {
    static let agBg     = Color.white
    static let agSide   = Color(red: 0.965, green: 0.97, blue: 0.978)
    static let agPanel  = Color(red: 0.975, green: 0.978, blue: 0.985)
    static let agLine   = Color(red: 0.90, green: 0.915, blue: 0.935)
    static let agInk    = Color(red: 0.11, green: 0.12, blue: 0.15)
    static let agMuted  = Color(red: 0.52, green: 0.55, blue: 0.61)
    static let agBrand  = Color(red: 0.29, green: 0.33, blue: 0.83)
    static let agBot    = Color(red: 0.955, green: 0.963, blue: 0.975)
    static let agChip   = Color(red: 0.93, green: 0.95, blue: 1.0)
    static let agChipTx = Color(red: 0.22, green: 0.29, blue: 0.72)
    static let agOk     = Color(red: 0.13, green: 0.68, blue: 0.38)
    static let agSel    = Color(red: 0.90, green: 0.92, blue: 1.0)
}

// ---------------------------------------------------------------- 데이터 (Codable 로 저장)

struct ChatItem: Identifiable, Codable, Equatable {
    var id = UUID()
    var kind: String          // me / bot / think / call / result
    var text: String
    var arg: String = ""      // call 인자
    var ok: Bool = true       // result 성공 여부
}

struct Session: Identifiable, Codable {
    var id = UUID()
    var title: String = "새 대화"
    var date: Date = Date()
    var items: [ChatItem] = []
}

// ---------------------------------------------------------------- 저장소

enum Store {
    static var url: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Agiten", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("sessions.json")
    }
    static func load() -> [Session] {
        guard let data = try? Data(contentsOf: url),
              let s = try? JSONDecoder().decode([Session].self, from: data) else { return [] }
        return s
    }
    static func save(_ sessions: [Session]) {
        if let data = try? JSONEncoder().encode(sessions) { try? data.write(to: url) }
    }
}

// ---------------------------------------------------------------- 모델

@MainActor
final class ChatModel: ObservableObject {
    @Published var sessions: [Session] = []
    @Published var currentId: UUID = UUID()
    @Published var items: [ChatItem] = []
    @Published var input: String = ""
    @Published var allow: Bool = false
    @Published var ready: Bool = false
    @Published var statusText: String = "확인 중…"
    @Published var sending: Bool = false

    private var serverProc: Process?

    func onAppear() {
        sessions = Store.load()
        if sessions.isEmpty { newSession() }
        else { currentId = sessions[0].id; items = sessions[0].items }
        launchServerIfNeeded()
        Task { await pollLoop() }
    }

    // ---- 세션 관리
    func newSession() {
        let s = Session()
        sessions.insert(s, at: 0)
        currentId = s.id
        items = []
        resetServer()
        persist()
    }

    func select(_ id: UUID) {
        guard id != currentId, let s = sessions.first(where: { $0.id == id }) else { return }
        syncCurrent()
        currentId = id
        items = s.items
        resetServer()   // 모델 문맥은 새로 시작(과거 대화 열람 중심)
    }

    func deleteSession(_ id: UUID) {
        sessions.removeAll { $0.id == id }
        if sessions.isEmpty { newSession() }
        else if currentId == id { currentId = sessions[0].id; items = sessions[0].items; resetServer() }
        persist()
    }

    private func syncCurrent() {
        guard let idx = sessions.firstIndex(where: { $0.id == currentId }) else { return }
        sessions[idx].items = items
        if let first = items.first(where: { $0.kind == "me" }) {
            sessions[idx].title = String(first.text.prefix(28))
        }
        sessions[idx].date = Date()
    }

    private func persist() { syncCurrent(); Store.save(sessions) }

    private func bumpToTop() {
        guard let idx = sessions.firstIndex(where: { $0.id == currentId }), idx != 0 else { return }
        let s = sessions.remove(at: idx); sessions.insert(s, at: 0)
    }

    // ---- 서버/네트워크
    func launchServerIfNeeded() {
        Task {
            if await reachable() { return }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = ["python3", "-u", "scripts/serve.py", "--port", "8000"]
            p.currentDirectoryURL = URL(fileURLWithPath: REPO_PATH)
            do { try p.run(); self.serverProc = p } catch {}
        }
    }
    func reachable() async -> Bool {
        guard let url = URL(string: "\(SERVER_URL)/status") else { return false }
        var req = URLRequest(url: url); req.timeoutInterval = 1.5
        return (try? await URLSession.shared.data(for: req)) != nil
    }
    func pollLoop() async {
        while true { await pollStatus(); try? await Task.sleep(nanoseconds: 3_000_000_000) }
    }
    func pollStatus() async {
        guard let url = URL(string: "\(SERVER_URL)/status") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let j = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
            ready = (j["ready"] as? Bool) ?? false
            let model = (j["model"] as? String) ?? ""
            statusText = ready ? (model.isEmpty ? "준비됨" : model) : ((j["detail"] as? String) ?? "학습 중…")
        } catch { ready = false; statusText = "서버 대기 중…" }
    }
    func resetServer() {
        Task {
            guard let url = URL(string: "\(SERVER_URL)/reset") else { return }
            var req = URLRequest(url: url); req.httpMethod = "POST"
            _ = try? await URLSession.shared.data(for: req)
        }
    }

    // ---- 전송
    func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, ready, !sending else { return }
        input = ""; sending = true
        items.append(ChatItem(kind: "me", text: text))
        bumpToTop(); persist()
        Task { await doSend(text) }
    }
    func doSend(_ text: String) async {
        defer { sending = false }
        guard let url = URL(string: "\(SERVER_URL)/chat") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["message": text, "allow": allow])
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            let j = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
            if let err = j["error"] as? String {
                items.append(ChatItem(kind: "result", text: "⚠ \(err)", ok: false))
            } else {
                for e in (j["events"] as? [[String: Any]]) ?? [] { appendEvent(e) }
            }
        } catch {
            items.append(ChatItem(kind: "result", text: "⚠ 서버 오류: \(error.localizedDescription)", ok: false))
        }
        persist()
    }
    func appendEvent(_ e: [String: Any]) {
        let kind = e["kind"] as? String ?? ""
        switch kind {
        case "think":
            if let t = e["data"] as? String { items.append(ChatItem(kind: "think", text: t)) }
        case "call":
            if let d = e["data"] as? [String: Any] {
                let name = d["name"] as? String ?? "?"
                let args = d["args"] as? [String: Any] ?? [:]
                let argStr = (try? JSONSerialization.data(withJSONObject: args))
                    .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
                items.append(ChatItem(kind: "call", text: name, arg: argStr))
            }
        case "result":
            if let s = e["data"] as? String {
                let ok = !s.contains("\"ok\": false") && !s.contains("\"ok\":false")
                items.append(ChatItem(kind: "result", text: "← " + String(s.prefix(240)), ok: ok))
            }
        case "final":
            if let t = e["data"] as? String, !t.isEmpty { items.append(ChatItem(kind: "bot", text: t)) }
        default: break
        }
    }

    func shutdown() { serverProc?.terminate() }
}

// ---------------------------------------------------------------- 말풍선

struct BubbleView: View {
    let item: ChatItem
    var body: some View {
        switch item.kind {
        case "me":
            HStack { Spacer(minLength: 36)
                Text(item.text).foregroundColor(.white)
                    .padding(.horizontal, 15).padding(.vertical, 10)
                    .background(Color.agBrand)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .shadow(color: .agBrand.opacity(0.22), radius: 6, y: 2)
            }
        case "bot":
            HStack {
                Text(item.text).textSelection(.enabled).foregroundColor(.agInk)
                    .padding(.horizontal, 15).padding(.vertical, 10)
                    .background(Color.agBot)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(Color.agLine, lineWidth: 1))
                Spacer(minLength: 36)
            }
        case "think":
            HStack { Text("💭 \(item.text)").font(.caption).italic().foregroundColor(.agMuted); Spacer() }
                .padding(.leading, 4)
        case "call":
            HStack {
                HStack(spacing: 5) {
                    Text("⚙").font(.caption)
                    Text(item.text).font(.system(.caption, design: .monospaced)).bold()
                    Text(item.arg).font(.system(.caption, design: .monospaced)).foregroundColor(.agChipTx.opacity(0.75))
                }
                .foregroundColor(.agChipTx)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Color.agChip)
                .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                Spacer()
            }
        default: // result
            HStack {
                Text(item.text).font(.system(.caption, design: .monospaced))
                    .foregroundColor(item.ok ? .agMuted : .red).lineLimit(3)
                Spacer()
            }.padding(.leading, 4)
        }
    }
}

// ---------------------------------------------------------------- 사이드바

struct Sidebar: View {
    @ObservedObject var model: ChatModel
    var body: some View {
        VStack(spacing: 0) {
            Button(action: { model.newSession() }) {
                HStack { Image(systemName: "square.and.pencil"); Text("새 대화").fontWeight(.medium); Spacer() }
                    .foregroundColor(.agBrand)
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .background(Color.agChip)
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            .buttonStyle(.plain).padding(10)

            Text("대화 기록").font(.caption).foregroundColor(.agMuted)
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 4)

            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(model.sessions) { s in
                        SessionRow(session: s, selected: s.id == model.currentId)
                            .contentShape(Rectangle())
                            .onTapGesture { model.select(s.id) }
                            .contextMenu { Button("삭제", role: .destructive) { model.deleteSession(s.id) } }
                    }
                }.padding(.horizontal, 8)
            }
            Spacer(minLength: 0)
        }
        .background(Color.agSide)
    }
}

struct SessionRow: View {
    let session: Session
    let selected: Bool
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "bubble.left").font(.caption).foregroundColor(selected ? .agBrand : .agMuted)
            VStack(alignment: .leading, spacing: 1) {
                Text(session.title.isEmpty ? "새 대화" : session.title)
                    .font(.callout).foregroundColor(.agInk).lineLimit(1)
                Text(session.date, style: .relative).font(.caption2).foregroundColor(.agMuted)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(selected ? Color.agSel : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

// ---------------------------------------------------------------- 메인

struct ContentView: View {
    @StateObject var model = ChatModel()
    var body: some View {
        NavigationSplitView {
            Sidebar(model: model)
                .navigationSplitViewColumnWidth(min: 200, ideal: 240, max: 320)
        } detail: {
            ChatPane(model: model)
        }
        .preferredColorScheme(.light)
        .onAppear { model.onAppear() }
        .onDisappear { model.shutdown() }
    }
}

struct ChatPane: View {
    @ObservedObject var model: ChatModel
    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Color.agLine)
            messages
            Divider().overlay(Color.agLine)
            composer
        }
        .background(Color.agBg)
        .frame(minWidth: 460, minHeight: 520)
    }

    var header: some View {
        HStack(spacing: 11) {
            Text("🤖").font(.system(size: 22))
            VStack(alignment: .leading, spacing: 1) {
                Text("Agiten").font(.headline).foregroundColor(.agInk)
                Text("내 자동화 비서").font(.caption).foregroundColor(.agMuted)
            }
            Spacer()
            HStack(spacing: 6) {
                Circle().fill(model.ready ? Color.agOk : Color.orange).frame(width: 7, height: 7)
                Text(model.statusText).font(.caption).foregroundColor(.agMuted)
            }
            .padding(.horizontal, 11).padding(.vertical, 6)
            .background(Color.agPanel).clipShape(Capsule())
            .overlay(Capsule().stroke(Color.agLine, lineWidth: 1))
        }
        .padding(.horizontal, 18).padding(.vertical, 12).background(Color.agBg)
    }

    var messages: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 11) {
                    if model.items.isEmpty { emptyState }
                    ForEach(model.items) { item in BubbleView(item: item).id(item.id) }
                }.padding(18)
            }
            .background(Color.agBg)
            .onChange(of: model.items.count) { _, _ in
                if let last = model.items.last { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(last.id, anchor: .bottom) } }
            }
        }
    }

    var emptyState: some View {
        VStack(spacing: 14) {
            Text("🤖").font(.system(size: 44))
            Text("무엇을 도와드릴까요?").font(.title3).fontWeight(.semibold).foregroundColor(.agInk)
            Text("회원님이 처음부터 만든 자동화 비서예요.\n실제로 파일을 만들고 명령을 실행합니다.")
                .multilineTextAlignment(.center).font(.callout).foregroundColor(.agMuted)
            VStack(spacing: 7) {
                ForEach(["이 폴더에 뭐 있어?", "test.py 만들고 실행해줘", "파일 지워줘"], id: \.self) { s in
                    Text(s).font(.callout).foregroundColor(.agChipTx)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(Color.agChip).clipShape(Capsule())
                        .onTapGesture { model.input = s }
                }
            }.padding(.top, 4)
        }
        .frame(maxWidth: .infinity).padding(.top, 46)
    }

    var composer: some View {
        VStack(spacing: 10) {
            HStack {
                Toggle(isOn: $model.allow) {
                    Text("⚠ 위험 작업 실행 허용 (파일 쓰기·명령 실행)").font(.caption).foregroundColor(.agMuted)
                }.toggleStyle(.checkbox)
                Spacer()
            }
            HStack(spacing: 10) {
                TextField("메시지를 입력하세요…", text: $model.input, axis: .vertical)
                    .textFieldStyle(.plain).lineLimit(1...5).foregroundColor(.agInk)
                    .padding(.horizontal, 14).padding(.vertical, 11).background(Color.agBg)
                    .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 13, style: .continuous).stroke(Color.agLine, lineWidth: 1.2))
                    .onSubmit { model.send() }
                Button(action: { model.send() }) {
                    Text("보내기").fontWeight(.semibold).foregroundColor(.white)
                        .padding(.horizontal, 20).padding(.vertical, 12)
                        .background((model.ready && !model.sending) ? Color.agBrand : Color.agMuted.opacity(0.35))
                        .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
                }
                .buttonStyle(.plain).keyboardShortcut(.return, modifiers: []).disabled(!model.ready || model.sending)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 13).background(Color.agBg)
    }
}

@main
struct AgitenApp: App {
    var body: some Scene {
        WindowGroup("Agiten") { ContentView() }
    }
}
