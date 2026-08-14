"""Native Tk About window for the standalone Windows application."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import ImageTk

from standalone.about_info import (
    AUTHOR_NAME,
    SOCIAL_PROFILES,
    WECHAT_ID,
    SocialProfile,
    load_about_image,
)

BACKGROUND = "#f3f7fc"
NAVY = "#102342"
BLUE = "#1677ff"
TEXT = "#13213a"
MUTED = "#66758a"
WHITE = "#ffffff"
BORDER = "#dce6f2"


def about_window_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Fit the preferred 680x700 window on small or scaled displays."""

    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("screen dimensions must be positive")
    width = min(680, max(320, screen_width - 48), screen_width)
    height = min(700, max(360, screen_height - 96), screen_height)
    return width, height


def detail_window_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Fit the preferred 760x820 social-image viewer on the current display."""

    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("screen dimensions must be positive")
    width = min(760, max(340, screen_width - 48), screen_width)
    height = min(820, max(380, screen_height - 80), screen_height)
    return width, height


class AboutWindow:
    """Own a single, non-modal About ``Toplevel`` and its image resources."""

    def __init__(
        self,
        owner: tk.Misc,
        app_name: str,
        app_version: str,
        check_updates: Callable[[], None],
        logger: Callable[[str], None],
    ) -> None:
        self.owner = owner
        self.app_name = app_name
        self.app_version = app_version
        self.check_updates = check_updates
        self.logger = logger
        self.window: tk.Toplevel | None = None
        self.photos: list[ImageTk.PhotoImage] = []
        self.feedback: tk.StringVar | None = None
        self._feedback_timer: str | None = None
        self.detail_window: tk.Toplevel | None = None
        self.detail_content: tk.Frame | None = None
        self.detail_canvas: tk.Canvas | None = None
        self.detail_photo: ImageTk.PhotoImage | None = None
        self.detail_image_side = 680

    def show(self) -> None:
        """Create the window once, or activate the existing instance."""

        if self._window_exists():
            assert self.window is not None
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            return
        self._build()

    def close(self) -> None:
        window = self.window
        self._clear_feedback_timer()
        self.close_social_detail()
        self.window = None
        self.photos.clear()
        self.feedback = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def _window_exists(self) -> bool:
        if self.window is None:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            self.window = None
            self.photos.clear()
            return False

    def _build(self) -> None:
        window = tk.Toplevel(self.owner)
        self.window = window
        self.photos.clear()
        self.feedback = tk.StringVar(master=window, value="")
        window.title(f"关于 {self.app_name}")
        window.configure(background=BACKGROUND)
        window.resizable(True, True)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _event: self.close())
        window.bind("<Control-w>", lambda _event: self.close())
        window.bind("<Control-c>", lambda _event: self.copy_wechat())
        window.bind("<Destroy>", self._on_destroy, add="+")

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        width, height = about_window_size(screen_width, screen_height)
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(min(520, width), min(480, height))

        shell = tk.Frame(window, background=BACKGROUND)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            shell,
            background=BACKGROUND,
            borderwidth=0,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, background=BACKGROUND)
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_id, width=event.width),
        )
        window.bind("<MouseWheel>", lambda event: self._scroll(canvas, event))
        window.bind("<Prior>", lambda _event: canvas.yview_scroll(-1, "pages"))
        window.bind("<Next>", lambda _event: canvas.yview_scroll(1, "pages"))
        window.bind("<Home>", lambda _event: canvas.yview_moveto(0.0))
        window.bind("<End>", lambda _event: canvas.yview_moveto(1.0))

        self._build_header(content)
        self._build_author_card(content)
        image_side = max(130, min(245, (width - 128) // 2))
        self._build_social_cards(content, image_side)
        self._build_footer(content)

        window.after_idle(window.focus_force)

    def _build_header(self, parent: tk.Misc) -> None:
        header = tk.Frame(parent, background=NAVY, padx=28, pady=24)
        header.pack(fill="x")
        tk.Label(
            header,
            text=self.app_name,
            background=NAVY,
            foreground=WHITE,
            font=("Microsoft YaHei UI", 21, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"Windows · v{self.app_version}",
            background=NAVY,
            foreground="#a9c8f5",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(5, 0))

    def _build_author_card(self, parent: tk.Misc) -> None:
        card = self._card(parent, 24, 18)
        card.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(
            card,
            text=f"作者 · {AUTHOR_NAME}",
            background=WHITE,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            card,
            text="联系作者、反馈问题或获取会员版本",
            background=WHITE,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 15))
        tk.Label(
            card,
            text="微信",
            background=WHITE,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=2, column=0, sticky="w")
        tk.Label(
            card,
            text=WECHAT_ID,
            background=WHITE,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).grid(row=2, column=1, sticky="w", padx=(12, 16))
        copy_button = ttk.Button(card, text="复制微信号", command=self.copy_wechat)
        copy_button.grid(row=2, column=2, sticky="e")
        copy_button.bind("<Return>", lambda _event: copy_button.invoke())
        card.grid_columnconfigure(1, weight=1)
        tk.Label(
            card,
            textvariable=self.feedback,
            background=WHITE,
            foreground=BLUE,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _build_social_cards(self, parent: tk.Misc, image_side: int) -> None:
        section = tk.Frame(parent, background=BACKGROUND)
        section.pack(fill="x", padx=24, pady=(0, 12))
        section.grid_columnconfigure(0, weight=1, uniform="social")
        section.grid_columnconfigure(1, weight=1, uniform="social")
        for column, profile in enumerate(SOCIAL_PROFILES):
            card = self._card(section, 14, 14)
            card.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0, 6) if column == 0 else (6, 0),
            )
            try:
                display_image = load_about_image(profile.image_filename, image_side)
                photo = ImageTk.PhotoImage(display_image, master=self.window)
                self.photos.append(photo)
                tk.Label(
                    card,
                    image=photo,
                    background=WHITE,
                    borderwidth=0,
                ).pack(pady=(0, 12))
            except (OSError, ValueError, tk.TclError) as exc:
                self.logger(
                    "About image unavailable "
                    f"{profile.image_filename}: {type(exc).__name__}: {exc}"
                )
                tk.Label(
                    card,
                    text=f"{profile.accessible_text}\n图片暂不可用",
                    background="#edf3fa",
                    foreground=MUTED,
                    width=24,
                    height=8,
                    font=("Microsoft YaHei UI", 10),
                ).pack(fill="x", pady=(0, 12))
            tk.Label(
                card,
                text=profile.platform,
                background=WHITE,
                foreground=TEXT,
                font=("Microsoft YaHei UI", 12, "bold"),
            ).pack(anchor="w")
            tk.Label(
                card,
                text=f"{profile.handle} / {profile.account_id}",
                background=WHITE,
                foreground=MUTED,
                font=("Microsoft YaHei UI", 9),
                wraplength=max(130, image_side),
                justify="left",
            ).pack(anchor="w", pady=(4, 0))
            detail_button = ttk.Button(
                card,
                text="查看大图",
                command=lambda selected=profile: self.show_social_detail(selected),
            )
            detail_button.pack(fill="x", pady=(12, 0))
            detail_button.bind(
                "<Return>",
                lambda _event, button=detail_button: button.invoke(),
            )

    def show_social_detail(self, profile: SocialProfile) -> None:
        """Show one full author image, reusing the same detail ``Toplevel``."""

        if self._detail_window_exists():
            self._render_social_detail(profile)
            assert self.detail_window is not None
            self.detail_window.deiconify()
            self.detail_window.lift()
            self.detail_window.focus_force()
            return
        self._build_social_detail(profile)

    def close_social_detail(self) -> None:
        detail = self.detail_window
        self.detail_window = None
        self.detail_content = None
        self.detail_canvas = None
        self.detail_photo = None
        if detail is not None:
            try:
                detail.destroy()
            except tk.TclError:
                pass

    def _detail_window_exists(self) -> bool:
        if self.detail_window is None:
            return False
        try:
            return bool(self.detail_window.winfo_exists())
        except tk.TclError:
            self.detail_window = None
            self.detail_content = None
            self.detail_canvas = None
            self.detail_photo = None
            return False

    def _build_social_detail(self, profile: SocialProfile) -> None:
        detail = tk.Toplevel(self.owner)
        self.detail_window = detail
        detail.configure(background=BACKGROUND)
        detail.resizable(True, True)
        detail.protocol("WM_DELETE_WINDOW", self.close_social_detail)
        detail.bind("<Escape>", lambda _event: self.close_social_detail())
        detail.bind("<Control-w>", lambda _event: self.close_social_detail())
        detail.bind("<Destroy>", self._on_detail_destroy, add="+")

        screen_width = detail.winfo_screenwidth()
        screen_height = detail.winfo_screenheight()
        width, height = detail_window_size(screen_width, screen_height)
        self.detail_image_side = max(220, min(680, width - 80))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        detail.geometry(f"{width}x{height}+{x}+{y}")
        detail.minsize(min(540, width), min(500, height))

        shell = tk.Frame(detail, background=BACKGROUND)
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            shell,
            background=BACKGROUND,
            borderwidth=0,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, background=BACKGROUND)
        content_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_id, width=event.width),
        )
        detail.bind("<MouseWheel>", lambda event: self._scroll(canvas, event))
        detail.bind("<Prior>", lambda _event: canvas.yview_scroll(-1, "pages"))
        detail.bind("<Next>", lambda _event: canvas.yview_scroll(1, "pages"))
        detail.bind("<Home>", lambda _event: canvas.yview_moveto(0.0))
        detail.bind("<End>", lambda _event: canvas.yview_moveto(1.0))
        self.detail_content = content
        self.detail_canvas = canvas
        self._render_social_detail(profile)
        detail.after_idle(detail.focus_force)

    def _render_social_detail(self, profile: SocialProfile) -> None:
        detail = self.detail_window
        content = self.detail_content
        canvas = self.detail_canvas
        if detail is None or content is None or canvas is None:
            return
        detail.title(f"{profile.platform} · {profile.handle}")
        for child in content.winfo_children():
            child.destroy()
        self.detail_photo = None

        header = tk.Frame(content, background=NAVY, padx=28, pady=20)
        header.pack(fill="x")
        tk.Label(
            header,
            text=profile.platform,
            background=NAVY,
            foreground=WHITE,
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"{profile.handle} / {profile.account_id}",
            background=NAVY,
            foreground="#a9c8f5",
            font=("Microsoft YaHei UI", 11),
        ).pack(anchor="w", pady=(4, 0))

        # 16px canvas scrollbar + 32px outer margin + 32px card padding leave
        # exactly 680px for the full image in the preferred 760px window.
        card = self._card(content, 16, 16)
        card.pack(fill="x", padx=16, pady=20)
        try:
            display_image = load_about_image(
                profile.image_filename,
                self.detail_image_side,
            )
            photo = ImageTk.PhotoImage(display_image, master=detail)
            self.detail_photo = photo
            tk.Label(
                card,
                image=photo,
                background=WHITE,
                borderwidth=0,
            ).pack()
        except (OSError, ValueError, tk.TclError) as exc:
            self.logger(
                "About detail image unavailable "
                f"{profile.image_filename}: {type(exc).__name__}: {exc}"
            )
            tk.Label(
                card,
                text=f"{profile.accessible_text}\n图片暂不可用",
                background="#edf3fa",
                foreground=MUTED,
                font=("Microsoft YaHei UI", 12),
                height=12,
            ).pack(fill="x")
        tk.Label(
            card,
            text=profile.accessible_text,
            background=WHITE,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", pady=(16, 0))

        footer = tk.Frame(content, background=BACKGROUND)
        footer.pack(fill="x", padx=24, pady=(0, 24))
        close_button = ttk.Button(
            footer,
            text="关闭",
            command=self.close_social_detail,
        )
        close_button.pack(side="right")
        close_button.bind("<Return>", lambda _event: close_button.invoke())
        canvas.yview_moveto(0.0)
        detail.after_idle(self._refresh_detail_scrollregion)

    def _refresh_detail_scrollregion(self) -> None:
        if not self._detail_window_exists() or self.detail_canvas is None:
            return
        self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all"))

    def _build_footer(self, parent: tk.Misc) -> None:
        footer = tk.Frame(parent, background=BACKGROUND)
        footer.pack(fill="x", padx=24, pady=(0, 24))
        update_button = ttk.Button(
            footer,
            text="检查更新",
            command=self.check_updates,
        )
        update_button.pack(side="left")
        close_button = ttk.Button(footer, text="关闭", command=self.close)
        close_button.pack(side="right")
        update_button.bind("<Return>", lambda _event: update_button.invoke())
        close_button.bind("<Return>", lambda _event: close_button.invoke())

    @staticmethod
    def _card(parent: tk.Misc, padx: int, pady: int) -> tk.Frame:
        return tk.Frame(
            parent,
            background=WHITE,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            padx=padx,
            pady=pady,
        )

    @staticmethod
    def _scroll(canvas: tk.Canvas, event: tk.Event) -> str:
        if event.delta:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def copy_wechat(self) -> None:
        try:
            self.owner.clipboard_clear()
            self.owner.clipboard_append(WECHAT_ID)
        except tk.TclError as exc:
            self.logger(f"Could not copy WeChat ID: {type(exc).__name__}: {exc}")
            if self.feedback is not None:
                self.feedback.set("复制失败，请手动记录微信号 wydyid")
            return
        if self.feedback is not None:
            self.feedback.set(f"已复制微信号 {WECHAT_ID}")
        self._clear_feedback_timer()
        if self.window is not None:
            self._feedback_timer = self.window.after(2500, self._clear_feedback)

    def _clear_feedback(self) -> None:
        self._feedback_timer = None
        if self.feedback is not None:
            self.feedback.set("")

    def _clear_feedback_timer(self) -> None:
        if self._feedback_timer is None or self.window is None:
            self._feedback_timer = None
            return
        try:
            self.window.after_cancel(self._feedback_timer)
        except tk.TclError:
            pass
        self._feedback_timer = None

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.window:
            return
        self._clear_feedback_timer()
        self.close_social_detail()
        self.window = None
        self.photos.clear()
        self.feedback = None

    def _on_detail_destroy(self, event: tk.Event) -> None:
        if event.widget is not self.detail_window:
            return
        self.detail_window = None
        self.detail_content = None
        self.detail_canvas = None
        self.detail_photo = None
