import Foundation
import Testing
@testable import RemoteMic

@Suite("Application updater")
struct AppUpdaterTests {
    private let validPublicKey = Data(repeating: 0x2a, count: 32).base64EncodedString()

    @Test func acceptsHTTPSFeedAnd32ByteEd25519PublicKey() throws {
        let configuration = try #require(UpdateConfiguration(infoDictionary: [
            "SUFeedURL": "https://updates.example.com/mac/appcast.xml",
            "SUPublicEDKey": validPublicKey,
        ]))

        #expect(configuration.feedURL.absoluteString ==
            "https://updates.example.com/mac/appcast.xml")
        #expect(configuration.publicKey == validPublicKey)
    }

    @Test func rejectsIncompleteOrUnsafeConfiguration() {
        #expect(UpdateConfiguration(infoDictionary: [:]) == nil)
        #expect(UpdateConfiguration(infoDictionary: [
            "SUFeedURL": "http://updates.example.com/mac/appcast.xml",
            "SUPublicEDKey": validPublicKey,
        ]) == nil)
        #expect(UpdateConfiguration(infoDictionary: [
            "SUFeedURL": "https://updates.example.com/mac/appcast.xml",
            "SUPublicEDKey": Data(repeating: 0x2a, count: 31).base64EncodedString(),
        ]) == nil)
        #expect(UpdateConfiguration(infoDictionary: [
            "SUFeedURL": "https://updates.example.com/mac/appcast.xml",
            "SUPublicEDKey": "not-base64",
        ]) == nil)
        #expect(UpdateConfiguration(infoDictionary: [
            "SUFeedURL": "https://member:secret@updates.example.com/mac/appcast.xml",
            "SUPublicEDKey": validPublicKey,
        ]) == nil)
        #expect(UpdateConfiguration(infoDictionary: [
            "SUFeedURL": "https://updates.example.com/mac/appcast.xml?token=secret",
            "SUPublicEDKey": validPublicKey,
        ]) == nil)
    }

    @Test func bundlePolicyChecksPeriodicallyWithoutSilentInstall() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let plistData = try Data(contentsOf: root.appendingPathComponent("Resources/Info.plist"))
        let plist = try #require(
            PropertyListSerialization.propertyList(from: plistData, format: nil)
                as? [String: Any]
        )

        #expect(plist["SUEnableAutomaticChecks"] as? Bool == true)
        #expect(plist["SUAllowsAutomaticUpdates"] as? Bool == false)
        #expect(plist["SUAutomaticallyUpdate"] as? Bool == false)
        #expect((plist["SUScheduledCheckInterval"] as? NSNumber)?.intValue == 86_400)
        #expect(plist["SUFeedURL"] == nil)
        #expect(plist["SUPublicEDKey"] == nil)
    }
}
