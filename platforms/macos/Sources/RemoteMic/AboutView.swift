import AppKit
import SwiftUI

enum AboutInformation {
    static let appName = "MiVibe Remote"
    static let author = "起司"
    static let weChatID = "wydyid"
    static let douyinAccount = "@起司"
    static let douyinID = "56257686125"
    static let xiaohongshuAccount = "起司"
    static let xiaohongshuID = "5668049267"

    static func versionText(infoDictionary: [String: Any]) -> String {
        let shortVersion = (infoDictionary["CFBundleShortVersionString"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let build = (infoDictionary["CFBundleVersion"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)

        switch (shortVersion, build) {
        case let (version?, build?) where !version.isEmpty && !build.isEmpty:
            return "版本 \(version)（\(build)）"
        case let (version?, _) where !version.isEmpty:
            return "版本 \(version)"
        default:
            return "版本未知"
        }
    }
}

struct AboutView: View {
    let updatesConfigured: Bool
    let onCheckForUpdates: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var copiedWeChatID = false
    @State private var copyFeedbackTask: Task<Void, Never>?

    private var versionText: String {
        AboutInformation.versionText(infoDictionary: Bundle.main.infoDictionary ?? [:])
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("关于")
                        .font(.system(size: 25, weight: .semibold))
                    Text("了解 MiVibe Remote，并找到作者\(AboutInformation.author)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                appIdentityCard
                weChatCard
                socialCards

                Text("感谢你使用 MiVibe Remote，把遥控器变成更顺手的创作工具。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 4)
            }
            .padding(22)
            .frame(maxWidth: 900, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .adaptiveSoftTopScrollEdge()
        .background {
            LinearGradient(
                colors: [Color.accentColor.opacity(0.08), Color.clear],
                startPoint: .topLeading,
                endPoint: .center
            )
            .ignoresSafeArea()
        }
        .onDisappear {
            copyFeedbackTask?.cancel()
            copyFeedbackTask = nil
        }
    }

    private var appIdentityCard: some View {
        AboutSurface {
            HStack(spacing: 18) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 82, height: 82)
                    .accessibilityLabel("MiVibe Remote 应用图标")

                VStack(alignment: .leading, spacing: 5) {
                    Text(AboutInformation.appName)
                        .font(.system(size: 25, weight: .bold))
                    Text(versionText)
                        .font(.subheadline.monospacedDigit())
                        .foregroundStyle(.secondary)
                    Label("\(AboutInformation.author)制作", systemImage: "person.crop.circle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color.accentColor)
                        .padding(.top, 2)
                }

                Spacer(minLength: 12)

                VStack(alignment: .trailing, spacing: 6) {
                    Button("检查更新…", systemImage: "arrow.triangle.2.circlepath") {
                        onCheckForUpdates()
                    }
                    .adaptiveGlassButtonStyle()
                    .disabled(!updatesConfigured)
                    .help(
                        updatesConfigured
                            ? "使用 Sparkle 检查 MiVibe Remote 更新"
                            : "此安装包未配置自动更新服务"
                    )

                    if !updatesConfigured {
                        Text("自动更新未配置")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var weChatCard: some View {
        AboutSurface {
            HStack(spacing: 16) {
                Image(systemName: "message.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 42, height: 42)
                    .adaptiveTintedGlassCircle(Color.accentColor.opacity(0.14))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 3) {
                    Text("微信")
                        .font(.headline)
                    Text(AboutInformation.weChatID)
                        .font(.body.monospaced())
                        .textSelection(.enabled)
                    if copiedWeChatID {
                        Label("微信号已复制", systemImage: "checkmark.circle.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.green)
                            .transition(.opacity)
                    } else {
                        Text("复制后可在微信中添加作者起司")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer(minLength: 16)

                Button {
                    copyWeChatID()
                } label: {
                    Label(
                        copiedWeChatID ? "已复制" : "复制微信号",
                        systemImage: copiedWeChatID ? "checkmark" : "doc.on.doc"
                    )
                }
                .adaptiveProminentGlassButtonStyle()
                .buttonBorderShape(.roundedRectangle(radius: 10))
                .accessibilityLabel(copiedWeChatID ? "微信号已复制" : "复制微信号 wydyid")
            }
        }
    }

    private var socialCards: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 14) {
                socialCard(
                    platform: "抖音",
                    account: AboutInformation.douyinAccount,
                    identifierLabel: "抖音号",
                    identifier: AboutInformation.douyinID,
                    resourceName: "AuthorDouyin"
                )
                .frame(minWidth: 230)
                socialCard(
                    platform: "小红书",
                    account: AboutInformation.xiaohongshuAccount,
                    identifierLabel: "小红书号",
                    identifier: AboutInformation.xiaohongshuID,
                    resourceName: "AuthorXiaohongshu"
                )
                .frame(minWidth: 230)
            }

            VStack(spacing: 14) {
                socialCard(
                    platform: "抖音",
                    account: AboutInformation.douyinAccount,
                    identifierLabel: "抖音号",
                    identifier: AboutInformation.douyinID,
                    resourceName: "AuthorDouyin"
                )
                socialCard(
                    platform: "小红书",
                    account: AboutInformation.xiaohongshuAccount,
                    identifierLabel: "小红书号",
                    identifier: AboutInformation.xiaohongshuID,
                    resourceName: "AuthorXiaohongshu"
                )
            }
        }
    }

    private func socialCard(
        platform: String,
        account: String,
        identifierLabel: String,
        identifier: String,
        resourceName: String
    ) -> some View {
        AboutSocialCard(
            platform: platform,
            account: account,
            identifierLabel: identifierLabel,
            identifier: identifier,
            resourceName: resourceName
        )
        .frame(maxWidth: .infinity)
    }

    private func copyWeChatID() {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(AboutInformation.weChatID, forType: .string)

        copyFeedbackTask?.cancel()
        setCopyFeedback(true)
        copyFeedbackTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            setCopyFeedback(false)
        }
    }

    private func setCopyFeedback(_ copied: Bool) {
        if reduceMotion {
            copiedWeChatID = copied
        } else {
            withAnimation(.easeInOut(duration: 0.2)) {
                copiedWeChatID = copied
            }
        }
    }
}

private struct AboutSurface<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(18)
            .adaptiveRegularGlassRounded(cornerRadius: 20)
    }
}

private struct AboutSocialCard: View {
    let platform: String
    let account: String
    let identifierLabel: String
    let identifier: String
    let resourceName: String

    @State private var showingLargeImage = false

    private var resourceImage: NSImage? {
        guard let url = Bundle.main.url(forResource: resourceName, withExtension: "jpg") else {
            return nil
        }
        return NSImage(contentsOf: url)
    }

    var body: some View {
        AboutSurface {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(platform)
                        .font(.headline)
                    Text("\(account) · \(identifierLabel) \(identifier)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }

                Group {
                    if let resourceImage {
                        Image(nsImage: resourceImage)
                            .resizable()
                            .scaledToFit()
                    } else {
                        ContentUnavailableView(
                            "联系图片未找到",
                            systemImage: "photo.badge.exclamationmark",
                            description: Text("请重新安装 MiVibe Remote")
                        )
                    }
                }
                .frame(maxWidth: .infinity)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 14))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(
                    "\(platform)作者联系卡，账号\(account)，\(identifierLabel)\(identifier)，图片包含二维码"
                )

                Button {
                    showingLargeImage = true
                } label: {
                    Label("查看大图", systemImage: "arrow.up.left.and.arrow.down.right")
                        .frame(maxWidth: .infinity)
                }
                .adaptiveGlassButtonStyle()
                .disabled(resourceImage == nil)
                .accessibilityLabel("查看\(platform)联系图片大图")
            }
        }
        .sheet(isPresented: $showingLargeImage) {
            if let resourceImage {
                AboutImagePreview(
                    platform: platform,
                    account: account,
                    identifierLabel: identifierLabel,
                    identifier: identifier,
                    image: resourceImage
                )
            }
        }
    }
}

private struct AboutImagePreview: View {
    let platform: String
    let account: String
    let identifierLabel: String
    let identifier: String
    let image: NSImage

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("\(platform)联系图片")
                        .font(.title2.weight(.semibold))
                    Text("\(account) · \(identifierLabel) \(identifier)")
                        .font(.subheadline.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }

                Spacer(minLength: 16)

                Button("完成") {
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 18)

            Divider()

            ScrollView {
                VStack(spacing: 14) {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 720)
                        .background(
                            Color(nsColor: .windowBackgroundColor),
                            in: RoundedRectangle(cornerRadius: 16, style: .continuous)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .accessibilityLabel(
                            "\(platform)作者联系大图，账号\(account)，\(identifierLabel)\(identifier)，图片包含二维码"
                        )

                    Text("可使用手机打开对应平台，扫描原图中的二维码。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(24)
                .frame(maxWidth: .infinity)
            }
        }
        .frame(minWidth: 560, idealWidth: 760, minHeight: 620, idealHeight: 820)
        .background(.regularMaterial)
    }
}
