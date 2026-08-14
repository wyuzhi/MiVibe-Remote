import Foundation
import Testing
@testable import RemoteMic

@Suite("About page")
struct AboutViewTests {
    @Test func exposesRequestedAuthorContacts() {
        #expect(AboutInformation.appName == "MiVibe Remote")
        #expect(AboutInformation.author == "起司")
        #expect(AboutInformation.weChatID == "wydyid")
        #expect(AboutInformation.douyinAccount == "@起司")
        #expect(AboutInformation.douyinID == "56257686125")
        #expect(AboutInformation.xiaohongshuAccount == "起司")
        #expect(AboutInformation.xiaohongshuID == "5668049267")
    }

    @Test func formatsCurrentVersionAndBuildWithoutInventingValues() {
        #expect(AboutInformation.versionText(infoDictionary: [
            "CFBundleShortVersionString": "0.1.10",
            "CFBundleVersion": "11",
        ]) == "版本 0.1.10（11）")
        #expect(AboutInformation.versionText(infoDictionary: [
            "CFBundleShortVersionString": "0.1.10",
        ]) == "版本 0.1.10")
        #expect(AboutInformation.versionText(infoDictionary: [:]) == "版本未知")
    }

    @Test func sharedAuthorImagesExistAtTheirCanonicalPaths() {
        let macRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let sharedAbout = macRoot
            .deletingLastPathComponent()
            .appendingPathComponent("shared/about", isDirectory: true)

        let douyin = sharedAbout.appendingPathComponent("AuthorDouyin.jpg")
        let xiaohongshu = sharedAbout.appendingPathComponent("AuthorXiaohongshu.jpg")
        #expect(FileManager.default.fileExists(atPath: douyin.path))
        #expect(FileManager.default.fileExists(atPath: xiaohongshu.path))
        #expect((try? Data(contentsOf: douyin).isEmpty) == false)
        #expect((try? Data(contentsOf: xiaohongshu).isEmpty) == false)
    }

    @Test func everyContactCardOffersAnAccessibleLargeOriginalImage() throws {
        let macRoot = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: macRoot.appendingPathComponent("Sources/RemoteMic/AboutView.swift"),
            encoding: .utf8
        )

        #expect(source.contains("Label(\"查看大图\""))
        #expect(source.contains(".sheet(isPresented: $showingLargeImage)"))
        #expect(source.contains("AboutImagePreview("))
        #expect(source.contains(".frame(maxWidth: 720)"))
        #expect(source.contains(".scaledToFit()"))
        #expect(source.contains("查看\\(platform)联系图片大图"))
        #expect(source.contains(".keyboardShortcut(.cancelAction)"))
    }
}
