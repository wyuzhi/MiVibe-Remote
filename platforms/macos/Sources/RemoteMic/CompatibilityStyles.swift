import SwiftUI

/// Keeps the macOS 26 Liquid Glass appearance while providing a native,
/// material-based presentation on macOS 15.
struct AdaptiveGlassEffectContainer<Content: View>: View {
    let spacing: CGFloat
    private let content: Content

    init(spacing: CGFloat, @ViewBuilder content: () -> Content) {
        self.spacing = spacing
        self.content = content()
    }

    @ViewBuilder
    var body: some View {
        if #available(macOS 26.0, *) {
            GlassEffectContainer(spacing: spacing) {
                content
            }
        } else {
            content
        }
    }
}

extension View {
    @ViewBuilder
    func adaptiveSoftTopScrollEdge() -> some View {
        if #available(macOS 26.0, *) {
            scrollEdgeEffectStyle(.soft, for: .top)
        } else {
            self
        }
    }

    @ViewBuilder
    func adaptiveGlassButtonStyle() -> some View {
        if #available(macOS 26.0, *) {
            buttonStyle(.glass)
        } else {
            buttonStyle(.bordered)
        }
    }

    @ViewBuilder
    func adaptiveProminentGlassButtonStyle() -> some View {
        if #available(macOS 26.0, *) {
            buttonStyle(.glassProminent)
        } else {
            buttonStyle(.borderedProminent)
        }
    }

    @ViewBuilder
    func adaptiveRegularGlassRounded(cornerRadius: CGFloat) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        if #available(macOS 26.0, *) {
            glassEffect(.regular, in: shape)
        } else {
            background(.regularMaterial, in: shape)
                .overlay(shape.stroke(Color.primary.opacity(0.08), lineWidth: 1))
        }
    }

    @ViewBuilder
    func adaptiveTintedGlassRounded(
        cornerRadius: CGFloat,
        tint: Color,
        interactive: Bool = false
    ) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        if #available(macOS 26.0, *) {
            if interactive {
                glassEffect(.clear.tint(tint).interactive(), in: shape)
            } else {
                glassEffect(.clear.tint(tint), in: shape)
            }
        } else {
            background(tint, in: shape)
                .overlay(shape.stroke(tint.opacity(0.55), lineWidth: 1))
        }
    }

    @ViewBuilder
    func adaptiveTintedGlassCircle(_ tint: Color) -> some View {
        if #available(macOS 26.0, *) {
            glassEffect(.clear.tint(tint), in: Circle())
        } else {
            background(tint, in: Circle())
                .overlay(Circle().stroke(tint.opacity(0.55), lineWidth: 1))
        }
    }

    @ViewBuilder
    func adaptiveTintedGlassCapsule(_ tint: Color) -> some View {
        if #available(macOS 26.0, *) {
            glassEffect(.clear.tint(tint), in: Capsule())
        } else {
            background(tint, in: Capsule())
                .overlay(Capsule().stroke(tint.opacity(0.55), lineWidth: 1))
        }
    }
}
