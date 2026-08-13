import Foundation
import Testing

@Suite("App lifecycle")
struct AppLifecycleTests {
    @Test func regularAppHasFastNavigationReopenAndClearExitPaths() throws {
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
        let infoPlist = try String(
            contentsOf: root.appendingPathComponent("Resources/Info.plist"),
            encoding: .utf8
        )

        #expect(appSource.contains("configureMainMenu()"))
        #expect(appSource.contains("appUpdater = AppUpdater()"))
        #expect(appSource.contains("appUpdater?.start()"))
        #expect(appSource.contains("menu.addItem(updateMenuItem())"))
        #expect(appSource.contains("applicationMenu.addItem(updateMenuItem())"))
        #expect(appSource.contains("检查更新…（自动更新未配置）"))
        #expect(appSource.contains("title: \"退出 MiVibe Remote\""))
        #expect(appSource.contains("keyEquivalent: \"q\""))
        #expect(appSource.contains("application.setActivationPolicy(.regular)"))
        #expect(appSource.contains("applicationShouldHandleReopen"))
        #expect(appSource.contains("refreshMenuStatus()\n        showSettings()"))
        #expect(appSource.contains("styleMask: [.titled, .closable, .resizable]"))
        #expect(!appSource.contains(".miniaturizable"))
        #expect(settingsSource.contains("Text(\"退出应用\")"))
        #expect(settingsSource.contains("NSApp.terminate(nil)"))
        #expect(!settingsSource.contains("NavigationSplitView"))
        #expect(!settingsSource.contains("settings-navigation-selection"))
        #expect(settingsSource.contains("ZStack"))
        #expect(settingsSource.contains(".allowsHitTesting(selectedSection =="))
        #expect(infoPlist.contains("<key>LSUIElement</key>"))
        #expect(infoPlist.contains("<false/>"))
    }
}
