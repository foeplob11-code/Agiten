// Agiten — 네이티브 macOS 채팅 앱 (SwiftUI) · 모던 화이트 디자인
//
// 채팅 UI는 네이티브, 두뇌(모델)+손발(자동화 엔진)은 파이썬 서버가 담당한다.
// 앱을 켜면 파이썬 서버(scripts/serve.py)가 아직 안 떠 있으면 자동으로 띄우고,
// http://localhost:8000 으로 대화한다.

import SwiftUI
import AppKit

let REPO_PATH = "/Users/hobak/Agiten"
let SERVER_URL = "http://localhost:8000"

// ---------------------------------------------------------------- 색상 팔레트 (모던 화이트)

extension Color {
    static let agBg     = Color.white
    static let agPanel  = Color(red: 0.975, green: 0.978, blue: 0.985)
    static let agLine   = Color(red: 0.90, green: 0.915, blue: 0.935)
    static let agInk    = Color(red: 0.11, green: 0.12, blue: 0.15)
    static let agMuted  = Color(red: 0.52, green: 0.55, blue: 0.61)
    static let agBrand  = Color(red: 0.29, green: 0.33, blue: 0.83)   // 인디고
    static let agBot    = Color(red: 0.955, green: 0.963, blue: 0.975)
    static let agChip   = Color(red: 0.93, green: 0.95, blue: 1.0)
    static let agChipTx = Color(red: 0.22, green: 0.29, blue: 0.72)
    static let agOk     = Color(red: 0.13, green: 0.68, blue: 0.38)
}

// ---------------------------------------------------------------- 모델

enum Bubble: Equatable {
    case me(String)
    case bot(String)
    case think(String)
    case call(String, String)
    case result(String, Bool)
}

struct ChatItem: Identifiable {
    let id = UUID()
    let bubble: Bubble
}

@MainActor
final class ChatModel: ObservableObject {
    @Published var items: [ChatItem] = []
    @Published var input: String = ""
    @Published var allow: Bool = false
    @Published var ready: Bool = false
    @Published var statusText: String = "확인 중…"
    @Published var sending: Bool = false

    private var serverProc: Process?

    func onAppear() {
        launchServerIfNeeded()
        Task { await pollLoop() }
    }

    func launchServerIfNeeded() {
        Task {
            if await reachable() { return }
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = ["python3", "-u", "scripts/serve.py", "--port", "8000"]
            p.currentDirectoryURL = URL(fileURLWithPath: REPO_PATH)
            do { try p.run(); self.serverProc = p }
            catch { await MainActor.run { self.statusText = "서버 실행 실패: \(error.localizedDescription)" } }
        }
    }

    func reachable() async -> Bool {
        guard let url = URL(string: "\(SERVER_URL)/status") else { return false }
        var req = URLRequest(url: url); req.timeoutInterval = 1.5
        return (try? await URLSession.shared.data(for: req)) != nil
    }

    func pollLoop() async {
        while true {
            await pollStatus()
            try? await Task.sleep(nanoseconds: 3_000_000_000)
        }
    }

    func pollStatus() async {
        guard let url = URL(string: "\(SERVER_URL)/status") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(from: url)
            let j = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
            self.ready = (j["ready"] as? Bool) ?? false
            let model = (j["model"] as? String) ?? ""
            self.statusText = self.ready ? (model.isEmpty ? "준비됨" : model)
                                         : ((j["detail"] as? String) ?? "학습 중…")
        } catch {
            self.ready = false; self.statusText = "서버 대기 중…"
        }
    }

    func send() {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, ready, !sending else { return }
        input = ""; sending = true
        items.append(ChatItem(bubble: .me(text)))
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
                items.append(ChatItem(bubble: .result("⚠ \(err)", false))); return
            }
            for e in (j["events"] as? [[String: Any]]) ?? [] { appendEvent(e) }
        } catch {
            items.append(ChatItem(bubble: .result("⚠ 서버 오류: \(error.localizedDescription)", false)))
        }
    }

    func appendEvent(_ e: [String: Any]) {
        let kind = e["kind"] as? String ?? ""
        switch kind {
        case "think":
            if let t = e["data"] as? String { items.append(ChatItem(bubble: .think(t))) }
        case "call":
            if let d = e["data"] as? [String: Any] {
                let name = d["name"] as? String ?? "?"
                let args = d["args"] as? [String: Any] ?? [:]
                let argStr = (try? JSONSerialization.data(withJSONObject: args))
                    .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
                items.append(ChatItem(bubble: .call(name, argStr)))
            }
        case "result":
            if let s = e["data"] as? String {
                let ok = !s.contains("\"ok\": false") && !s.contains("\"ok\":false")
                items.append(ChatItem(bubble: .result("← " + String(s.prefix(240)), ok)))
            }
        case "final":
            if let t = e["data"] as? String, !t.isEmpty { items.append(ChatItem(bubble: .bot(t))) }
        default: break
        }
    }

    func reset() {
        items.removeAll()
        Task {
            guard let url = URL(string: "\(SERVER_URL)/reset") else { return }
            var req = URLRequest(url: url); req.httpMethod = "POST"
            _ = try? await URLSession.shared.data(for: req)
        }
    }

    func shutdown() { serverProc?.terminate() }
}

