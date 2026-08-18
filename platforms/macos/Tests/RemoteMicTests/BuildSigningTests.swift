import Foundation
import Testing

@Suite("Build signing")
struct BuildSigningTests {
    @Test func releaseArtifactsSupportMacOS15WithAdaptiveMacOS26Styling() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let package = try String(
            contentsOf: root.appendingPathComponent("Package.swift"),
            encoding: .utf8
        )
        let buildApp = try String(
            contentsOf: root.appendingPathComponent("scripts/build-app.sh"),
            encoding: .utf8
        )
        let verifyApp = try String(
            contentsOf: root.appendingPathComponent("scripts/verify-app.sh"),
            encoding: .utf8
        )
        let buildDriver = try String(
            contentsOf: root.appendingPathComponent("scripts/build-doubao-driver.sh"),
            encoding: .utf8
        )
        let compatibilityStyles = try String(
            contentsOf: root.appendingPathComponent(
                "Sources/RemoteMic/CompatibilityStyles.swift"
            ),
            encoding: .utf8
        )

        #expect(package.contains("platforms: [.macOS(.v15)]"))
        #expect(buildApp.contains("arm64-apple-macosx15.0"))
        #expect(verifyApp.contains("minos 15\\.0"))
        #expect(verifyApp.contains("verify_runs_on_macos_15"))
        #expect(verifyApp.contains("newer than the supported macOS 15.0"))
        #expect(buildDriver.contains("MACOSX_DEPLOYMENT_TARGET=15.0"))
        #expect(buildDriver.contains("-mmacosx-version-min=15.0"))
        #expect(compatibilityStyles.contains("#available(macOS 26.0, *)"))
        #expect(compatibilityStyles.contains("buttonStyle(.bordered)"))
        #expect(compatibilityStyles.contains("background(.regularMaterial"))
    }

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
        #expect(source.contains("SIGN_OPTIONS=()"))
        #expect(source.contains("SIGN_OPTIONS=(--options runtime)"))
        #expect(source.contains("\"${SIGN_OPTIONS[@]}\""))
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

    @Test func aboutImagesAreCopiedUnchangedAndVerified() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let buildSource = try String(
            contentsOf: root.appendingPathComponent("scripts/build-app.sh"),
            encoding: .utf8
        )
        let verifySource = try String(
            contentsOf: root.appendingPathComponent("scripts/verify-app.sh"),
            encoding: .utf8
        )

        #expect(buildSource.contains("SHARED_ABOUT_DIR=\"$ROOT/../shared/about\""))
        #expect(buildSource.contains("AuthorDouyin.jpg AuthorXiaohongshu.jpg"))
        #expect(buildSource.contains("ditto --norsrc --noextattr --noqtn --noacl"))
        #expect(verifySource.contains("AuthorDouyin.jpg"))
        #expect(verifySource.contains("AuthorXiaohongshu.jpg"))
        #expect(verifySource.components(separatedBy: "cmp -s").count == 3)
    }
}
