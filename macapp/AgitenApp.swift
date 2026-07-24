// Agiten — 네이티브 macOS 채팅 앱 (SwiftUI)
//
// 채팅 UI는 네이티브, 두뇌(모델)+손발(자동화 엔진)은 파이썬 서버가 담당한다.
// 앱을 켜면 파이썬 서버(scripts/serve.py)가 아직 안 떠 있으면 자동으로 띄우고,
// http://localhost:8000 으로 대화한다.

import SwiftUI
import AppKit

// 저장소 경로(이 맥 기준). 서버를 여기서 실행한다.
let REPO_PATH = "/Users/hobak/Agiten"
let SERVER_URL = "http://localhost:8000"

// ---------------------------------------------------------------- 모델

enum Bubble: Equatable {
    case me(String)          // 사용자
    case bot(String)         // 비서 최종 답변
    case think(String)       // 생각(연한 글씨)
    case call(String, String) // 도구호출: 이름, 인자
    case result(String, Bool) // 결과 문자열, ok 여부
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

    // 서버가 안 떠 있으면 파이썬 서버를 자식 프로세스로 실행
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
            for e in (j["events"] as? [[String: Any]]) ?? [] {
                appendEvent(e)
            }
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

// ---------------------------------------------------------------- 뷰

struct BubbleView: View {
    let bubble: Bubble
    var body: some View {
        switch bubble {
        case .me(let t):
            HStack { Spacer()
                Text(t).padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Color.accentColor).foregroundColor(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 15))
                    .frame(maxWidth: 460, alignment: .trailing)
            }
        case .bot(let t):
            HStack {
                Text(t).textSelection(.enabled).padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Color(nsColor: .controlBackgroundColor))
                    .clipShape(RoundedRectangle(cornerRadius: 15))
                    .frame(maxWidth: 460, alignment: .leading)
                Spacer()
            }
        case .think(let t):
            HStack { Text("💭 \(t)").font(.caption).italic().foregroundColor(.secondary); Spacer() }
        case .call(let name, let args):
            HStack {
                (Text("⚙ \(name) ").bold() + Text(args))
                    .font(.system(.caption, design: .monospaced))
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(Color.accentColor.opacity(0.14))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                Spacer()
            }
        case .result(let t, let ok):
            HStack {
                Text(t).font(.system(.caption, design: .monospaced))
                    .foregroundColor(ok ? .secondary : .red).lineLimit(3)
                Spacer()
            }
        }
    }
}

struct ContentView: View {
    @StateObject var model = ChatModel()

    var body: some View {
        VStack(spacing: 0) {
            // 헤더
            HStack(spacing: 8) {
                Text("🤖").font(.title2)
                Text("Agiten").font(.headline)
                Text("— 내 자동화 비서").foregroundColor(.secondary).font(.subheadline)
                Spacer()
                Circle().fill(model.ready ? Color.green : Color.red).frame(width: 8, height: 8)
                Text(model.statusText).font(.caption).foregroundColor(.secondary)
            }
            .padding(12)
            .background(Color(nsColor: .windowBackgroundColor))
            Divider()

            // 메시지
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if model.items.isEmpty {
                            Text("안녕하세요! 저는 회원님이 처음부터 만든 자동화 비서예요.\n\n" +
                                 "예:  “이 폴더에 뭐 있어?”   “test.py 만들고 실행해줘”   “파일 지워줘”\n\n" +
                                 "실제로 파일을 만들고 명령을 실행해요. 위험한 작업은 아래 ‘실행 허용’을 켜야 돌아갑니다.")
                                .foregroundColor(.secondary).font(.callout)
                                .frame(maxWidth: .infinity, alignment: .center)
                                .padding(.top, 60).padding(.horizontal, 40)
                        }
                        ForEach(model.items) { item in BubbleView(bubble: item.bubble).id(item.id) }
                    }
                    .padding(16)
                }
                .onChange(of: model.items.count) { _, _ in
                    if let last = model.items.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
                }
            }

            Divider()
            // 입력부
            VStack(spacing: 8) {
                HStack {
                    Toggle(isOn: $model.allow) { Text("⚠ 위험 작업 실행 허용 (파일 쓰기·명령 실행)").font(.caption) }
                        .toggleStyle(.checkbox)
                    Spacer()
                    Button("대화 초기화") { model.reset() }.font(.caption).buttonStyle(.link)
                }
                HStack(spacing: 8) {
                    TextField("메시지를 입력하세요…", text: $model.input, axis: .vertical)
                        .textFieldStyle(.roundedBorder).lineLimit(1...5)
                        .onSubmit { model.send() }
                    Button(action: { model.send() }) {
                        Text("보내기").padding(.horizontal, 6)
                    }
                    .keyboardShortcut(.return, modifiers: [])
                    .disabled(!model.ready || model.sending)
                }
            }
            .padding(12)
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(minWidth: 560, minHeight: 480)
        .onAppear { model.onAppear() }
        .onDisappear { model.shutdown() }
    }
}

@main
struct AgitenApp: App {
    var body: some Scene {
        WindowGroup("Agiten") { ContentView() }
            .windowResizability(.contentSize)
    }
}