// ---------------------------------------------------------------- 말풍선

struct BubbleView: View {
    let bubble: Bubble
    var body: some View {
        switch bubble {
        case .me(let t):
            HStack { Spacer(minLength: 40)
                Text(t)
                    .foregroundColor(.white)
                    .padding(.horizontal, 15).padding(.vertical, 10)
                    .background(Color.agBrand)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .shadow(color: .agBrand.opacity(0.25), radius: 6, y: 2)
            }
        case .bot(let t):
            HStack {
                Text(t).textSelection(.enabled).foregroundColor(.agInk)
                    .padding(.horizontal, 15).padding(.vertical, 10)
                    .background(Color.agBot)
                    .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(Color.agLine, lineWidth: 1))
                Spacer(minLength: 40)
            }
        case .think(let t):
            HStack { Text("💭 \(t)").font(.caption).italic().foregroundColor(.agMuted); Spacer() }
                .padding(.leading, 4)
        case .call(let name, let args):
            HStack {
                HStack(spacing: 5) {
                    Text("⚙").font(.caption)
                    Text(name).font(.system(.caption, design: .monospaced)).bold()
                    Text(args).font(.system(.caption, design: .monospaced)).foregroundColor(.agChipTx.opacity(0.75))
                }
                .foregroundColor(.agChipTx)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(Color.agChip)
                .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                Spacer()
            }
        case .result(let t, let ok):
            HStack {
                Text(t).font(.system(.caption, design: .monospaced))
                    .foregroundColor(ok ? .agMuted : .red).lineLimit(3)
                Spacer()
            }
            .padding(.leading, 4)
        }
    }
}

// ---------------------------------------------------------------- 메인 화면

struct ContentView: View {
    @StateObject var model = ChatModel()

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(Color.agLine)
            messages
            Divider().overlay(Color.agLine)
            composer
        }
        .background(Color.agBg)
        .frame(minWidth: 580, minHeight: 520)
        .preferredColorScheme(.light)          // 시스템이 다크여도 항상 화이트
        .onAppear { model.onAppear() }
        .onDisappear { model.shutdown() }
    }

    var header: some View {
        HStack(spacing: 11) {
            Text("🤖").font(.system(size: 24))
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
            .background(Color.agPanel)
            .clipShape(Capsule())
            .overlay(Capsule().stroke(Color.agLine, lineWidth: 1))
        }
        .padding(.horizontal, 18).padding(.vertical, 13)
        .background(Color.agBg)
    }

    var messages: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 11) {
                    if model.items.isEmpty { emptyState }
                    ForEach(model.items) { item in BubbleView(bubble: item.bubble).id(item.id) }
                }
                .padding(18)
            }
            .background(Color.agBg)
            .onChange(of: model.items.count) { _, _ in
                if let last = model.items.last { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo(last.id, anchor: .bottom) } }
            }
        }
    }

    var emptyState: some View {
        VStack(spacing: 14) {
            Text("🤖").font(.system(size: 46))
            Text("무엇을 도와드릴까요?").font(.title3).fontWeight(.semibold).foregroundColor(.agInk)
            Text("회원님이 처음부터 만든 자동화 비서예요.\n실제로 파일을 만들고 명령을 실행합니다.")
                .multilineTextAlignment(.center).font(.callout).foregroundColor(.agMuted)
            VStack(spacing: 7) {
                ForEach(["이 폴더에 뭐 있어?", "test.py 만들고 실행해줘", "파일 지워줘"], id: \.self) { s in
                    Text(s).font(.callout).foregroundColor(.agChipTx)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(Color.agChip).clipShape(Capsule())
                }
            }
            .padding(.top, 4)
        }
        .frame(maxWidth: .infinity).padding(.top, 50)
    }

    var composer: some View {
        VStack(spacing: 10) {
            HStack {
                Toggle(isOn: $model.allow) {
                    Text("⚠ 위험 작업 실행 허용 (파일 쓰기·명령 실행)")
                        .font(.caption).foregroundColor(.agMuted)
                }
                .toggleStyle(.checkbox)
                Spacer()
                Button(action: { model.reset() }) {
                    Text("대화 초기화").font(.caption).foregroundColor(.agMuted)
                }.buttonStyle(.plain)
            }
            HStack(spacing: 10) {
                TextField("메시지를 입력하세요…", text: $model.input, axis: .vertical)
                    .textFieldStyle(.plain).lineLimit(1...5)
                    .foregroundColor(.agInk)
                    .padding(.horizontal, 14).padding(.vertical, 11)
                    .background(Color.agBg)
                    .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 13, style: .continuous).stroke(Color.agLine, lineWidth: 1.2))
                    .onSubmit { model.send() }
                Button(action: { model.send() }) {
                    Text("보내기").fontWeight(.semibold).foregroundColor(.white)
                        .padding(.horizontal, 20).padding(.vertical, 12)
                        .background((model.ready && !model.sending) ? Color.agBrand : Color.agMuted.opacity(0.35))
                        .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.return, modifiers: [])
                .disabled(!model.ready || model.sending)
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 13)
        .background(Color.agBg)
    }
}

@main
struct AgitenApp: App {
    var body: some Scene {
        WindowGroup("Agiten") { ContentView() }
            .windowResizability(.contentSize)
    }
}
