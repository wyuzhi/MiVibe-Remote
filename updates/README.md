# MiVibe Remote 更新源

macOS 使用 Sparkle 2，Windows 使用 WinSparkle。两端使用同一对 Ed25519
密钥，但分别读取同一 HTTPS 目录下的两个清单：

- `macos-appcast.xml`
- `windows-appcast.xml`

Sparkle 官方不建议在一个 appcast 中混放 macOS 和非 macOS 更新，所以这里
共用生成、签名和发布流程，但不共用单个 XML 文件。

## 密钥

只生成一次 Ed25519 密钥。私钥不能提交到 Git，也不能写进安装包。

```sh
python3 -m pip install -r scripts/requirements-updates.txt
./scripts/create-update-signing-key.sh /absolute/path/to/offline-backup
```

该目录必须离线备份。其中私钥及其 Base64 文件不得提交或发给用户；公钥必须
原样嵌入 macOS 和 Windows 客户端。脚本会给出不在终端打印私钥的 `gh`
配置命令。GitHub Actions Secret 名为：

- `UPDATE_ED25519_PRIVATE_KEY_BASE64`

再把公钥保存为 GitHub Actions Variable：

- `UPDATE_ED25519_PUBLIC_KEY`

构建应用时工作流统一传入：

- `MIVIBE_UPDATE_ED25519_PUBLIC_KEY`
- macOS 的 `MIVIBE_APPCAST_URL` 指向 `macos-appcast.xml`
- Windows 的 `MIVIBE_APPCAST_URL` 指向 `windows-appcast.xml`

发布时会校验二者是否匹配；只配置其中一项或两项都未配置时，仍可生成供用户
手工安装的 Release 安装包，但客户端会安全禁用自动更新，绝不会降级为无
签名更新。普通 PR 测试也不需要私钥。

## 外部更新源（正式发布必需）

源码仓库是私有仓库。私有 GitHub Release 的固定 URL 对没有 GitHub Token 的
Sparkle/WinSparkle 客户端会返回 404，因此构建不再回退到 GitHub Release
地址。tag、PR 和 main 构建缺少外部 `UPDATE_BASE_URL` 或公钥中的任意一项
时会安全禁用更新功能。没有配置 `UPDATE_BASE_URL` 的正式 Release 会跳过
稳定 feed 推广；一旦配置并启用推广，仍然要求完整的外部更新源、公私钥与
存储配置，缺少任何一项都会失败。

当前客户端不会携带会员令牌，所以 `UPDATE_BASE_URL`、两个 appcast 和其引用
的安装包必须能由已安装客户端直接通过 HTTPS 读取。若要按会员鉴权下载，必须
先实现客户端令牌和更新服务的短期授权，不能把 GitHub、R2 或 S3 密钥写进
客户端。

长期推荐使用 S3 或 Cloudflare R2。当前首个正式更新源复用 MiVibe 官网的
公开静态目录；客户端和官网按钮都读取：

```text
https://gssghh.online/downloads/mivibe/updates/
```

`.github/workflows/prepare-website-update.yml` 会使用 GitHub Secret 中的私钥生成
一个经过签名和验证的官网更新包。下载该 Actions artifact 后，把其中全部文件
原样放入官网项目的 `public/downloads/mivibe/updates/` 并部署。私钥始终留在
GitHub Actions 中，不会进入官网仓库、安装包或本地下载包。

需要完全自动上传时再迁移到 S3 或 Cloudflare R2：

设置 Repository Variable：

- `UPDATE_BASE_URL`：客户端可访问的目录，例如
  `https://updates.example.com/stable`
- `UPDATE_S3_PREFIX`：可选，bucket 内目录，例如 `stable`

设置 Repository Secrets：

- `UPDATE_S3_ENDPOINT`
- `UPDATE_S3_BUCKET`
- `UPDATE_S3_ACCESS_KEY_ID`
- `UPDATE_S3_SECRET_ACCESS_KEY`

上述配置在稳定更新推广时全部必填，缺一项即失败。`UPDATE_BASE_URL` 必须与
bucket/prefix 对应，并且两个 appcast 可以从该 URL 直接读取。URL 不得包含
用户名、密码、查询参数或片段，防止长期令牌被编译进客户端。

## 候选构建与稳定推广

`.github/workflows/build.yml` 只负责测试、构建并把 DMG/EXE 上传到对应的候选
Release。创建 tag 或 draft Release **不会**再修改已安装客户端读取的稳定
feed。

`.github/workflows/promote-updates.yml` 仅在以下情况运行：

1. 非 draft、非 prerelease 的 GitHub Release 正式发布；或
2. 人工运行工作流，指定已经发布的稳定 tag，并输入 `PROMOTE_STABLE`。

推广顺序固定为：

1. 从 tag 源码读取 macOS 短版本/内部构建号，并精确要求
   `MiVibe-Remote-<短版本>.dmg` 与 `MiVibeRemoteSetup-<tag去掉v>.exe`；
2. 校验私钥、公钥、外部 URL 和 R2/S3 配置；
3. 生成并验证 Ed25519 签名；
4. 读取现有两个 appcast：首次发布允许两者都返回 404，否则要求 macOS
   `CFBundleVersion` 和 Windows 版本都严格大于线上版本；
5. 先上传带版本号的 DMG/EXE，并从公网重新下载校验 SHA-256；
6. 安装包公网校验通过后，最后替换两个 appcast；
7. 从公网读取并逐字节验证新 feed；
8. 成功后把相同文件保存到私有 `update-feed` Release 作为归档。

Release 发布事件和 tag 构建可能并行：推广工作流会每 30 秒检查一次 Release
资产，最多等待 15 分钟。只有文件名与 tag/Info.plist 精确匹配时才继续；错误
版本、额外版本、超时或缺失都会失败。

私有 `update-feed` Release 从不作为客户端源。若发布工作流失败，修复配置后用
人工 `PROMOTE_STABLE` 重试，不要重新打同名 tag。

## 本地生成和验证

```sh
python3 -m venv .venv-updates
.venv-updates/bin/pip install -r scripts/requirements-updates.txt
.venv-updates/bin/python scripts/generate_appcasts.py \
  --mac-asset /path/MiVibe-Remote-0.1.10.dmg \
  --windows-asset /path/MiVibeRemoteSetup-0.1.16.exe \
  --private-key-file /safe/path/mivibe-update-private.pem \
  --expected-public-key '客户端内置的 Base64 公钥' \
  --mac-build-version 11 \
  --base-url https://updates.example.com/stable \
  --output-dir /tmp/mivibe-appcasts
```

运行测试：

```sh
python3 -m unittest scripts.tests.test_generate_appcasts -v
```

输出的 `update-manifest.json` 包含公钥、文件 SHA-256、下载地址和签名，方便
发布后核查；它不包含私钥。

Windows feed 会给 Inno Setup 传递
`/SILENT /SP- /NOICONS /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /UPDATED`。
`/UPDATED` 是 MiVibe 安装器内部约定，用于
跳过在线升级时不需要的驱动检查，并在替换程序后重新启动应用。
