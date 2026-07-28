import Foundation
import Testing

@Suite("App lifecycle")
struct AppLifecycleTests {
    @Test func menuBarUtilityHasClearExitPathsAndDoesNotMinimizeIntoDock() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let appSource = try String(
            contentsOf: root.appendingPathComponent("Sources/RemoteMic/RemoteMicApp.swift"),
            encoding: .utf8
        )
        let settingsSource = try String(
            contentsOf: root.appendingPathComponent("Sources/RemoteMic/SettingsView.swift"),
            encoding: .utf8
        )

        #expect(appSource.contains("configureMainMenu()"))
        #expect(appSource.contains("title: \"退出 MiVibe Remote\""))
        #expect(appSource.contains("keyEquivalent: \"q\""))
        #expect(appSource.contains("styleMask: [.titled, .closable, .resizable]"))
        #expect(!appSource.contains(".miniaturizable"))
        #expect(settingsSource.contains("Text(\"退出应用\")"))
        #expect(settingsSource.contains("NSApp.terminate(nil)"))
    }
}
