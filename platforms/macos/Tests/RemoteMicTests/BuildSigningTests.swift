import Foundation
import Testing

@Suite("Build signing")
struct BuildSigningTests {
    @Test func buildDefaultsToStableAdHocSigning() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: root.appendingPathComponent("scripts/build-app.sh"),
            encoding: .utf8
        )

        #expect(source.contains("CODE_SIGN_IDENTITY"))
        #expect(source.contains("SIGNING_IDENTITY=\"${CODE_SIGN_IDENTITY:--}\""))
        #expect(source.contains("if [[ \"$SIGNING_IDENTITY\" == \"-\" ]]; then"))
        #expect(source.contains("designated => identifier"))
        #expect(!source.contains("security find-identity -p codesigning -v"))
        #expect(!source.contains("git config --get user.email"))
        #expect(!source.contains("codesign --force --deep --sign - \"$APP_DIR\""))
        #expect(source.contains("MIVIBE_APPCAST_URL"))
        #expect(source.contains("MIVIBE_UPDATE_ED25519_PUBLIC_KEY"))
        #expect(source.contains("must not contain credentials, a query string, or a fragment"))
        #expect(source.contains("@executable_path/../Frameworks"))
        #expect(source.contains("Sparkle.framework"))
        #expect(source.contains("XPCServices/Installer.xpc"))
        #expect(source.contains("XPCServices/Downloader.xpc"))
        #expect(!source.contains("MIVIBE_UPDATE_PRIVATE"))
    }

    @Test func sparkleHelpersFollowOfficialManualSigningRecipe() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: root.appendingPathComponent("scripts/build-app.sh"),
            encoding: .utf8
        )

        let preserveEntitlements = "--preserve-metadata=entitlements"
        #expect(source.components(separatedBy: preserveEntitlements).count == 2)
        #expect(source.contains("""
        sign_sparkle_component \\
          "$SPARKLE_VERSION_DIR/XPCServices/Downloader.xpc" \\
          --preserve-metadata=entitlements
        """))
        #expect(!source.contains("for sparkle_component in"))

        let expectedOrder = [
            "sign_sparkle_component \\\n  \"$SPARKLE_VERSION_DIR/XPCServices/Installer.xpc\"",
            "sign_sparkle_component \\\n  \"$SPARKLE_VERSION_DIR/XPCServices/Downloader.xpc\"",
            "sign_sparkle_component \\\n  \"$SPARKLE_VERSION_DIR/Autoupdate\"",
            "sign_sparkle_component \\\n  \"$SPARKLE_VERSION_DIR/Updater.app\"",
            "sign_sparkle_component \\\n  \"$EMBEDDED_SPARKLE\"",
        ]
        let componentOffsets = try expectedOrder.map { component in
            try #require(source.range(of: component)?.lowerBound)
        }
        #expect(componentOffsets == componentOffsets.sorted())
    }
}
