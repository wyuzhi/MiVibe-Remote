import Foundation
import Sparkle

struct UpdateConfiguration: Equatable, Sendable {
    static let feedURLKey = "SUFeedURL"
    static let publicKeyKey = "SUPublicEDKey"

    let feedURL: URL
    let publicKey: String

    init?(infoDictionary: [String: Any]) {
        guard let rawFeedURL = infoDictionary[Self.feedURLKey] as? String,
              let feedURL = URL(string: rawFeedURL),
              feedURL.scheme?.lowercased() == "https",
              feedURL.host != nil,
              feedURL.user == nil,
              feedURL.password == nil,
              feedURL.query == nil,
              feedURL.fragment == nil,
              let rawPublicKey = infoDictionary[Self.publicKeyKey] as? String else {
            return nil
        }

        let publicKey = rawPublicKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let decodedKey = Data(base64Encoded: publicKey), decodedKey.count == 32 else {
            return nil
        }

        self.feedURL = feedURL
        self.publicKey = publicKey
    }

    static func load(from bundle: Bundle = .main) -> UpdateConfiguration? {
        guard let infoDictionary = bundle.infoDictionary else { return nil }
        return UpdateConfiguration(infoDictionary: infoDictionary)
    }
}

@MainActor
final class AppUpdater {
    private let updaterController: SPUStandardUpdaterController?

    var isConfigured: Bool {
        updaterController != nil
    }

    var canCheckForUpdates: Bool {
        updaterController?.updater.canCheckForUpdates ?? false
    }

    init(bundle: Bundle = .main) {
        guard UpdateConfiguration.load(from: bundle) != nil else {
            updaterController = nil
            return
        }

        updaterController = SPUStandardUpdaterController(
            startingUpdater: false,
            updaterDelegate: nil,
            userDriverDelegate: nil
        )
    }

    func start() {
        updaterController?.startUpdater()
    }

    func checkForUpdates(_ sender: Any?) {
        updaterController?.checkForUpdates(sender)
    }
}
